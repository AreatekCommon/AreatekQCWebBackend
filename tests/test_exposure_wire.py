from __future__ import annotations

import unittest

from app.exposure_migration import infer_exposure_mode_from_legacy, migrate_legacy_exposure_settings
from app.exposure_wire import encode_exposure_wire, exposure_sdk_commands
from app.models.scanner_settings import ScannerExposureSettings, ScannerSettings


class ExposureWireTests(unittest.TestCase):
    def test_auto_mode_masks_all_wire_values(self) -> None:
        settings = ScannerExposureSettings(
            mode="auto",
            marker_exp=15,
            val1=30,
            val2=20,
            val3=10,
        )
        wire = encode_exposure_wire(settings)
        self.assertEqual(wire.exp_type, 1)
        self.assertEqual(wire.marker_exp, 1)
        self.assertEqual(wire.val1, 1)
        self.assertEqual(wire.val2, 1)
        self.assertEqual(wire.val3, 1)

    def test_first_mode_keeps_only_val1_on_wire(self) -> None:
        settings = ScannerExposureSettings(
            mode="first",
            marker_exp=12,
            val1=25,
            val2=18,
            val3=9,
        )
        wire = encode_exposure_wire(settings)
        self.assertEqual(wire.exp_type, 0)
        self.assertEqual(wire.marker_exp, 12)
        self.assertEqual(wire.val1, 25)
        self.assertEqual(wire.val2, 1)
        self.assertEqual(wire.val3, 1)

    def test_second_mode_keeps_only_val2_on_wire(self) -> None:
        settings = ScannerExposureSettings(
            mode="second",
            val1=25,
            val2=18,
            val3=9,
        )
        wire = encode_exposure_wire(settings)
        self.assertEqual(wire.val1, 1)
        self.assertEqual(wire.val2, 18)
        self.assertEqual(wire.val3, 1)

    def test_third_mode_keeps_only_val3_on_wire(self) -> None:
        settings = ScannerExposureSettings(
            mode="third",
            val1=25,
            val2=18,
            val3=9,
        )
        wire = encode_exposure_wire(settings)
        self.assertEqual(wire.val1, 1)
        self.assertEqual(wire.val2, 1)
        self.assertEqual(wire.val3, 9)

    def test_customized_first_second_slots(self) -> None:
        settings = ScannerExposureSettings(
            mode="customized",
            customized_slots="first_second",
            val1=11,
            val2=22,
            val3=33,
        )
        wire = encode_exposure_wire(settings)
        self.assertEqual(wire.val1, 11)
        self.assertEqual(wire.val2, 22)
        self.assertEqual(wire.val3, 1)

    def test_customized_all_slots(self) -> None:
        settings = ScannerExposureSettings(
            mode="customized",
            customized_slots="all",
            val1=11,
            val2=22,
            val3=33,
        )
        wire = encode_exposure_wire(settings)
        self.assertEqual((wire.val1, wire.val2, wire.val3), (11, 22, 33))

    def test_exposure_sdk_commands_auto_mode_uses_point_cloud_only(self) -> None:
        wire = encode_exposure_wire(ScannerExposureSettings(mode="auto"))
        commands = exposure_sdk_commands(wire, mode="auto")
        self.assertEqual(commands, [(0, wire)])

    def test_exposure_sdk_commands_manual_mode_uses_dual_targets(self) -> None:
        wire = encode_exposure_wire(
            ScannerExposureSettings(mode="first", marker_exp=12, val1=25)
        )
        commands = exposure_sdk_commands(wire, mode="first")
        self.assertEqual(commands, [(1, wire), (0, wire)])

    def test_legacy_migration_auto(self) -> None:
        mode, slots = infer_exposure_mode_from_legacy(1, 22, 18, 9)
        self.assertEqual(mode, "auto")
        self.assertEqual(slots, "first")

    def test_legacy_migration_first(self) -> None:
        mode, slots = infer_exposure_mode_from_legacy(0, 22, 1, 1)
        self.assertEqual(mode, "first")
        self.assertEqual(slots, "first")

    def test_legacy_migration_customized_all(self) -> None:
        mode, slots = infer_exposure_mode_from_legacy(0, 22, 18, 9)
        self.assertEqual(mode, "customized")
        self.assertEqual(slots, "all")

    def test_scanner_settings_migrates_legacy_device_fields(self) -> None:
        scanner = ScannerSettings.model_validate(
            {
                "device": {
                    "rgb_level": 14,
                    "exp_type": 0,
                    "exp_obj": 1,
                    "marker_exp": 6,
                    "val1": 10,
                    "val2": 1,
                    "val3": 1,
                }
            }
        )
        self.assertEqual(scanner.exposure_settings.mode, "first")
        self.assertEqual(scanner.exposure_settings.marker_exp, 6)
        self.assertEqual(scanner.exposure_settings.val1, 10)
        self.assertFalse(hasattr(scanner.device, "exp_type"))

    def test_migrate_legacy_exposure_settings_clamps_values(self) -> None:
        settings = migrate_legacy_exposure_settings(
            exp_type=0,
            marker_exp=99,
            val1=100,
            val2=0,
            val3=1,
        )
        self.assertEqual(settings["marker_exp"], 25)
        self.assertEqual(settings["val1"], 60)
        self.assertEqual(settings["val2"], 1)


if __name__ == "__main__":
    unittest.main()
