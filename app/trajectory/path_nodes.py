from __future__ import annotations

import copy
from typing import Any

DEFAULT_MOTION = {"speed": 50.0, "acceleration": 50.0}
DEFAULT_TURNTABLE_ANGLE = {"angle": 0.0, "speed": 50.0, "acceleration": 50.0}


def _point_name(source: dict[str, Any]) -> str:
    for key in ("name", "comment"):
        value = str(source.get(key, "")).strip()
        if value:
            return value
    point_id = str(source.get("id", "")).strip()
    return point_id or "Point"


def _catalog_point(source: dict[str, Any]) -> dict[str, Any]:
    point_id = str(source.get("id", "")).strip()
    return {
        "id": point_id,
        "name": _point_name(source),
        "axes": copy.deepcopy(source.get("axes") or {}),
    }


def _node_settings(source: dict[str, Any]) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    turntable = source.get("turntable")
    if isinstance(turntable, dict) and turntable:
        settings["turntable"] = copy.deepcopy(turntable)
    else:
        settings["turntable"] = copy.deepcopy(DEFAULT_TURNTABLE_ANGLE)

    motion = source.get("motion")
    if isinstance(motion, dict) and motion:
        settings["motion"] = copy.deepcopy(motion)
    else:
        settings["motion"] = copy.deepcopy(DEFAULT_MOTION)

    exposure = source.get("exposure")
    if isinstance(exposure, dict):
        settings["exposure"] = copy.deepcopy(exposure)
    return settings


def _build_node(entry: dict[str, Any], *, node_id: str, point_id: str) -> dict[str, Any]:
    node = {
        "id": node_id,
        "type": str(entry.get("type", "basic_scan")).strip(),
        "point_id": point_id,
        **_node_settings(entry),
    }
    return node


def migrate_legacy_positions(positions: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from app.trajectory.position_ids import axes_key

    points: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    axes_to_point_index: dict[tuple[float, ...], int] = {}

    for index, entry in enumerate(positions):
        if not isinstance(entry, dict):
            continue

        raw_axes = entry.get("axes") or {}
        if not isinstance(raw_axes, dict):
            raw_axes = {}
        key = axes_key(raw_axes)

        if key not in axes_to_point_index:
            point = _catalog_point(entry)
            if not point["id"]:
                point["id"] = str(index)
            axes_to_point_index[key] = len(points)
            points.append(point)
        else:
            point_index = axes_to_point_index[key]
            existing = points[point_index]
            incoming_name = _point_name(entry)
            if incoming_name and existing.get("name") == existing.get("id"):
                existing["name"] = incoming_name

        point_id = points[axes_to_point_index[key]]["id"]
        if str(entry.get("type", "")).strip().lower() == "transition":
            continue
        nodes.append(_build_node(entry, node_id=str(index), point_id=point_id))

    link_node_chain(nodes)
    layout_nodes_linear(nodes)
    return points, nodes


def split_settings_from_points(
    points: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> None:
    point_by_id = {
        str(point.get("id", "")): point
        for point in points
        if isinstance(point, dict) and point.get("id")
    }

    for node in nodes:
        if not isinstance(node, dict):
            continue
        point = point_by_id.get(str(node.get("point_id", "")))
        if not isinstance(point, dict):
            continue

        if "turntable" not in node and isinstance(point.get("turntable"), dict):
            node["turntable"] = copy.deepcopy(point["turntable"])
        if "motion" not in node and isinstance(point.get("motion"), dict):
            node["motion"] = copy.deepcopy(point["motion"])
        if "exposure" not in node and isinstance(point.get("exposure"), dict):
            node["exposure"] = copy.deepcopy(point["exposure"])

        if "turntable" not in node:
            node["turntable"] = copy.deepcopy(DEFAULT_TURNTABLE_ANGLE)
        if "motion" not in node:
            node["motion"] = copy.deepcopy(DEFAULT_MOTION)

    for point in points:
        if not isinstance(point, dict):
            continue
        if "name" not in point or not str(point.get("name", "")).strip():
            point["name"] = _point_name(point)
        point.pop("comment", None)
        point.pop("turntable", None)
        point.pop("motion", None)
        point.pop("exposure", None)


def strip_points_catalog(points: list[dict[str, Any]]) -> None:
    for point in points:
        if not isinstance(point, dict):
            continue
        if "name" not in point or not str(point.get("name", "")).strip():
            point["name"] = _point_name(point)
        point.pop("comment", None)
        point.pop("turntable", None)
        point.pop("motion", None)
        point.pop("exposure", None)


def ensure_node_defaults(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if "turntable" not in node or not isinstance(node.get("turntable"), dict):
            node["turntable"] = copy.deepcopy(DEFAULT_TURNTABLE_ANGLE)
        if "motion" not in node or not isinstance(node.get("motion"), dict):
            node["motion"] = copy.deepcopy(DEFAULT_MOTION)

        position_type = str(node.get("type", "")).strip()
        turntable = node["turntable"]
        if position_type == "advanced_scan":
            if "advanced_scan_mode" not in turntable:
                turntable["advanced_scan_mode"] = "range"
            scan_mode = str(turntable.get("advanced_scan_mode", "range")).strip().lower()
            if "start_angle" not in turntable:
                turntable["start_angle"] = float(turntable.get("angle", 0.0))
            if "scan_count" not in turntable or int(turntable.get("scan_count") or 0) < 1:
                turntable["scan_count"] = 1
            if scan_mode == "step":
                if "step_angle" not in turntable:
                    turntable["step_angle"] = 90.0
            else:
                turntable["advanced_scan_mode"] = "range"
                if "end_angle" not in turntable:
                    turntable["end_angle"] = 360.0
        elif "angle" not in turntable:
            turntable["angle"] = float(turntable.get("start_angle", 0.0))


def has_explicit_node_links(nodes: list[dict[str, Any]]) -> bool:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("next_node_id") or node.get("prev_node_id"):
            return True
    return False


def strip_transition_nodes(nodes: list[dict[str, Any]]) -> None:
    had_transitions = any(
        isinstance(node, dict) and str(node.get("type", "")).strip().lower() == "transition"
        for node in nodes
    )
    kept = [
        node
        for node in nodes
        if isinstance(node, dict) and str(node.get("type", "")).strip().lower() != "transition"
    ]
    nodes[:] = kept
    if had_transitions or not has_explicit_node_links(nodes):
        link_node_chain(nodes)
    layout_nodes_linear(nodes)


def remove_orphan_catalog_points(
    points: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    safe_route_ids: list[str],
) -> None:
    referenced = {
        str(node.get("point_id", "")).strip()
        for node in nodes
        if isinstance(node, dict) and str(node.get("point_id", "")).strip()
    }
    safe_ids = {str(point_id).strip() for point_id in safe_route_ids if str(point_id).strip()}
    points[:] = [
        point
        for point in points
        if isinstance(point, dict)
        and (
            str(point.get("id", "")).strip() in referenced
            or str(point.get("id", "")).strip() in safe_ids
        )
    ]


def link_node_chain(nodes: list[dict[str, Any]]) -> None:
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        if index == 0:
            node.pop("prev_node_id", None)
        else:
            node["prev_node_id"] = str(nodes[index - 1].get("id", ""))

        if index == len(nodes) - 1:
            node.pop("next_node_id", None)
        else:
            node["next_node_id"] = str(nodes[index + 1].get("id", ""))


def layout_nodes_linear(nodes: list[dict[str, Any]], *, start_x: float = 40.0, start_y: float = 40.0) -> None:
    x_step = 220.0
    y_step = 120.0
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        if node.get("x") is None:
            node["x"] = start_x + (index % 4) * x_step
        if node.get("y") is None:
            node["y"] = start_y + (index // 4) * y_step


def ordered_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not nodes:
        return []

    by_id = {str(node.get("id", "")): node for node in nodes if isinstance(node, dict) and node.get("id")}

    start: dict[str, Any] | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("type", "")).strip().lower() == "home":
            start = node
            break

    if start is None:
        return [node for node in nodes if isinstance(node, dict)]

    ordered: list[dict[str, Any]] = []
    current: dict[str, Any] | None = start
    visited: set[str] = set()

    while current is not None:
        node_id = str(current.get("id", ""))
        if not node_id or node_id in visited:
            break
        visited.add(node_id)
        ordered.append(current)
        next_id = current.get("next_node_id")
        if not next_id:
            break
        current = by_id.get(str(next_id))

    if len(ordered) < len(nodes):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", ""))
            if node_id not in visited:
                ordered.append(node)

    return ordered
