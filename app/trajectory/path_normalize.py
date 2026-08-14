from __future__ import annotations

import copy
from typing import Any

from app.trajectory.path_nodes import (
    ensure_node_defaults,
    has_explicit_node_links,
    layout_nodes_linear,
    link_node_chain,
    migrate_legacy_positions,
    ordered_nodes,
    split_settings_from_points,
    strip_points_catalog,
    strip_transition_nodes,
)
from app.trajectory.position_ids import (
    catalog_order_point_ids,
    migrate_position_matrix_to_id_matrix,
    remap_id_matrix,
)
from app.trajectory.routing import normalize_id_safe_routes


def ensure_neighbor_safe_routes(
    nodes: list[dict[str, Any]],
    safe_route_ids: list[str],
    safe_routes: list[list[bool]],
) -> None:
    if not nodes or not safe_route_ids:
        return

    id_to_index = {position_id: index for index, position_id in enumerate(safe_route_ids)}
    chain = ordered_nodes(nodes)

    for left, right in zip(chain, chain[1:]):
        left_id = str(left.get("point_id", ""))
        right_id = str(right.get("point_id", ""))
        if not left_id or not right_id or left_id == right_id:
            continue
        if left_id not in id_to_index or right_id not in id_to_index:
            continue

        row = id_to_index[left_id]
        col = id_to_index[right_id]
        if not safe_routes[row][col]:
            safe_routes[row][col] = True
            safe_routes[col][row] = True


def _resolve_id_safe_routes(
    points: list[dict[str, Any]],
    data: dict[str, Any],
    *,
    legacy_positions: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[list[bool]]]:
    ids = catalog_order_point_ids(points)
    raw_ids = data.get("safe_route_ids")
    raw_matrix = data.get("safe_routes")

    if (
        isinstance(raw_ids, list)
        and isinstance(raw_matrix, list)
        and len(raw_ids) == len(raw_matrix) == len(ids)
        and set(str(item) for item in raw_ids) == set(ids)
    ):
        id_to_old_index = {str(position_id): index for index, position_id in enumerate(raw_ids)}
        reordered = [
            [
                bool(raw_matrix[id_to_old_index[ids[row_index]]][id_to_old_index[ids[column_index]]])
                if row_index != column_index
                else True
                for column_index in range(len(ids))
            ]
            for row_index in range(len(ids))
        ]
        return ids, normalize_id_safe_routes(ids, reordered)

    if isinstance(raw_ids, list) and isinstance(raw_matrix, list) and len(raw_ids) == len(raw_matrix):
        remapped_ids, remapped_matrix = remap_id_matrix(raw_ids, raw_matrix, ids)
        return remapped_ids, normalize_id_safe_routes(remapped_ids, remapped_matrix)

    if legacy_positions and isinstance(raw_matrix, list) and len(raw_matrix) == len(legacy_positions):
        migrated_ids, migrated_matrix = migrate_position_matrix_to_id_matrix(legacy_positions, raw_matrix)
        return migrated_ids, normalize_id_safe_routes(migrated_ids, migrated_matrix)

    return ids, normalize_id_safe_routes(ids, None)


def _ensure_points_nodes(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]] | None]:
    legacy_positions: list[dict[str, Any]] | None = None

    raw_nodes = data.get("nodes")
    raw_points = data.get("points")

    if (
        isinstance(raw_nodes, list)
        and isinstance(raw_points, list)
        and len(raw_points) > 0
        and len(raw_nodes) > 0
    ):
        return copy.deepcopy(raw_points), copy.deepcopy(raw_nodes), None

    raw_positions = data.get("positions")
    if isinstance(raw_positions, list) and len(raw_positions) > 0:
        legacy_positions = copy.deepcopy(raw_positions)
        points, nodes = migrate_legacy_positions(raw_positions)
        return points, nodes, legacy_positions

    if isinstance(raw_points, list):
        return copy.deepcopy(raw_points), copy.deepcopy(raw_nodes if isinstance(raw_nodes, list) else []), None

    raise ValueError("Path document must contain 'points' and 'nodes' arrays")


def normalize_path_document(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Path document must be a JSON object")

    points, nodes, legacy_positions = _ensure_points_nodes(data)

    split_settings_from_points(points, nodes)
    strip_points_catalog(points)
    ensure_node_defaults(nodes)
    strip_transition_nodes(nodes)

    ordered = ordered_nodes(nodes)
    if not has_explicit_node_links(nodes):
        link_node_chain(ordered)
    layout_nodes_linear(ordered)
    nodes[:] = ordered

    safe_route_ids, safe_routes = _resolve_id_safe_routes(points, data, legacy_positions=legacy_positions)
    raw_matrix = data.get("safe_routes")
    has_explicit_matrix = isinstance(raw_matrix, list) and len(raw_matrix) > 0
    if not has_explicit_matrix:
        ensure_neighbor_safe_routes(nodes, safe_route_ids, safe_routes)

    uniform_count = data.get("uniform_advanced_scan_count")
    return {
        "points": points,
        "nodes": nodes,
        "safe_route_ids": safe_route_ids,
        "safe_routes": safe_routes,
        "per_point_exposure": bool(data.get("per_point_exposure", False)),
        "per_point_marker_exposure": bool(data.get("per_point_marker_exposure", False)),
        "uniform_advanced_scan_rotations": bool(data.get("uniform_advanced_scan_rotations", False)),
        "uniform_advanced_scan_count": int(uniform_count) if uniform_count is not None else None,
    }
