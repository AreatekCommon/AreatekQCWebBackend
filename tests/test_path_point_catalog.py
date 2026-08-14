from __future__ import annotations

import unittest

from app.eki.path_parser import merge_node_point, parse_path_document
from app.trajectory.path_normalize import normalize_path_document


class PathPointCatalogTests(unittest.TestCase):
    def test_merge_node_point_uses_node_settings(self) -> None:
        point = {
            "id": "1",
            "name": "Scan pose",
            "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
        }
        node = {
            "id": "n1",
            "type": "basic_scan",
            "point_id": "1",
            "turntable": {"angle": 45.0, "speed": 50.0, "acceleration": 50.0},
            "motion": {"speed": 40.0, "acceleration": 40.0},
            "exposure": {"val1": 12, "marker_exp": 3},
        }

        merged = merge_node_point(node, point)

        self.assertEqual(merged["type"], "basic_scan")
        self.assertEqual(merged["turntable"]["angle"], 45.0)
        self.assertEqual(merged["exposure"]["val1"], 12)
        self.assertNotIn("turntable", point)

    def test_normalize_strips_point_settings(self) -> None:
        document = {
            "points": [
                {
                    "id": "0",
                    "name": "Home",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 90.0},
                }
            ],
            "nodes": [
                {
                    "id": "n0",
                    "type": "home",
                    "point_id": "0",
                    "turntable": {"angle": 15.0, "speed": 50.0, "acceleration": 50.0},
                }
            ],
        }

        normalized = normalize_path_document(document)

        self.assertEqual(normalized["points"][0], {
            "id": "0",
            "name": "Home",
            "axes": {"J1": 0.0, "J2": 0.0, "J3": 0.0, "J4": 0.0, "J5": 0.0, "J6": 0.0},
        })
        self.assertEqual(normalized["nodes"][0]["turntable"]["angle"], 15.0)

    def test_parse_reads_exposure_from_node(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {
                        "id": "1",
                        "name": "scan",
                        "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    }
                ],
                "nodes": [
                    {
                        "id": "n1",
                        "type": "basic_scan",
                        "point_id": "1",
                        "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
                        "motion": {"speed": 50.0, "acceleration": 50.0},
                        "exposure": {"val1": 22, "marker_exp": 5},
                    }
                ],
            }
        )

        points = parse_path_document(document)

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].exposure_val1, 22)
        self.assertEqual(points[0].exposure_marker_exp, 5)


if __name__ == "__main__":
    unittest.main()
