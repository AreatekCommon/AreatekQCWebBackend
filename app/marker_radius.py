from __future__ import annotations

from collections.abc import Iterable

WORK_RANGE_LARGE = 1

MARKER_RADIUS_1MM = 1
MARKER_RADIUS_2MM = 2
MARKER_RADIUS_4MM = 4

LARGE_RANGE_ALLOWED_MASK = MARKER_RADIUS_2MM | MARKER_RADIUS_4MM
SMALL_RANGE_ALLOWED_MASK = MARKER_RADIUS_1MM | MARKER_RADIUS_2MM | MARKER_RADIUS_4MM

DEFAULT_MARKER_RADIUS = MARKER_RADIUS_4MM

ALL_MM_SIZES = (MARKER_RADIUS_1MM, MARKER_RADIUS_2MM, MARKER_RADIUS_4MM)


def allowed_mask(work_range: int) -> int:
    if work_range == WORK_RANGE_LARGE:
        return LARGE_RANGE_ALLOWED_MASK
    return SMALL_RANGE_ALLOWED_MASK


def encode_mm_sizes(sizes: Iterable[int]) -> int:
    value = 0
    for size in sizes:
        value |= size
    return value


def selected_mm_sizes(value: int) -> list[int]:
    return [mm for mm in ALL_MM_SIZES if value & mm]


def normalize_marker_radius(work_range: int, value: int) -> int:
    mask = allowed_mask(work_range)
    masked = value & mask
    if masked == 0:
        return DEFAULT_MARKER_RADIUS if DEFAULT_MARKER_RADIUS & mask else mask
    return masked


def is_valid_marker_radius(work_range: int, value: int) -> bool:
    if value == 0:
        return False
    mask = allowed_mask(work_range)
    return (value & ~mask) == 0
