from __future__ import annotations

import unittest

from app.trajectory.path_nodes import (
    link_node_chain,
    migrate_legacy_positions,
    ordered_nodes,
)
from app.trajectory.path_normalize import normalize_path_document


class PathMigrateNodesTests(unittest.TestCase):
    def test_legacy_positions_migrate_to_points_and_nodes(self) -> None:
        legacy = {
            "positions": [
                {
                    "id": "0",
                    "type": "home",
                    "comment": "start",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 0},
                },
                {
                    "id": "1",
                    "type": "basic_scan",
                    "comment": "scan",
                    "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 90},
                },
                {
                    "id": "0",
                    "type": "end",
                    "comment": "start",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 0},
                },
            ]
        }

        normalized = normalize_path_document(legacy)

        self.assertNotIn("positions", normalized)
        self.assertEqual(len(normalized["nodes"]), 3)
        self.assertEqual(len(normalized["points"]), 2)
        self.assertNotIn("turntable", normalized["points"][0])
        self.assertIn("turntable", normalized["nodes"][0])

        chain = ordered_nodes(normalized["nodes"])
        self.assertEqual(chain[0]["type"], "home")
        self.assertEqual(chain[-1]["type"], "end")
        self.assertIsNone(chain[0].get("prev_node_id"))
        self.assertIsNone(chain[-1].get("next_node_id"))
        self.assertEqual(chain[1]["prev_node_id"], chain[0]["id"])
        self.assertEqual(chain[1]["next_node_id"], chain[2]["id"])

    def test_duplicate_axes_share_point_id(self) -> None:
        positions = [
            {
                "id": "0",
                "type": "home",
                "comment": "home",
                "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                "turntable": {"angle": 0},
            },
            {
                "id": "0",
                "type": "end",
                "comment": "home",
                "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                "turntable": {"angle": 0},
            },
        ]

        points, nodes = migrate_legacy_positions(positions)
        normalized = normalize_path_document({"points": points, "nodes": nodes})

        home_node = normalized["nodes"][0]
        end_node = normalized["nodes"][1]
        self.assertEqual(home_node["point_id"], end_node["point_id"])
        self.assertEqual(normalized["points"][0]["id"], "0")

    def test_empty_points_nodes_falls_back_to_positions(self) -> None:
        legacy = {
            "points": [],
            "nodes": [],
            "positions": [
                {
                    "id": "0",
                    "type": "home",
                    "comment": "start",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 0},
                },
                {
                    "id": "1",
                    "type": "basic_scan",
                    "comment": "scan",
                    "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 90},
                },
            ],
        }

        normalized = normalize_path_document(legacy)

        self.assertEqual(len(normalized["points"]), 2)
        self.assertEqual(len(normalized["nodes"]), 2)
        self.assertEqual(normalized["nodes"][0]["type"], "home")
        self.assertEqual(normalized["nodes"][1]["type"], "basic_scan")

    def test_legacy_transition_positions_catalog_only_no_nodes(self) -> None:
        legacy = {
            "positions": [
                {
                    "id": "0",
                    "type": "home",
                    "comment": "start",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 0},
                },
                {
                    "id": "1",
                    "type": "transition",
                    "comment": "via",
                    "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 0},
                },
                {
                    "id": "2",
                    "type": "basic_scan",
                    "comment": "scan",
                    "axes": {"J1": 2, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 90},
                },
            ]
        }

        normalized = normalize_path_document(legacy)

        self.assertEqual([node["type"] for node in normalized["nodes"]], ["home", "basic_scan"])
        point_ids = {point["id"] for point in normalized["points"]}
        self.assertIn("1", point_ids)
        self.assertIn("2", point_ids)


if __name__ == "__main__":
    unittest.main()
