from __future__ import annotations

import unittest

from app.trajectory.path_normalize import normalize_path_document


class PathStripTransitionsTests(unittest.TestCase):
    def test_normalize_strips_transition_nodes_and_relinks_chain(self) -> None:
        document = {
            "points": [
                {"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "1", "name": "scan", "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "2", "name": "via", "axes": {"J1": 2, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "3", "name": "scan2", "axes": {"J1": 3, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            ],
            "nodes": [
                {
                    "id": "0",
                    "type": "home",
                    "point_id": "0",
                    "next_node_id": "1",
                    "turntable": {"angle": 0.0},
                    "motion": {"speed": 50.0, "acceleration": 50.0},
                },
                {
                    "id": "1",
                    "type": "basic_scan",
                    "point_id": "1",
                    "prev_node_id": "0",
                    "next_node_id": "2",
                    "turntable": {"angle": 90.0},
                    "motion": {"speed": 50.0, "acceleration": 50.0},
                },
                {
                    "id": "2",
                    "type": "transition",
                    "point_id": "2",
                    "prev_node_id": "1",
                    "next_node_id": "3",
                    "turntable": {"angle": 90.0},
                    "motion": {"speed": 50.0, "acceleration": 50.0},
                },
                {
                    "id": "3",
                    "type": "end",
                    "point_id": "3",
                    "prev_node_id": "2",
                    "turntable": {"angle": 0.0},
                    "motion": {"speed": 50.0, "acceleration": 50.0},
                },
            ],
            "safe_route_ids": ["0", "1", "2", "3"],
            "safe_routes": [
                [True, True, True, True],
                [True, True, True, True],
                [True, True, True, True],
                [True, True, True, True],
            ],
        }

        normalized = normalize_path_document(document)

        node_types = [node["type"] for node in normalized["nodes"]]
        self.assertNotIn("transition", node_types)
        self.assertEqual(node_types, ["home", "basic_scan", "end"])

        chain = normalized["nodes"]
        self.assertEqual(chain[0]["next_node_id"], chain[1]["id"])
        self.assertEqual(chain[1]["next_node_id"], chain[2]["id"])
        self.assertIsNone(chain[2].get("next_node_id"))
        self.assertEqual(chain[1]["prev_node_id"], chain[0]["id"])
        self.assertEqual(chain[2]["prev_node_id"], chain[1]["id"])

        point_ids = {point["id"] for point in normalized["points"]}
        self.assertIn("2", point_ids)

    def test_orphan_catalog_point_kept_when_not_referenced(self) -> None:
        document = {
            "points": [
                {"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "9", "name": "orphan", "axes": {"J1": 9, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            ],
            "nodes": [
                {
                    "id": "0",
                    "type": "home",
                    "point_id": "0",
                    "turntable": {"angle": 0.0},
                    "motion": {"speed": 50.0, "acceleration": 50.0},
                },
                {
                    "id": "1",
                    "type": "transition",
                    "point_id": "9",
                    "turntable": {"angle": 0.0},
                    "motion": {"speed": 50.0, "acceleration": 50.0},
                },
            ],
            "safe_route_ids": ["0"],
            "safe_routes": [[True]],
        }

        normalized = normalize_path_document(document)

        point_ids = {point["id"] for point in normalized["points"]}
        self.assertEqual(point_ids, {"0", "9"})


if __name__ == "__main__":
    unittest.main()
