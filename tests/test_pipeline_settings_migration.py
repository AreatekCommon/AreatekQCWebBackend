from __future__ import annotations

import unittest

from app.models.pipeline_settings import PipelineSettings
from app.trajectory.routing import interpolate_turntable_angles


class PipelineSettingsMigrationTests(unittest.TestCase):
    def test_legacy_stop_after_last_scan_true_maps_to_single_last_scan(self) -> None:
        settings = PipelineSettings.model_validate({"stop_after_last_scan": True})
        self.assertEqual(settings.cycle_run_mode, "single_last_scan")
        self.assertTrue(settings.stop_after_last_scan)

    def test_legacy_stop_after_last_scan_false_defaults_to_single_full(self) -> None:
        settings = PipelineSettings.model_validate({"stop_after_last_scan": False})
        self.assertEqual(settings.cycle_run_mode, "single_full")
        self.assertFalse(settings.stop_after_last_scan)


class TurntableInterpolationTests(unittest.TestCase):
    def test_single_transition_halves_delta(self) -> None:
        self.assertEqual(interpolate_turntable_angles(360.0, 0.0, 1), [180.0])

    def test_two_transitions_split_into_thirds(self) -> None:
        self.assertEqual(interpolate_turntable_angles(360.0, 0.0, 2), [240.0, 120.0])


if __name__ == "__main__":
    unittest.main()
