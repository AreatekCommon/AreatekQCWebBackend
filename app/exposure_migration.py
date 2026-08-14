from __future__ import annotations

from typing import Any, Literal

ExposureMode = Literal["auto", "first", "second", "third", "customized"]
CustomizedSlots = Literal["first", "first_second", "all"]

MARKER_EXP_MIN = 1
MARKER_EXP_MAX = 25
POINT_CLOUD_EXP_MIN = 1
POINT_CLOUD_EXP_MAX = 60

LEGACY_DEVICE_EXPOSURE_KEYS = (
    "exp_type",
    "exp_obj",
    "marker_exp",
    "val1",
    "val2",
    "val3",
)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def infer_exposure_mode_from_legacy(
    exp_type: int,
    val1: int,
    val2: int,
    val3: int,
) -> tuple[ExposureMode, CustomizedSlots]:
    if exp_type == 1:
        return "auto", "first"

    active = [index for index, value in enumerate((val1, val2, val3), start=1) if value > 1]
    if len(active) == 0:
        return "first", "first"
    if len(active) == 1:
        return {1: "first", 2: "second", 3: "third"}[active[0]], "first"
    if active == [1, 2]:
        return "customized", "first_second"
    return "customized", "all"


def migrate_legacy_exposure_settings(
    *,
    exp_type: int = 1,
    marker_exp: int = 8,
    val1: int = 22,
    val2: int = 1,
    val3: int = 1,
) -> dict[str, Any]:
    mode, customized_slots = infer_exposure_mode_from_legacy(exp_type, val1, val2, val3)
    return {
        "mode": mode,
        "customized_slots": customized_slots,
        "marker_exp": _clamp(marker_exp, MARKER_EXP_MIN, MARKER_EXP_MAX),
        "val1": _clamp(val1, POINT_CLOUD_EXP_MIN, POINT_CLOUD_EXP_MAX),
        "val2": _clamp(val2, POINT_CLOUD_EXP_MIN, POINT_CLOUD_EXP_MAX),
        "val3": _clamp(val3, POINT_CLOUD_EXP_MIN, POINT_CLOUD_EXP_MAX),
    }


def strip_legacy_device_exposure(device: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(device)
    for key in LEGACY_DEVICE_EXPOSURE_KEYS:
        cleaned.pop(key, None)
    return cleaned
