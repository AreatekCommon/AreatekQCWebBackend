from __future__ import annotations

from typing import Any

JOINT_KEYS = ("J1", "J2", "J3", "J4", "J5", "J6")


def axes_key(axes: dict[str, Any]) -> tuple[float, ...]:
    return tuple(round(float(axes[key]), 2) for key in JOINT_KEYS)


def _parse_id(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _next_free_id(used_ids: set[str]) -> str:
    candidate = 0
    while str(candidate) in used_ids:
        candidate += 1
    return str(candidate)


def normalize_point_ids(points: list[dict[str, Any]]) -> dict[str, str]:
    """Normalize point ids by axes. Returns old_id -> canonical_id mapping."""
    id_map: dict[str, str] = {}

    groups: dict[tuple[float, ...], list[int]] = {}
    for index, point in enumerate(points):
        raw_axes = point.get("axes") or {}
        if not isinstance(raw_axes, dict):
            raw_axes = {}
        key = axes_key(raw_axes)
        groups.setdefault(key, []).append(index)

    group_entries: list[tuple[int, tuple[float, ...], list[int], str]] = []
    for key, indices in groups.items():
        numeric_ids = [_parse_id(points[index].get("id")) for index in indices]
        valid_ids = [value for value in numeric_ids if value is not None]
        if valid_ids:
            canonical = str(min(valid_ids))
        else:
            canonical = str(min(indices))
        group_entries.append((min(indices), key, indices, canonical))

    group_entries.sort(key=lambda item: item[0])

    assigned: dict[tuple[float, ...], str] = {}
    used_ids: set[str] = set()
    for _, key, _indices, canonical in group_entries:
        chosen = canonical
        if chosen in used_ids:
            chosen = _next_free_id(used_ids)
        assigned[key] = chosen
        used_ids.add(chosen)

    for key, indices in groups.items():
        point_id = assigned[key]
        for index in indices:
            old_id = str(points[index].get("id", ""))
            points[index]["id"] = point_id
            if old_id:
                id_map[old_id] = point_id
            id_map[point_id] = point_id

    return id_map


def normalize_position_ids(positions: list[dict[str, Any]]) -> None:
    groups: dict[tuple[float, ...], list[int]] = {}
    for index, position in enumerate(positions):
        raw_axes = position.get("axes") or {}
        if not isinstance(raw_axes, dict):
            raw_axes = {}
        key = axes_key(raw_axes)
        groups.setdefault(key, []).append(index)

    group_entries: list[tuple[int, tuple[float, ...], list[int], str]] = []
    for key, indices in groups.items():
        numeric_ids = [_parse_id(positions[index].get("id")) for index in indices]
        valid_ids = [value for value in numeric_ids if value is not None]
        if valid_ids:
            canonical = str(min(valid_ids))
        else:
            canonical = str(min(indices))
        group_entries.append((min(indices), key, indices, canonical))

    group_entries.sort(key=lambda item: item[0])

    assigned: dict[tuple[float, ...], str] = {}
    used_ids: set[str] = set()
    for _, key, _indices, canonical in group_entries:
        chosen = canonical
        if chosen in used_ids:
            chosen = _next_free_id(used_ids)
        assigned[key] = chosen
        used_ids.add(chosen)

    for key, indices in groups.items():
        position_id = assigned[key]
        for index in indices:
            positions[index]["id"] = position_id


def _sort_id_key(position_id: str) -> tuple[int, str | int]:
    parsed = _parse_id(position_id)
    if parsed is not None:
        return (0, parsed)
    return (1, position_id)


def unique_sorted_ids(positions: list[dict[str, Any]]) -> list[str]:
    unique = {str(position.get("id", "")) for position in positions if isinstance(position, dict)}
    unique.discard("")
    return sorted(unique, key=_sort_id_key)


def catalog_order_point_ids(points: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        point_id = str(point.get("id", "")).strip()
        if not point_id or point_id in seen:
            continue
        seen.add(point_id)
        ids.append(point_id)
    return ids


def unique_sorted_point_ids(points: list[dict[str, Any]]) -> list[str]:
    return unique_sorted_ids(points)


def first_point_index_for_id(points: list[dict[str, Any]], point_id: str) -> int:
    return first_index_for_id(points, point_id)


def first_index_for_id(positions: list[dict[str, Any]], position_id: str) -> int:
    for index, position in enumerate(positions):
        if not isinstance(position, dict):
            continue
        if str(position.get("id", "")) == position_id:
            return index
    raise ValueError(f"Position id not found: {position_id}")


def migrate_position_matrix_to_id_matrix(
    positions: list[dict[str, Any]],
    old_matrix: list[Any] | None,
) -> tuple[list[str], list[list[bool]]]:
    ids = unique_sorted_ids(positions)
    if not ids:
        return [], []

    id_to_index = {position_id: index for index, position_id in enumerate(ids)}
    size = len(ids)
    merged = [[row_index == column_index for column_index in range(size)] for row_index in range(size)]

    if not old_matrix:
        return ids, merged

    for row_index, position in enumerate(positions):
        if row_index >= len(old_matrix):
            break
        if not isinstance(position, dict):
            continue
        from_id = str(position.get("id", ""))
        if from_id not in id_to_index:
            continue
        from_matrix_index = id_to_index[from_id]
        source_row = old_matrix[row_index]
        if not isinstance(source_row, list):
            continue

        for column_index, other in enumerate(positions):
            if column_index >= len(source_row):
                break
            if not isinstance(other, dict):
                continue
            to_id = str(other.get("id", ""))
            if to_id not in id_to_index:
                continue
            if bool(source_row[column_index]):
                to_matrix_index = id_to_index[to_id]
                merged[from_matrix_index][to_matrix_index] = True
                merged[to_matrix_index][from_matrix_index] = True

    return ids, merged


def remap_id_matrix(
    old_ids: list[Any],
    old_matrix: list[Any],
    new_ids: list[str],
) -> tuple[list[str], list[list[bool]]]:
    if not new_ids:
        return [], []

    new_index = {position_id: index for index, position_id in enumerate(new_ids)}
    size = len(new_ids)
    merged = [[row_index == column_index for column_index in range(size)] for row_index in range(size)]

    for row_index, raw_from_id in enumerate(old_ids):
        if row_index >= len(old_matrix):
            break
        from_id = str(raw_from_id)
        if from_id not in new_index:
            continue
        from_matrix_index = new_index[from_id]
        source_row = old_matrix[row_index]
        if not isinstance(source_row, list):
            continue

        for column_index, raw_to_id in enumerate(old_ids):
            if column_index >= len(source_row):
                break
            to_id = str(raw_to_id)
            if to_id not in new_index:
                continue
            if bool(source_row[column_index]):
                to_matrix_index = new_index[to_id]
                merged[from_matrix_index][to_matrix_index] = True
                merged[to_matrix_index][from_matrix_index] = True

    return new_ids, merged


def sync_comments_by_id(positions: list[dict[str, Any]]) -> None:
    comment_by_id: dict[str, str] = {}

    for position in positions:
        if not isinstance(position, dict):
            continue
        position_id = str(position.get("id", ""))
        comment = str(position.get("comment", "")).strip()
        if position_id not in comment_by_id:
            comment_by_id[position_id] = comment
        elif comment and not comment_by_id[position_id]:
            comment_by_id[position_id] = comment

    for position in positions:
        if not isinstance(position, dict):
            continue
        position_id = str(position.get("id", ""))
        position["comment"] = comment_by_id.get(position_id, "")

