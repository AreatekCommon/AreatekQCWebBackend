from __future__ import annotations

import json
from typing import Any, Optional

from app.eki.messages import TrajectoryPoint
from app.eki.turntable_units import quantize_turntable_angle

POSITION_TYPES = frozenset({"home", "transition", "basic_scan", "advanced_scan", "end"})
POINT_TYPE_BY_POSITION = {
    "home": "home",
    "transition": "transition",
    "basic_scan": "scan",
    "advanced_scan": "scan",
    "end": "end",
}
JOINT_KEYS = ("J1", "J2", "J3", "J4", "J5", "J6")
DEFAULT_MOTION_VALUE = 50.0


def _is_full_revolution(start_angle: float, end_angle: float) -> bool:
    start = quantize_turntable_angle(start_angle)
    end = quantize_turntable_angle(end_angle)
    return (start == 0.0 and end == 360.0) or (start == 360.0 and end == 0.0)


def expand_turntable_angles(start_angle: float, end_angle: float, scan_count: int) -> list[float]:
    if scan_count < 1:
        raise ValueError(f"scan_count must be >= 1, received {scan_count}")

    start = quantize_turntable_angle(start_angle)
    end = quantize_turntable_angle(end_angle)

    if _is_full_revolution(start_angle, end_angle):
        if scan_count == 1:
            return [end]
        step = 360.0 / scan_count
        if start == 0.0 and end == 360.0:
            return [quantize_turntable_angle(step * (index + 1)) for index in range(scan_count)]
        return [quantize_turntable_angle(360.0 - step * (index + 1)) for index in range(scan_count)]

    if scan_count == 1:
        return [quantize_turntable_angle(start_angle)]

    step = (end_angle - start_angle) / (scan_count - 1)
    return [
        quantize_turntable_angle(start_angle + index * step)
        for index in range(scan_count)
    ]


def expand_turntable_angles_step(start_angle: float, scan_count: int, step_angle: float) -> list[float]:
    if scan_count < 1:
        raise ValueError(f"scan_count must be >= 1, received {scan_count}")
    if step_angle == 0:
        raise ValueError("step_angle must be non-zero")

    return [
        quantize_turntable_angle(start_angle + index * step_angle)
        for index in range(scan_count)
    ]


def _parse_exposure_fields(
    item: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None]:
    raw = item.get("exposure")
    if not isinstance(raw, dict):
        return None, None, None, None

    def optional_int(key: str) -> int | None:
        if key not in raw or raw[key] is None:
            return None
        return int(raw[key])

    return (
        optional_int("val1"),
        optional_int("val2"),
        optional_int("val3"),
        optional_int("marker_exp"),
    )


def _trajectory_point(
    *,
    next_index: int,
    point_type: str,
    comment: str,
    speed: float,
    acceleration: float,
    a7: float,
    a7_speed: float,
    a7_acceleration: float,
    axes: list[float],
    exposure: tuple[int | None, int | None, int | None, int | None],
) -> TrajectoryPoint:
    val1, val2, val3, marker_exp = exposure
    return TrajectoryPoint(
        index=next_index,
        guid="",
        point_type=point_type,
        comment=comment,
        speed=speed,
        acceleration=acceleration,
        a7=a7,
        a7_speed=a7_speed,
        a7_acceleration=a7_acceleration,
        axes=axes,
        exposure_val1=val1,
        exposure_val2=val2,
        exposure_val3=val3,
        exposure_marker_exp=marker_exp,
    )


def load_trajectory_from_json(path: str) -> list[TrajectoryPoint]:
    with open(path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)
    return parse_path_document(data)


def merge_node_point(node: dict[str, Any], point: dict[str, Any]) -> dict[str, Any]:
    name = str(point.get("name") or point.get("comment") or point.get("id", "")).strip()
    merged: dict[str, Any] = {
        "id": str(point.get("id", "")),
        "name": name,
        "axes": point.get("axes") or {},
        "type": str(node.get("type", "")).strip(),
        "turntable": node.get("turntable") or {},
        "motion": node.get("motion") or {},
    }
    if isinstance(node.get("exposure"), dict):
        merged["exposure"] = node["exposure"]
    return merged


def parse_path_document(
    data: dict[str, Any],
    *,
    allowed_point_types: Optional[set[str] | list[str]] = None,
) -> list[TrajectoryPoint]:
    from app.trajectory.path_nodes import ordered_nodes

    raw_points = data.get("points")
    raw_nodes = data.get("nodes")
    if not isinstance(raw_points, list):
        raise ValueError("JSON is missing required 'points' array")
    if not isinstance(raw_nodes, list):
        raise ValueError("JSON is missing required 'nodes' array")

    point_by_id = {
        str(point.get("id", "")): point
        for point in raw_points
        if isinstance(point, dict) and point.get("id")
    }

    from app.trajectory.routing import build_execution_items_with_transitions

    raw_safe_route_ids = data.get("safe_route_ids")
    raw_safe_routes = data.get("safe_routes")
    safe_route_ids = (
        [str(item) for item in raw_safe_route_ids]
        if isinstance(raw_safe_route_ids, list)
        else []
    )
    safe_routes = (
        raw_safe_routes
        if isinstance(raw_safe_routes, list)
        else []
    )

    merged_items = build_execution_items_with_transitions(
        point_by_id,
        ordered_nodes(raw_nodes),
        safe_route_ids,
        safe_routes,
    )

    return _expand_position_items(merged_items, allowed_point_types=allowed_point_types)


def parse_positions_json(
    data: dict[str, Any],
    *,
    allowed_point_types: Optional[set[str] | list[str]] = None,
) -> list[TrajectoryPoint]:
    from app.trajectory.path_normalize import normalize_path_document

    normalized = normalize_path_document(data)
    return parse_path_document(normalized, allowed_point_types=allowed_point_types)


def _expand_position_items(
    items: list[dict[str, Any]],
    *,
    allowed_point_types: Optional[set[str] | list[str]] = None,
) -> list[TrajectoryPoint]:
    allowed = set(allowed_point_types) if allowed_point_types else None
    points: list[TrajectoryPoint] = []
    next_index = 0

    for position_index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Position #{position_index} must be an object")

        position_type = _require_str(item, "type", position_index)
        if position_type not in POSITION_TYPES:
            raise ValueError(
                f"Position #{position_index} has unknown type '{position_type}'. "
                f"Expected one of: {', '.join(sorted(POSITION_TYPES))}"
            )

        point_type = POINT_TYPE_BY_POSITION[position_type]
        if allowed is not None and point_type not in allowed:
            continue

        axes = _parse_axes(item.get("axes"), position_index)
        turntable = item.get("turntable") or {}
        if not isinstance(turntable, dict):
            raise ValueError(f"Position #{position_index} 'turntable' must be an object")

        motion = item.get("motion") or {}
        if not isinstance(motion, dict):
            raise ValueError(f"Position #{position_index} 'motion' must be an object")

        speed = float(motion.get("speed", DEFAULT_MOTION_VALUE))
        acceleration = float(motion.get("acceleration", DEFAULT_MOTION_VALUE))
        a7_speed = float(turntable.get("speed", DEFAULT_MOTION_VALUE))
        a7_acceleration = float(turntable.get("acceleration", DEFAULT_MOTION_VALUE))
        base_comment = str(item.get("name") or item.get("comment") or "")
        exposure = _parse_exposure_fields(item)

        if position_type in {"home", "transition", "basic_scan", "end"}:
            if "angle" not in turntable:
                raise ValueError(f"Position #{position_index} ({position_type}) requires turntable.angle")

            points.append(
                _trajectory_point(
                    next_index=next_index,
                    point_type=point_type,
                    comment=base_comment,
                    speed=speed,
                    acceleration=acceleration,
                    a7=quantize_turntable_angle(float(turntable["angle"])),
                    a7_speed=a7_speed,
                    a7_acceleration=a7_acceleration,
                    axes=axes,
                    exposure=exposure if position_type == "basic_scan" else (None, None, None, None),
                )
            )
            next_index += 1
            continue

        scan_mode = str(turntable.get("advanced_scan_mode", "range")).strip().lower()
        if scan_mode not in {"range", "step"}:
            raise ValueError(
                f"Position #{position_index} (advanced_scan) has invalid turntable.advanced_scan_mode: {scan_mode!r}"
            )

        for field_name in ("start_angle", "scan_count"):
            if field_name not in turntable:
                raise ValueError(
                    f"Position #{position_index} (advanced_scan) requires turntable.{field_name}"
                )

        scan_count = int(turntable["scan_count"])
        start_angle = float(turntable["start_angle"])

        if scan_mode == "step":
            if "step_angle" not in turntable:
                raise ValueError(
                    f"Position #{position_index} (advanced_scan) requires turntable.step_angle"
                )
            step_angle = float(turntable["step_angle"])
            turntable_angles = expand_turntable_angles_step(start_angle, scan_count, step_angle)
        else:
            for field_name in ("end_angle",):
                if field_name not in turntable:
                    raise ValueError(
                        f"Position #{position_index} (advanced_scan) requires turntable.{field_name}"
                    )
            end_angle = float(turntable["end_angle"])
            turntable_angles = expand_turntable_angles(start_angle, end_angle, scan_count)

        for step_index, angle in enumerate(turntable_angles, start=1):
            step_comment = base_comment
            if base_comment:
                step_comment = f"{base_comment} ({step_index}/{scan_count})"
            else:
                step_comment = f"advanced_scan ({step_index}/{scan_count})"

            points.append(
                _trajectory_point(
                    next_index=next_index,
                    point_type=point_type,
                    comment=step_comment,
                    speed=speed,
                    acceleration=acceleration,
                    a7=angle,
                    a7_speed=a7_speed,
                    a7_acceleration=a7_acceleration,
                    axes=list(axes),
                    exposure=exposure,
                )
            )
            next_index += 1

    return points


def _require_str(item: dict[str, Any], field_name: str, position_index: int) -> str:
    value = item.get(field_name)
    if value is None or not str(value).strip():
        raise ValueError(f"Position #{position_index} is missing required field '{field_name}'")
    return str(value).strip()


def _parse_axes(raw_axes: Any, position_index: int) -> list[float]:
    if not isinstance(raw_axes, dict):
        raise ValueError(f"Position #{position_index} requires 'axes' object with J1..J6")

    missing = [key for key in JOINT_KEYS if key not in raw_axes]
    if missing:
        raise ValueError(
            f"Position #{position_index} axes missing required joints: {', '.join(missing)}"
        )

    return [float(raw_axes[key]) for key in JOINT_KEYS]


def resolve_jog_target(position: dict[str, Any]) -> tuple[list[float], float]:
    position_type = str(position.get("type", "")).strip()
    if position_type not in POSITION_TYPES:
        raise ValueError(
            f"Unknown position type '{position_type}'. "
            f"Expected one of: {', '.join(sorted(POSITION_TYPES))}"
        )

    axes = _parse_axes(position.get("axes"), 0)
    turntable = position.get("turntable") or {}
    if not isinstance(turntable, dict):
        raise ValueError("Position 'turntable' must be an object")

    if position_type == "advanced_scan":
        if "start_angle" not in turntable:
            raise ValueError("advanced_scan position requires turntable.start_angle")
        turntable_angle = float(turntable["start_angle"])
    else:
        turntable_angle = float(turntable.get("angle", 0.0))

    return axes, quantize_turntable_angle(turntable_angle)
