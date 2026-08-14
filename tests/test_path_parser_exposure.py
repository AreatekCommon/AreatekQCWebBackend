from __future__ import annotations

import unittest

from app.eki.path_parser import parse_positions_json


class PathParserExposureTests(unittest.TestCase):
    def test_basic_scan_exposure_copied_to_trajectory_point(self) -> None:
        document = {
            "positions": [
                {
                    "id": "1",
                    "type": "basic_scan",
                    "comment": "scan",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 90},
                    "exposure": {"val1": 25, "marker_exp": 11},
                }
            ]
        }

        points = parse_positions_json(document)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].exposure_val1, 25)
        self.assertEqual(points[0].exposure_marker_exp, 11)

    def test_advanced_scan_exposure_copied_to_each_step(self) -> None:
        document = {
            "positions": [
                {
                    "id": "1",
                    "type": "advanced_scan",
                    "comment": "adv",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {
                        "start_angle": 0,
                        "end_angle": 180,
                        "scan_count": 2,
                    },
                    "exposure": {"val2": 30, "marker_exp": 9},
                }
            ]
        }

        points = parse_positions_json(document)

        self.assertEqual(len(points), 2)
        for point in points:
            self.assertEqual(point.exposure_val2, 30)
            self.assertEqual(point.exposure_marker_exp, 9)


if __name__ == "__main__":
    unittest.main()
