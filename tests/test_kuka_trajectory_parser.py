from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.eki.path_parser import parse_path_document
from app.trajectory.kuka_trajectory_parser import (
    KukaTrajectoryParseError,
    parse_kuka_trajectory_data,
    parse_kuka_trajectory_file,
)


SAMPLE_KUKA = {
    "path_settings": {"version": "1.0"},
    "paths": [
        {
            "index": 0,
            "point_type": "transition",
            "comment": "过渡点",
            "arm_joint_angles": {
                "J1": 0.0,
                "J2": -120.0,
                "J3": 120.0,
                "J4": 0.0,
                "J5": 0.0,
                "J6": 0.0,
            },
            "arm_motion_paras": {"speed": 50.0, "acceleration": 50.0},
            "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
        },
        {
            "index": 1,
            "point_type": "scan",
            "comment": "扫描点",
            "arm_joint_angles": {
                "J1": -48.46522314992055,
                "J2": -80.53387424514872,
                "J3": 88.94574176783567,
                "J4": 32.68123187349842,
                "J5": -71.65200765955778,
                "J6": -70.36875536825747,
            },
            "arm_motion_paras": {"speed": 40.0, "acceleration": 45.0},
            "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
        },
        {
            "index": 2,
            "point_type": "scan",
            "comment": "扫描点 2",
            "arm_joint_angles": {
                "J1": -37.48126983642578,
                "J2": -90.89015197753906,
                "J3": 111.61524200439453,
                "J4": 0.5149440765380859,
                "J5": 69.71473693847656,
                "J6": -105.94129180908203,
            },
            "arm_motion_paras": {"speed": 50.0, "acceleration": 50.0},
            "turntable": {"angle": 360.0, "speed": 50.0, "acceleration": 50.0},
        },
        {
            "index": 3,
            "point_type": "scan",
            "comment": "扫描点 3",
            "arm_joint_angles": {
                "J1": -40.35213851928711,
                "J2": -26.405885696411133,
                "J3": 94.2444076538086,
                "J4": -73.09336853027344,
                "J5": 40.607784271240234,
                "J6": -32.641334533691406,
            },
            "arm_motion_paras": {"speed": 50.0, "acceleration": 50.0},
            "turntable": {"angle": 79.49718475341797, "speed": 50.0, "acceleration": 50.0},
        },
    ],
}


class KukaTrajectoryParserTests(unittest.TestCase):
    def test_parse_sample_structure(self) -> None:
        document = parse_kuka_trajectory_data(SAMPLE_KUKA)

        self.assertEqual(len(document["points"]), 4)
        self.assertEqual(len(document["nodes"]), 5)

        node_types = [node["type"] for node in document["nodes"]]
        self.assertEqual(node_types[0], "home")
        self.assertEqual(node_types[1:-1], ["basic_scan", "basic_scan", "basic_scan"])
        self.assertEqual(node_types[-1], "end")

        self.assertEqual(document["nodes"][0]["point_id"], "1")
        self.assertEqual(document["nodes"][-1]["point_id"], "1")
        self.assertEqual(document["nodes"][-1]["id"], "5")

        for node in document["nodes"]:
            turntable = node.get("turntable") or {}
            self.assertEqual(turntable.get("angle"), 0.0)

        self.assertEqual(document["nodes"][1]["motion"]["speed"], 40.0)
        self.assertEqual(document["nodes"][1]["motion"]["acceleration"], 45.0)

        self.assertEqual(document["points"][0]["name"], "Point 1")
        self.assertEqual(document["points"][0]["id"], "1")
        self.assertEqual([point["id"] for point in document["points"]], ["1", "2", "3", "4"])
        self.assertEqual(
            [point["name"] for point in document["points"]],
            ["Point 1", "Point 2", "Point 3", "Point 4"],
        )
        self.assertAlmostEqual(document["points"][1]["axes"]["J1"], -48.47, places=2)

        parse_path_document(document)

    def test_ignores_comments_and_uses_one_based_numbering(self) -> None:
        document = parse_kuka_trajectory_data(SAMPLE_KUKA)

        self.assertEqual(len(document["points"]), 4)
        for index, point in enumerate(document["points"], start=1):
            self.assertEqual(point["id"], str(index))
            self.assertEqual(point["name"], f"Point {index}")

        self.assertEqual(document["nodes"][-1]["id"], "5")
        self.assertEqual(document["nodes"][-1]["point_id"], "1")

    def test_parse_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "scan_path_test.json"
            source.write_text(json.dumps(SAMPLE_KUKA), encoding="utf-8")
            document = parse_kuka_trajectory_file(source)
            self.assertEqual(len(document["nodes"]), 5)

    def test_rejects_empty_paths(self) -> None:
        with self.assertRaises(KukaTrajectoryParseError):
            parse_kuka_trajectory_data({"paths": []})

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(KukaTrajectoryParseError):
            parse_kuka_trajectory_file(Path("missing_file.json"))


if __name__ == "__main__":
    unittest.main()
