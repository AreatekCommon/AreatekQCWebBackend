from __future__ import annotations

from collections import deque
from typing import Any

from app.eki.path_parser import JOINT_KEYS, merge_node_point, resolve_jog_target
from app.eki.turntable_units import quantize_turntable_angle
from app.trajectory.path_nodes import ordered_nodes
from app.trajectory.position_ids import first_point_index_for_id

DEFAULT_MATCH_THRESHOLD_DEG = 1.0
DEFAULT_MOTION = {"speed": 50.0, "acceleration": 50.0}
DEFAULT_TURNTABLE = {"angle": 0.0, "speed": 50.0, "acceleration": 50.0}
SCAN_POSITION_TYPES = frozenset({"basic_scan", "advanced_scan"})


def normalize_id_safe_routes(
    ids: list[str],
    matrix: list[Any] | None = None,
) -> list[list[bool]]:
    count = len(ids)
    if count < 0:
        raise ValueError("Id count must be non-negative")

    if count == 0:
        return []

    if matrix is None and count <= 2:
        return [[True for _ in range(count)] for _ in range(count)]

    routes: list[list[bool]] = []
    for row_index in range(count):
        row: list[bool] = []
        for column_index in range(count):
            if row_index == column_index:
                row.append(True)
                continue

            value = False
            if matrix is not None and row_index < len(matrix):
                source_row = matrix[row_index]
                if isinstance(source_row, list) and column_index < len(source_row):
                    value = bool(source_row[column_index])
            row.append(value)
        routes.append(row)

    for row_index in range(count):
        for column_index in range(row_index + 1, count):
            left = routes[row_index][column_index]
            right = routes[column_index][row_index]
            merged = left or right
            routes[row_index][column_index] = merged
            routes[column_index][row_index] = merged

    return routes


def position_joint_axes(position: dict[str, Any]) -> list[float]:
    raw_axes = position.get("axes") or {}
    if not isinstance(raw_axes, dict):
        raise ValueError("Position 'axes' must be an object")
    missing = [key for key in JOINT_KEYS if key not in raw_axes]
    if missing:
        raise ValueError(f"Position axes missing required joints: {', '.join(missing)}")
    return [float(raw_axes[key]) for key in JOINT_KEYS]


def axes_match(
    current_axes: list[float],
    target_axes: list[float],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD_DEG,
) -> bool:
    if len(current_axes) != len(target_axes):
        return False
    return all(abs(current - target) <= threshold for current, target in zip(current_axes, target_axes))


def match_current_ids(
    current_axes: list[float],
    points: list[dict[str, Any]],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD_DEG,
) -> list[str]:
    matched_ids: list[str] = []
    seen: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            target_axes = position_joint_axes(point)
        except ValueError:
            continue
        if not axes_match(current_axes, target_axes, threshold=threshold):
            continue
        point_id = str(point.get("id", ""))
        if not point_id or point_id in seen:
            continue
        seen.add(point_id)
        matched_ids.append(point_id)
    return matched_ids


def find_id_route(
    safe_routes: list[list[bool]],
    safe_route_ids: list[str],
    start_ids: list[str],
    goal_id: str,
) -> list[str]:
    if goal_id not in safe_route_ids:
        raise ValueError(f"Goal id not found in safe routes: {goal_id}")

    if not start_ids:
        raise RuntimeError("Robot is not at a known position")

    id_to_index = {position_id: index for index, position_id in enumerate(safe_route_ids)}
    goal_index = id_to_index[goal_id]
    start_indices = [id_to_index[position_id] for position_id in start_ids if position_id in id_to_index]

    if not start_indices:
        raise RuntimeError("Robot is not at a known position")

    if goal_index in start_indices:
        return [goal_id]

    visited: set[int] = set()
    queue: deque[list[int]] = deque()

    for start_index in start_indices:
        if start_index in visited:
            continue
        visited.add(start_index)
        queue.append([start_index])

    while queue:
        path = queue.popleft()
        current = path[-1]
        if current == goal_index:
            return [safe_route_ids[index] for index in path]

        for neighbor in range(len(safe_routes)):
            if neighbor in visited:
                continue
            if not safe_routes[current][neighbor]:
                continue
            visited.add(neighbor)
            queue.append([*path, neighbor])

    raise RuntimeError("No safe route to target position")


def has_direct_safe_route(
    safe_route_ids: list[str],
    safe_routes: list[list[bool]],
    from_id: str,
    to_id: str,
) -> bool:
    if from_id == to_id:
        return True
    if not safe_route_ids or not safe_routes:
        return False

    id_to_index = {position_id: index for index, position_id in enumerate(safe_route_ids)}
    if from_id not in id_to_index or to_id not in id_to_index:
        return False

    row = id_to_index[from_id]
    col = id_to_index[to_id]
    if row >= len(safe_routes) or col >= len(safe_routes[row]):
        return False
    return bool(safe_routes[row][col])


def exit_turntable_angle_from_merged_item(item: dict[str, Any]) -> float:
    position_type = str(item.get("type", "")).strip()
    turntable = item.get("turntable") or {}
    if not isinstance(turntable, dict):
        return 0.0

    if position_type in {"home", "transition", "basic_scan", "end"}:
        return quantize_turntable_angle(float(turntable.get("angle", 0.0)))

    if position_type == "advanced_scan":
        scan_mode = str(turntable.get("advanced_scan_mode", "range")).strip().lower()
        start_angle = float(turntable.get("start_angle", 0.0))
        if scan_mode == "step":
            step_angle = float(turntable.get("step_angle", 90.0))
            scan_count = int(turntable.get("scan_count", 1))
            if scan_count <= 1:
                return quantize_turntable_angle(start_angle)
            return quantize_turntable_angle(start_angle + (scan_count - 1) * step_angle)

        end_angle = float(turntable.get("end_angle", 360.0))
        return quantize_turntable_angle(end_angle)

    return 0.0


def entry_turntable_angle_from_merged_item(item: dict[str, Any]) -> float:
    position_type = str(item.get("type", "")).strip()
    turntable = item.get("turntable") or {}
    if not isinstance(turntable, dict):
        return 0.0

    if position_type == "advanced_scan":
        return quantize_turntable_angle(
            float(turntable.get("start_angle", turntable.get("angle", 0.0)))
        )

    return quantize_turntable_angle(float(turntable.get("angle", 0.0)))


def interpolate_turntable_angles(start: float, end: float, count: int) -> list[float]:
    if count <= 0:
        return []
    return [
        quantize_turntable_angle(start - (start - end) / (count + 1) * index)
        for index in range(1, count + 1)
    ]


def _make_transition_item(point: dict[str, Any], exit_angle: float) -> dict[str, Any]:
    name = str(point.get("name") or point.get("comment") or point.get("id", "")).strip()
    return {
        "id": str(point.get("id", "")),
        "name": name,
        "axes": point.get("axes") or {},
        "type": "transition",
        "turntable": {
            **DEFAULT_TURNTABLE,
            "angle": quantize_turntable_angle(exit_angle),
        },
        "motion": dict(DEFAULT_MOTION),
    }


def build_execution_items_with_transitions(
    point_by_id: dict[str, dict[str, Any]],
    nodes: list[dict[str, Any]],
    safe_route_ids: list[str],
    safe_routes: list[list[bool]],
) -> list[dict[str, Any]]:
    if not nodes:
        return []

    merged_items: list[dict[str, Any]] = []
    last_exit_angle = 0.0

    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"Node #{node_index} must be an object")

        point_id = str(node.get("point_id", "")).strip()
        if not point_id or point_id not in point_by_id:
            raise ValueError(f"Node #{node_index} references unknown point_id '{point_id}'")

        if node_index > 0:
            prev_node = nodes[node_index - 1]
            from_id = str(prev_node.get("point_id", "")).strip()
            to_id = point_id
            left_node_id = str(prev_node.get("id", "")).strip()
            right_node_id = str(node.get("id", "")).strip()

            if not has_direct_safe_route(safe_route_ids, safe_routes, from_id, to_id):
                try:
                    id_route = find_id_route(safe_routes, safe_route_ids, [from_id], to_id)
                except RuntimeError as exc:
                    raise ValueError(
                        f"No safe route from point '{from_id}' to '{to_id}' "
                        f"(nodes {left_node_id} → {right_node_id})"
                    ) from exc

                intermediate_ids = id_route[1:-1]
                if intermediate_ids:
                    destination_merged = merge_node_point(node, point_by_id[point_id])
                    end_angle = entry_turntable_angle_from_merged_item(destination_merged)
                    transition_angles = interpolate_turntable_angles(
                        last_exit_angle,
                        end_angle,
                        len(intermediate_ids),
                    )
                    for intermediate_id, transition_angle in zip(
                        intermediate_ids,
                        transition_angles,
                        strict=True,
                    ):
                        intermediate_point = point_by_id.get(intermediate_id)
                        if intermediate_point is None:
                            raise ValueError(
                                f"Route references unknown point_id '{intermediate_id}'"
                            )
                        merged_items.append(
                            _make_transition_item(intermediate_point, transition_angle)
                        )

        merged = merge_node_point(node, point_by_id[point_id])
        merged_items.append(merged)
        last_exit_angle = exit_turntable_angle_from_merged_item(merged)

    return merged_items


def build_travel_plan_by_id(
    points: list[dict[str, Any]],
    id_route: list[str],
    *,
    nodes: list[dict[str, Any]] | None = None,
    goal_point_id: str | None = None,
    goal_node_id: str | None = None,
) -> list[tuple[str, list[float], float]]:
    node_by_point_id: dict[str, dict[str, Any]] = {}
    node_by_id: dict[str, dict[str, Any]] = {}
    if nodes:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id:
                node_by_id[node_id] = node
            point_id = str(node.get("point_id", "")).strip()
            if point_id:
                node_by_point_id[point_id] = node

    resolved_goal_point_id = goal_point_id
    if goal_node_id and goal_node_id in node_by_id:
        resolved_goal_point_id = (
            str(node_by_id[goal_node_id].get("point_id", "")).strip() or goal_point_id
        )

    def merged_for_position(position_id: str) -> dict[str, Any]:
        index = first_point_index_for_id(points, position_id)
        point = points[index]
        if not isinstance(point, dict):
            raise RuntimeError(f"Point id={position_id} must be an object")

        node = node_by_point_id.get(position_id)
        if (
            goal_node_id
            and resolved_goal_point_id
            and position_id == resolved_goal_point_id
            and goal_node_id in node_by_id
        ):
            node = node_by_id[goal_node_id]
        if node is not None:
            return merge_node_point(node, point)

        merged = dict(point)
        merged["type"] = "transition"
        merged["turntable"] = {"angle": 0.0}
        return merged

    interpolated_angles: list[float] = []
    if len(id_route) > 2:
        start_merged = merged_for_position(id_route[0])
        end_merged = merged_for_position(id_route[-1])
        interpolated_angles = interpolate_turntable_angles(
            exit_turntable_angle_from_merged_item(start_merged),
            entry_turntable_angle_from_merged_item(end_merged),
            len(id_route) - 2,
        )

    plan: list[tuple[str, list[float], float]] = []
    for route_index, position_id in enumerate(id_route):
        merged = merged_for_position(position_id)
        axes, turntable_angle = resolve_jog_target(merged)
        if interpolated_angles and 0 < route_index < len(id_route) - 1:
            turntable_angle = interpolated_angles[route_index - 1]
        plan.append((position_id, axes, turntable_angle))
    return plan


def find_home_point_id(nodes: list[dict[str, Any]]) -> str:
    for node in ordered_nodes(nodes):
        if not isinstance(node, dict):
            continue
        if str(node.get("type", "")).strip().lower() != "home":
            continue
        point_id = str(node.get("point_id", "")).strip()
        if point_id:
            return point_id
    raise ValueError("Path has no home node")


def find_first_scan_node(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    for node in ordered_nodes(nodes):
        if not isinstance(node, dict):
            continue
        if str(node.get("type", "")).strip().lower() not in SCAN_POSITION_TYPES:
            continue
        return node
    raise ValueError("Path has no scan node")


def find_first_scan_point_id(nodes: list[dict[str, Any]]) -> str:
    node = find_first_scan_node(nodes)
    point_id = str(node.get("point_id", "")).strip()
    if not point_id:
        raise ValueError("Path has no scan node")
    return point_id


def find_home_position_id(nodes: list[dict[str, Any]]) -> str:
    return find_home_point_id(nodes)


def find_first_scan_position_id(nodes: list[dict[str, Any]]) -> str:
    return find_first_scan_point_id(nodes)


def read_current_axes_from_snapshot(snapshot: dict[str, Any]) -> list[float]:
    current_axes: list[float] = []
    for axis_index in range(1, 7):
        value = snapshot.get(f"a{axis_index}")
        if value is None:
            raise RuntimeError("Robot axis position is not available")
        current_axes.append(float(value))
    return current_axes


def plan_id_route_to_goal(
    current_axes: list[float],
    points: list[dict[str, Any]],
    safe_routes: list[list[bool]],
    safe_route_ids: list[str],
    goal_id: str,
    *,
    no_route_message: str = "No safe route to target position",
) -> tuple[list[str], list[str]]:
    start_ids = match_current_ids(current_axes, points)
    if not start_ids:
        raise RuntimeError("Robot is not at a known position")

    try:
        id_route = find_id_route(safe_routes, safe_route_ids, start_ids, goal_id)
    except RuntimeError as exc:
        if "No safe route" in str(exc):
            raise RuntimeError(no_route_message) from exc
        raise

    return start_ids, id_route
