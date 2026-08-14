import json
import unittest
from pathlib import Path

from app.trajectory.routing import (
    find_first_scan_position_id,
    find_home_position_id,
    plan_id_route_to_goal,
    read_current_axes_from_snapshot,
)


def _load_sample_document() -> dict:
    sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_movement_path.json"
    return json.loads(sample_path.read_text(encoding="utf-8"))


def _load_sample_points() -> list[dict]:
    return _load_sample_document()["points"]


def _load_sample_nodes() -> list[dict]:
    return _load_sample_document()["nodes"]


def _home_axes(points: list[dict]) -> list[float]:
    home = next(point for point in points if point.get("id") == "0")
    return [
        float(home["axes"]["J1"]),
        float(home["axes"]["J2"]),
        float(home["axes"]["J3"]),
        float(home["axes"]["J4"]),
        float(home["axes"]["J5"]),
        float(home["axes"]["J6"]),
    ]


class RoutingStartupTests(unittest.TestCase):
    def test_find_home_position_id_finds_first_home(self) -> None:
        nodes = _load_sample_nodes()
        self.assertEqual(find_home_position_id(nodes), "0")

    def test_find_first_scan_position_id_finds_first_scan(self) -> None:
        nodes = _load_sample_nodes()
        self.assertEqual(find_first_scan_position_id(nodes), "1")

    def test_find_first_scan_position_id_missing_scan(self) -> None:
        nodes = [
            {
                "id": "0",
                "type": "home",
                "point_id": "0",
            },
            {
                "id": "1",
                "type": "end",
                "point_id": "0",
            },
        ]
        with self.assertRaises(ValueError):
            find_first_scan_position_id(nodes)

    def test_read_current_axes_requires_joint_values(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            read_current_axes_from_snapshot({"connected": True, "a1": 1.0})
        self.assertIn("Robot axis position is not available", str(ctx.exception))

    def test_read_current_axes_without_connection_when_joints_present(self) -> None:
        axes = read_current_axes_from_snapshot(
            {
                "connected": False,
                "a1": 1.0,
                "a2": 2.0,
                "a3": 3.0,
                "a4": 4.0,
                "a5": 5.0,
                "a6": 6.0,
            }
        )
        self.assertEqual(axes, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_plan_id_route_unknown_position(self) -> None:
        points = _load_sample_points()
        with self.assertRaises(RuntimeError) as ctx:
            plan_id_route_to_goal(
                [999.0, 999.0, 999.0, 999.0, 999.0, 999.0],
                points,
                [[True]],
                ["0"],
                "0",
            )
        self.assertIn("not at a known position", str(ctx.exception))

    def test_plan_id_route_no_route_to_first_scan(self) -> None:
        points = _load_sample_points()
        scan_point = next(point for point in points if point["id"] == "1")
        scan_axes = [
            float(scan_point["axes"]["J1"]),
            float(scan_point["axes"]["J2"]),
            float(scan_point["axes"]["J3"]),
            float(scan_point["axes"]["J4"]),
            float(scan_point["axes"]["J5"]),
            float(scan_point["axes"]["J6"]),
        ]
        safe_route_ids = ["0", "1"]
        safe_routes = [
            [True, False],
            [False, True],
        ]
        with self.assertRaises(RuntimeError) as ctx:
            plan_id_route_to_goal(
                scan_axes,
                points,
                safe_routes,
                safe_route_ids,
                "0",
                no_route_message="No safe route to first scan position",
            )
        self.assertIn("No safe route to first scan position", str(ctx.exception))

    def test_plan_id_route_already_at_first_scan(self) -> None:
        points = _load_sample_points()
        scan_point = next(point for point in points if point["id"] == "1")
        scan_axes = [
            float(scan_point["axes"]["J1"]),
            float(scan_point["axes"]["J2"]),
            float(scan_point["axes"]["J3"]),
            float(scan_point["axes"]["J4"]),
            float(scan_point["axes"]["J5"]),
            float(scan_point["axes"]["J6"]),
        ]
        safe_route_ids = ["0", "1", "2"]
        safe_routes = [
            [True, True, True],
            [True, True, True],
            [True, True, True],
        ]
        start_ids, id_route = plan_id_route_to_goal(
            scan_axes,
            points,
            safe_routes,
            safe_route_ids,
            "1",
        )
        self.assertIn("1", start_ids)
        self.assertEqual(id_route, ["1"])


if __name__ == "__main__":
    unittest.main()
