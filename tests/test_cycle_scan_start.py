import json
import unittest
from pathlib import Path

from app.eki.path_parser import parse_positions_json
from app.pipeline.cycle import get_first_scan_list_index, get_last_scan_list_index


class CycleScanStartTests(unittest.TestCase):
    def test_get_first_scan_list_index_skips_home(self) -> None:
        sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_movement_path.json"
        document = json.loads(sample_path.read_text(encoding="utf-8"))
        points = parse_positions_json(document)

        first_scan_index = get_first_scan_list_index(points)

        self.assertGreater(first_scan_index, 0)
        self.assertEqual(points[0].point_type, "home")
        self.assertEqual(points[first_scan_index].point_type, "scan")

    def test_get_first_scan_list_index_missing_scan(self) -> None:
        document = {
            "positions": [
                {
                    "id": "0",
                    "type": "home",
                    "comment": "home",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {"angle": 0, "speed": 50, "acceleration": 50},
                },
                {
                    "id": "1",
                    "type": "end",
                    "comment": "end",
                    "axes": {"J1": 1, "J2": 1, "J3": 1, "J4": 1, "J5": 1, "J6": 1},
                    "turntable": {"angle": 0, "speed": 50, "acceleration": 50},
                },
            ]
        }
        points = parse_positions_json(document)

        with self.assertRaises(RuntimeError) as ctx:
            get_first_scan_list_index(points)

        self.assertIn("no scan point", str(ctx.exception))

    def test_get_last_scan_list_index(self) -> None:
        sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_movement_path.json"
        document = json.loads(sample_path.read_text(encoding="utf-8"))
        points = parse_positions_json(document)

        last_scan_index = get_last_scan_list_index(points)

        self.assertEqual(points[last_scan_index].point_type, "scan")
        for list_index, point in enumerate(points):
            if list_index > last_scan_index:
                self.assertNotEqual(point.point_type, "scan")


if __name__ == "__main__":
    unittest.main()
