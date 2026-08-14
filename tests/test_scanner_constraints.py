from __future__ import annotations

import unittest

from app.models.scanner_settings import ScannerScanParams, ScannerSettings
from app.scanner.constraints import (
    normalize_scanner_settings,
    validate_scanner_constraints,
)


class ScannerConstraintsTests(unittest.TestCase):
    def _scanner(
        self,
        *,
        work_range: int = 1,
        marker_radius: int = 4,
        align_mod: int = 8,
        scan_markers: bool = False,
        scan_point_cloud: bool = True,
        add_global_markers: bool = True,
    ) -> ScannerSettings:
        return ScannerSettings(
            work_range=work_range,
            scan=ScannerScanParams(
                align_mod=align_mod,
                marker_radius=marker_radius,
                scan_markers=scan_markers,
                scan_point_cloud=scan_point_cloud,
                add_global_markers=add_global_markers,
            ),
        )

    def test_normalize_masks_invalid_marker_radius_for_large_range(self) -> None:
        scanner = self._scanner(marker_radius=7)
        normalized = normalize_scanner_settings(scanner)
        self.assertEqual(normalized.scan.marker_radius, 6)

    def test_normalize_preserves_combined_marker_radius_on_large_range(self) -> None:
        scanner = self._scanner(marker_radius=6)
        normalized = normalize_scanner_settings(scanner)
        self.assertEqual(normalized.scan.marker_radius, 6)

    def test_normalize_preserves_all_sizes_on_small_range(self) -> None:
        scanner = self._scanner(work_range=0, marker_radius=7)
        normalized = normalize_scanner_settings(scanner)
        self.assertEqual(normalized.scan.marker_radius, 7)

    def test_validate_accepts_combined_marker_radius_on_large_range(self) -> None:
        scanner = self._scanner(marker_radius=6)
        self.assertIsNone(validate_scanner_constraints(scanner))

    def test_validate_rejects_invalid_marker_radius_on_large_range(self) -> None:
        scanner = self._scanner(marker_radius=7)
        self.assertEqual(
            validate_scanner_constraints(scanner),
            "invalid_marker_radius_for_work_range",
        )

    def test_normalize_clears_both_scan_targets(self) -> None:
        scanner = self._scanner(scan_markers=True, scan_point_cloud=True)
        normalized = normalize_scanner_settings(scanner)
        self.assertFalse(normalized.scan.scan_markers)
        self.assertTrue(normalized.scan.scan_point_cloud)

    def test_validate_rejects_both_scan_targets(self) -> None:
        scanner = self._scanner(scan_markers=True, scan_point_cloud=True)
        self.assertEqual(validate_scanner_constraints(scanner), "invalid_scan_target_both_enabled")

    def test_markers_only_forces_global_align_and_p3(self) -> None:
        scanner = self._scanner(
            align_mod=4,
            scan_markers=True,
            scan_point_cloud=False,
            add_global_markers=False,
        )
        scanner = scanner.model_copy(update={"save_type": "stl"})
        normalized = normalize_scanner_settings(scanner)
        self.assertEqual(normalized.scan.align_mod, 8)
        self.assertEqual(normalized.save_type, "p3")

    def test_point_cloud_preserves_global_align_mod(self) -> None:
        scanner = self._scanner(align_mod=8, scan_markers=False, scan_point_cloud=True)
        normalized = normalize_scanner_settings(scanner)
        self.assertEqual(normalized.scan.align_mod, 8)
        self.assertFalse(normalized.scan.scan_markers)
        self.assertTrue(normalized.scan.scan_point_cloud)

    def test_global_align_does_not_flip_scan_target_to_point_cloud(self) -> None:
        scanner = self._scanner(
            align_mod=8,
            scan_markers=True,
            scan_point_cloud=False,
            add_global_markers=True,
        )
        normalized = normalize_scanner_settings(scanner)
        self.assertTrue(normalized.scan.scan_markers)
        self.assertFalse(normalized.scan.scan_point_cloud)
        self.assertEqual(normalized.scan.align_mod, 8)


if __name__ == "__main__":
    unittest.main()
