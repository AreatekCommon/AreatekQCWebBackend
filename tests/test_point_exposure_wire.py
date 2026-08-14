from __future__ import annotations

import unittest

from app.exposure_wire import PointExposureValues, build_point_scan_exposure_commands
from app.models.scanner_settings import ScannerExposureSettings


class PointExposureWireTests(unittest.TestCase):
    def test_auto_mode_returns_no_commands(self) -> None:
        settings = ScannerExposureSettings(mode="auto")
        commands = build_point_scan_exposure_commands(
            settings,
            per_point_exposure=True,
            per_point_marker_exposure=True,
            point_vals=PointExposureValues(val1=30, marker_exp=10),
        )
        self.assertEqual(commands, [])

    def test_marker_only_command(self) -> None:
        settings = ScannerExposureSettings(mode="first", val1=22, marker_exp=8)
        commands = build_point_scan_exposure_commands(
            settings,
            per_point_exposure=False,
            per_point_marker_exposure=True,
            point_vals=PointExposureValues(marker_exp=12),
        )
        self.assertEqual(len(commands), 1)
        exp_obj, payload = commands[0]
        self.assertEqual(exp_obj, 1)
        self.assertEqual(payload.marker_exp, 12)
        self.assertEqual(payload.exp_type, 0)

    def test_point_cloud_only_uses_per_point_values(self) -> None:
        settings = ScannerExposureSettings(
            mode="customized",
            customized_slots="all",
            val1=22,
            val2=33,
            val3=44,
            marker_exp=8,
        )
        commands = build_point_scan_exposure_commands(
            settings,
            per_point_exposure=True,
            per_point_marker_exposure=False,
            point_vals=PointExposureValues(val1=10, val2=20, val3=30),
        )
        self.assertEqual(len(commands), 1)
        exp_obj, payload = commands[0]
        self.assertEqual(exp_obj, 0)
        self.assertEqual(payload.val1, 10)
        self.assertEqual(payload.val2, 20)
        self.assertEqual(payload.val3, 30)

    def test_both_marker_and_point_cloud_commands(self) -> None:
        settings = ScannerExposureSettings(mode="second", val2=33, marker_exp=8)
        commands = build_point_scan_exposure_commands(
            settings,
            per_point_exposure=True,
            per_point_marker_exposure=True,
            point_vals=PointExposureValues(val2=40, marker_exp=15),
        )
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][0], 1)
        self.assertEqual(commands[0][1].marker_exp, 15)
        self.assertEqual(commands[1][0], 0)
        self.assertEqual(commands[1][1].val2, 40)
        self.assertEqual(commands[1][1].val1, 1)
        self.assertEqual(commands[1][1].val3, 1)


if __name__ == "__main__":
    unittest.main()
