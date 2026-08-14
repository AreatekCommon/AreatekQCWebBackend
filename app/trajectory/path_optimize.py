from __future__ import annotations

from typing import Any

from app.eki.turntable_units import quantize_turntable_angle


def _angular_distance(a: float, b: float) -> float:
    qa = quantize_turntable_angle(a)
    qb = quantize_turntable_angle(b)
    diff = abs(qa - qb) % 360.0
    if diff > 180.0:
        diff = 360.0 - diff
    return diff


def _should_swap_advanced_scan(
    last_scan_exit_angle: float,
    start_angle: float,
    end_angle: float,
) -> bool:
    dist_to_start = _angular_distance(last_scan_exit_angle, start_angle)
    dist_to_end = _angular_distance(last_scan_exit_angle, end_angle)

    if dist_to_end < dist_to_start:
        return True

    return (
        dist_to_end == dist_to_start
        and dist_to_start == 0.0
        and start_angle != last_scan_exit_angle
    )


def _node_turntable(node: dict[str, Any]) -> dict[str, Any]:
    turntable = node.get("turntable")
    if not isinstance(turntable, dict):
        turntable = {}
        node["turntable"] = turntable
    return turntable


def optimize_path_positions(positions: list[dict[str, Any]]) -> None:
    last_scan_exit_angle: float | None = None

    for position in positions:
        if not isinstance(position, dict):
            continue

        position_type = str(position.get("type", "")).strip()
        turntable = position.get("turntable")
        if not isinstance(turntable, dict):
            turntable = {}
            position["turntable"] = turntable

        if position_type == "basic_scan":
            angle = quantize_turntable_angle(float(turntable.get("angle", 0.0)))
            turntable["angle"] = angle
            last_scan_exit_angle = angle
            continue

        if position_type == "advanced_scan":
            scan_mode = str(turntable.get("advanced_scan_mode", "range")).strip().lower()
            start_angle = float(turntable.get("start_angle", 0.0))

            if scan_mode == "step":
                step_angle = float(turntable.get("step_angle", 90.0))
                scan_count = int(turntable.get("scan_count", 1))
                start_angle = quantize_turntable_angle(start_angle)
                turntable["start_angle"] = start_angle
                if scan_count <= 1:
                    last_scan_exit_angle = start_angle
                else:
                    last_scan_exit_angle = quantize_turntable_angle(
                        start_angle + (scan_count - 1) * step_angle
                    )
                continue

            end_angle = float(turntable.get("end_angle", 360.0))

            if last_scan_exit_angle is not None:
                if _should_swap_advanced_scan(last_scan_exit_angle, start_angle, end_angle):
                    start_angle, end_angle = end_angle, start_angle

            start_angle = quantize_turntable_angle(start_angle)
            end_angle = quantize_turntable_angle(end_angle)
            turntable["start_angle"] = start_angle
            turntable["end_angle"] = end_angle
            last_scan_exit_angle = end_angle
            continue


def optimize_path_nodes(nodes: list[dict[str, Any]]) -> None:
    last_scan_exit_angle: float | None = None

    for node in nodes:
        if not isinstance(node, dict):
            continue

        position_type = str(node.get("type", "")).strip()
        turntable = _node_turntable(node)

        if position_type == "basic_scan":
            angle = quantize_turntable_angle(float(turntable.get("angle", 0.0)))
            turntable["angle"] = angle
            last_scan_exit_angle = angle
            continue

        if position_type == "advanced_scan":
            scan_mode = str(turntable.get("advanced_scan_mode", "range")).strip().lower()
            start_angle = float(turntable.get("start_angle", 0.0))

            if scan_mode == "step":
                step_angle = float(turntable.get("step_angle", 90.0))
                scan_count = int(turntable.get("scan_count", 1))
                start_angle = quantize_turntable_angle(start_angle)
                turntable["start_angle"] = start_angle
                if scan_count <= 1:
                    last_scan_exit_angle = start_angle
                else:
                    last_scan_exit_angle = quantize_turntable_angle(
                        start_angle + (scan_count - 1) * step_angle
                    )
                continue

            end_angle = float(turntable.get("end_angle", 360.0))

            if last_scan_exit_angle is not None:
                if _should_swap_advanced_scan(last_scan_exit_angle, start_angle, end_angle):
                    start_angle, end_angle = end_angle, start_angle

            start_angle = quantize_turntable_angle(start_angle)
            end_angle = quantize_turntable_angle(end_angle)
            turntable["start_angle"] = start_angle
            turntable["end_angle"] = end_angle
            last_scan_exit_angle = end_angle
            continue

