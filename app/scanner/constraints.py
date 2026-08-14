from __future__ import annotations

from app.exposure_wire import validate_exposure_settings
from app.marker_radius import is_valid_marker_radius, normalize_marker_radius
from app.models.scanner_settings import ScannerScanParams, ScannerSettings

ALIGN_MOD_GLOBAL_MARKER = 8
MARKERS_ONLY_SAVE_TYPE = "p3"


def is_markers_only_scan_mode(scan: ScannerScanParams) -> bool:
    return scan.scan_markers and not scan.scan_point_cloud


def normalize_scan_target(scan: ScannerScanParams) -> ScannerScanParams:
    updated = scan.model_copy(deep=True)

    if updated.scan_markers and updated.scan_point_cloud:
        updated.scan_point_cloud = True
        updated.scan_markers = False

    return updated


def normalize_scanner_settings(scanner: ScannerSettings) -> ScannerSettings:
    marker_radius = normalize_marker_radius(scanner.work_range, scanner.scan.marker_radius)
    scan = scanner.scan.model_copy(deep=True)
    scan.marker_radius = marker_radius
    scan = normalize_scan_target(scan)
    normalized = scanner.model_copy(deep=True, update={"scan": scan})

    if is_markers_only_scan_mode(normalized.scan):
        normalized = normalized.model_copy(
            update={
                "save_type": MARKERS_ONLY_SAVE_TYPE,
                "scan": normalized.scan.model_copy(update={"align_mod": ALIGN_MOD_GLOBAL_MARKER}),
            }
        )

    return normalized


def validate_scanner_constraints(scanner: ScannerSettings) -> str | None:
    if not is_valid_marker_radius(scanner.work_range, scanner.scan.marker_radius):
        return "invalid_marker_radius_for_work_range"

    if scanner.scan.scan_markers and scanner.scan.scan_point_cloud:
        return "invalid_scan_target_both_enabled"

    exposure_error = validate_exposure_settings(scanner.exposure_settings)
    if exposure_error is not None:
        return exposure_error

    return None
