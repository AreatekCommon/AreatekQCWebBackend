from __future__ import annotations

from dataclasses import dataclass

from app.exposure_migration import (
    MARKER_EXP_MAX,
    MARKER_EXP_MIN,
    POINT_CLOUD_EXP_MAX,
    POINT_CLOUD_EXP_MIN,
    CustomizedSlots,
    ExposureMode,
    infer_exposure_mode_from_legacy,
)
from app.models.scanner_settings import ScannerExposureSettings


@dataclass(frozen=True)
class PointExposureValues:
    val1: int | None = None
    val2: int | None = None
    val3: int | None = None
    marker_exp: int | None = None


@dataclass(frozen=True)
class WireExposurePayload:
    exp_type: int
    marker_exp: int
    val1: int
    val2: int
    val3: int


def active_point_cloud_slots(
    mode: ExposureMode,
    customized_slots: CustomizedSlots,
) -> frozenset[int]:
    if mode == "auto":
        return frozenset()
    if mode == "first":
        return frozenset({1})
    if mode == "second":
        return frozenset({2})
    if mode == "third":
        return frozenset({3})
    if customized_slots == "first":
        return frozenset({1})
    if customized_slots == "first_second":
        return frozenset({1, 2})
    return frozenset({1, 2, 3})


def is_marker_editable(mode: ExposureMode) -> bool:
    return mode != "auto"


def is_point_cloud_slot_editable(
    mode: ExposureMode,
    customized_slots: CustomizedSlots,
    slot: int,
) -> bool:
    return slot in active_point_cloud_slots(mode, customized_slots)


def encode_exposure_wire(settings: ScannerExposureSettings) -> WireExposurePayload:
    if settings.mode == "auto":
        return WireExposurePayload(
            exp_type=1,
            marker_exp=1,
            val1=1,
            val2=1,
            val3=1,
        )

    active = active_point_cloud_slots(settings.mode, settings.customized_slots)
    return WireExposurePayload(
        exp_type=0,
        marker_exp=settings.marker_exp,
        val1=settings.val1 if 1 in active else 1,
        val2=settings.val2 if 2 in active else 1,
        val3=settings.val3 if 3 in active else 1,
    )


def build_point_scan_exposure_commands(
    global_settings: ScannerExposureSettings,
    *,
    per_point_exposure: bool,
    per_point_marker_exposure: bool,
    point_vals: PointExposureValues | None,
) -> list[tuple[int, WireExposurePayload]]:
    if global_settings.mode == "auto":
        return []

    if point_vals is None:
        return []

    active = active_point_cloud_slots(global_settings.mode, global_settings.customized_slots)
    commands: list[tuple[int, WireExposurePayload]] = []

    if per_point_marker_exposure and point_vals.marker_exp is not None:
        commands.append(
            (
                1,
                WireExposurePayload(
                    exp_type=0,
                    marker_exp=point_vals.marker_exp,
                    val1=1,
                    val2=1,
                    val3=1,
                ),
            )
        )

    if per_point_exposure:
        global_values = {
            1: global_settings.val1,
            2: global_settings.val2,
            3: global_settings.val3,
        }
        point_values = {
            1: point_vals.val1,
            2: point_vals.val2,
            3: point_vals.val3,
        }

        commands.append(
            (
                0,
                WireExposurePayload(
                    exp_type=0,
                    marker_exp=global_settings.marker_exp,
                    val1=point_values[1] if 1 in active and point_values[1] is not None else (global_values[1] if 1 in active else 1),
                    val2=point_values[2] if 2 in active and point_values[2] is not None else (global_values[2] if 2 in active else 1),
                    val3=point_values[3] if 3 in active and point_values[3] is not None else (global_values[3] if 3 in active else 1),
                ),
            )
        )

    return commands


def exposure_sdk_commands(
    wire: WireExposurePayload,
    *,
    mode: ExposureMode,
) -> list[tuple[int, WireExposurePayload]]:
    if mode == "auto":
        return [(0, wire)]
    return [(1, wire), (0, wire)]


def validate_exposure_settings(settings: ScannerExposureSettings) -> str | None:
    if not MARKER_EXP_MIN <= settings.marker_exp <= MARKER_EXP_MAX:
        return "invalid_marker_exposure_range"
    for value in (settings.val1, settings.val2, settings.val3):
        if not POINT_CLOUD_EXP_MIN <= value <= POINT_CLOUD_EXP_MAX:
            return "invalid_point_cloud_exposure_range"
    return None


__all__ = [
    "PointExposureValues",
    "WireExposurePayload",
    "active_point_cloud_slots",
    "build_point_scan_exposure_commands",
    "encode_exposure_wire",
    "exposure_sdk_commands",
    "infer_exposure_mode_from_legacy",
    "is_marker_editable",
    "is_point_cloud_slot_editable",
    "validate_exposure_settings",
]
