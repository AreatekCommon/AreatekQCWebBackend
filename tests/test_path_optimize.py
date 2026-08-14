from __future__ import annotations

import unittest

from app.trajectory.path_optimize import optimize_path_positions
from app.trajectory.position_ids import sync_comments_by_id


def _basic_scan(angle: float) -> dict:
    return {
        "id": "1",
        "type": "basic_scan",
        "comment": "",
        "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
        "turntable": {"angle": angle, "speed": 50, "acceleration": 50},
    }


def _advanced_scan(start: float, end: float, scan_count: int = 3) -> dict:
    return {
        "id": "2",
        "type": "advanced_scan",
        "comment": "",
        "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
        "turntable": {
            "advanced_scan_mode": "range",
            "start_angle": start,
            "end_angle": end,
            "scan_count": scan_count,
            "speed": 50,
            "acceleration": 50,
        },
    }


def _advanced_scan_step(start: float, scan_count: int, step_angle: float) -> dict:
    return {
        "id": "2",
        "type": "advanced_scan",
        "comment": "",
        "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
        "turntable": {
            "advanced_scan_mode": "step",
            "start_angle": start,
            "scan_count": scan_count,
            "step_angle": step_angle,
            "speed": 50,
            "acceleration": 50,
        },
    }


class PathOptimizeTests(unittest.TestCase):
    def test_advanced_scan_swaps_when_previous_exit_closer_to_end(self) -> None:
        positions = [
            _basic_scan(170.0),
            _advanced_scan(0.0, 180.0),
        ]

        optimize_path_positions(positions)

        turntable = positions[1]["turntable"]
        self.assertEqual(turntable["start_angle"], 180.0)
        self.assertEqual(turntable["end_angle"], 0.0)

    def test_advanced_scan_does_not_swap_when_previous_exit_closer_to_start(self) -> None:
        positions = [
            _basic_scan(0.0),
            _advanced_scan(0.0, 360.0),
        ]

        optimize_path_positions(positions)

        turntable = positions[1]["turntable"]
        self.assertEqual(turntable["start_angle"], 0.0)
        self.assertEqual(turntable["end_angle"], 360.0)

    def test_first_advanced_scan_without_prior_scan_is_unchanged(self) -> None:
        positions = [_advanced_scan(0.0, 360.0)]

        optimize_path_positions(positions)

        turntable = positions[0]["turntable"]
        self.assertEqual(turntable["start_angle"], 0.0)
        self.assertEqual(turntable["end_angle"], 360.0)

    def test_sync_comments_by_id_merges_duplicate_ids(self) -> None:
        positions = [
            {"id": "2", "comment": "Shared label", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            {"id": "2", "comment": "Other text", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            {"id": "3", "comment": "", "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            {"id": "3", "comment": "Pose three", "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
        ]

        sync_comments_by_id(positions)

        self.assertEqual(positions[0]["comment"], "Shared label")
        self.assertEqual(positions[1]["comment"], "Shared label")
        self.assertEqual(positions[2]["comment"], "Pose three")
        self.assertEqual(positions[3]["comment"], "Pose three")

    def test_consecutive_advanced_scans_keep_360_to_0_after_full_revolution(self) -> None:
        positions = [
            _advanced_scan(0.0, 360.0),
            _advanced_scan(360.0, 0.0),
        ]

        optimize_path_positions(positions)

        turntable = positions[1]["turntable"]
        self.assertEqual(turntable["start_angle"], 360.0)
        self.assertEqual(turntable["end_angle"], 0.0)

    def test_brake_dnishe_swaps_after_dom_ends_at_zero(self) -> None:
        positions = [
            _advanced_scan(0.0, 360.0),
            _advanced_scan(360.0, 0.0),
            _advanced_scan(360.0, 0.0),
        ]

        optimize_path_positions(positions)

        self.assertEqual(positions[1]["turntable"]["start_angle"], 360.0)
        self.assertEqual(positions[1]["turntable"]["end_angle"], 0.0)
        self.assertEqual(positions[2]["turntable"]["start_angle"], 0.0)
        self.assertEqual(positions[2]["turntable"]["end_angle"], 360.0)

    def test_step_mode_does_not_swap_start_and_end(self) -> None:
        positions = [
            _basic_scan(170.0),
            _advanced_scan_step(0.0, 4, 90.0),
        ]

        optimize_path_positions(positions)

        turntable = positions[1]["turntable"]
        self.assertEqual(turntable["advanced_scan_mode"], "step")
        self.assertEqual(turntable["start_angle"], 0.0)
        self.assertEqual(turntable["step_angle"], 90.0)
        self.assertNotIn("end_angle", turntable)

    def test_step_mode_tracks_exit_from_last_step(self) -> None:
        positions = [
            _advanced_scan_step(0.0, 4, 90.0),
            _advanced_scan(90.0, 270.0),
        ]

        optimize_path_positions(positions)

        turntable = positions[1]["turntable"]
        self.assertEqual(turntable["start_angle"], 270.0)
        self.assertEqual(turntable["end_angle"], 90.0)


if __name__ == "__main__":
    unittest.main()
