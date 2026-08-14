from __future__ import annotations

from typing import Literal

from app.core.logger import get_logger

DEFAULT_COUNTS_PER_REV = 300000
INT32_MAX = 2_147_483_647

_logger = get_logger(__name__)


def angle_deg_to_counts(
    angle_deg: float,
    counts_per_rev: int = DEFAULT_COUNTS_PER_REV,
) -> int:
    counts = round(angle_deg / 360.0 * counts_per_rev)
    max_counts = min(counts_per_rev, INT32_MAX)
    if counts > max_counts:
        _logger.warning(
            "Turntable angle %.6f deg maps to %d counts; clamping to %d",
            angle_deg,
            counts,
            max_counts,
        )
        return max_counts
    if counts < 0:
        _logger.warning(
            "Turntable angle %.6f deg maps to %d counts; clamping to 0",
            angle_deg,
            counts,
        )
        return 0
    return counts


def counts_to_angle_deg(
    counts: int,
    counts_per_rev: int = DEFAULT_COUNTS_PER_REV,
) -> float:
    return counts / counts_per_rev * 360.0


def quantize_turntable_angle(
    angle_deg: float,
    counts_per_rev: int = DEFAULT_COUNTS_PER_REV,
) -> float:
    counts = angle_deg_to_counts(angle_deg, counts_per_rev)
    return counts_to_angle_deg(counts, counts_per_rev)


def turntable_angle_for_wire(
    angle_deg: float,
    counts_per_rev: int = DEFAULT_COUNTS_PER_REV,
) -> float:
    return quantize_turntable_angle(angle_deg, counts_per_rev)


TurntableWireFormat = Literal["integer", "decimal_2"]


def format_turntable_turn_for_xml(
    angle_deg: float,
    wire_format: TurntableWireFormat,
    counts_per_rev: int = DEFAULT_COUNTS_PER_REV,
) -> str:
    aligned = turntable_angle_for_wire(angle_deg, counts_per_rev)
    if wire_format == "integer":
        return str(int(round(aligned)))
    return f"{aligned:.2f}"


def turntable_wire_display_value(
    angle_deg: float,
    wire_format: TurntableWireFormat,
    counts_per_rev: int = DEFAULT_COUNTS_PER_REV,
) -> float:
    aligned = turntable_angle_for_wire(angle_deg, counts_per_rev)
    if wire_format == "integer":
        return float(int(round(aligned)))
    return round(aligned, 2)
