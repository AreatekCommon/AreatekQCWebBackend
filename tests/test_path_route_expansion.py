from __future__ import annotations

import unittest

from app.eki.path_parser import parse_path_document
from app.trajectory.path_normalize import normalize_path_document


def _axes(j1: float = 0.0) -> dict[str, float]:
    return {"J1": j1, "J2": 0.0, "J3": 0.0, "J4": 0.0, "J5": 0.0, "J6": 0.0}


class PathRouteExpansionTests(unittest.TestCase):
    def test_direct_neighbor_route_has_no_inserted_transitions(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {"id": "p0", "name": "home", "axes": _axes(0)},
                    {"id": "p1", "name": "scan", "axes": _axes(1)},
                    {"id": "p2", "name": "end", "axes": _axes(2)},
                ],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "p0",
                        "next_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "1",
                        "type": "basic_scan",
                        "point_id": "p1",
                        "prev_node_id": "0",
                        "next_node_id": "2",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "2",
                        "type": "end",
                        "point_id": "p2",
                        "prev_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                ],
                "safe_route_ids": ["p0", "p1", "p2"],
                "safe_routes": [
                    [True, True, True],
                    [True, True, True],
                    [True, True, True],
                ],
            }
        )

        points = parse_path_document(document)
        point_types = [point.point_type for point in points]

        self.assertEqual(point_types, ["home", "scan", "end"])
        self.assertNotIn("transition", point_types)

    def test_same_point_id_neighbors_have_no_inserted_transitions(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {"id": "p0", "name": "shared", "axes": _axes(0)},
                ],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "p0",
                        "next_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "1",
                        "type": "basic_scan",
                        "point_id": "p0",
                        "prev_node_id": "0",
                        "next_node_id": "2",
                        "turntable": {"angle": 90.0},
                    },
                    {
                        "id": "2",
                        "type": "end",
                        "point_id": "p0",
                        "prev_node_id": "1",
                        "turntable": {"angle": 180.0},
                    },
                ],
                "safe_route_ids": ["p0"],
                "safe_routes": [[True]],
            }
        )

        points = parse_path_document(document)
        point_types = [point.point_type for point in points]

        self.assertEqual(point_types, ["home", "scan", "end"])
        self.assertNotIn("transition", point_types)

    def test_indirect_route_inserts_transition_waypoint(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {"id": "p0", "name": "home", "axes": _axes(0)},
                    {"id": "p1", "name": "waypoint", "axes": _axes(1)},
                    {"id": "p2", "name": "scan", "axes": _axes(2)},
                ],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "p0",
                        "next_node_id": "1",
                        "turntable": {"angle": 15.0},
                    },
                    {
                        "id": "1",
                        "type": "basic_scan",
                        "point_id": "p2",
                        "prev_node_id": "0",
                        "next_node_id": "2",
                        "turntable": {"angle": 45.0},
                    },
                    {
                        "id": "2",
                        "type": "end",
                        "point_id": "p2",
                        "prev_node_id": "1",
                        "turntable": {"angle": 45.0},
                    },
                ],
                "safe_route_ids": ["p0", "p1", "p2"],
                "safe_routes": [
                    [True, True, False],
                    [True, True, True],
                    [False, True, True],
                ],
            }
        )

        points = parse_path_document(document)
        point_types = [point.point_type for point in points]
        comments = [point.comment for point in points]

        self.assertEqual(point_types, ["home", "transition", "scan", "end"])
        self.assertEqual(comments[1], "waypoint")
        self.assertEqual(points[1].a7, 30.0)

    def test_unreachable_neighbor_pair_raises(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {"id": "p0", "name": "home", "axes": _axes(0)},
                    {"id": "p1", "name": "scan", "axes": _axes(1)},
                    {"id": "p2", "name": "end", "axes": _axes(2)},
                ],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "p0",
                        "next_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "1",
                        "type": "basic_scan",
                        "point_id": "p2",
                        "prev_node_id": "0",
                        "next_node_id": "2",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "2",
                        "type": "end",
                        "point_id": "p2",
                        "prev_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                ],
                "safe_route_ids": ["p0", "p1", "p2"],
                "safe_routes": [
                    [True, False, False],
                    [False, True, False],
                    [False, False, True],
                ],
            }
        )

        with self.assertRaises(ValueError) as ctx:
            parse_path_document(document)

        message = str(ctx.exception)
        self.assertIn("No safe route from point 'p0' to 'p2'", message)
        self.assertIn("nodes 0 → 1", message)

    def test_indirect_route_before_advanced_scan(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {"id": "p0", "name": "home", "axes": _axes(0)},
                    {"id": "p1", "name": "waypoint", "axes": _axes(1)},
                    {"id": "p2", "name": "scan", "axes": _axes(2)},
                ],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "p0",
                        "next_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "1",
                        "type": "advanced_scan",
                        "point_id": "p2",
                        "prev_node_id": "0",
                        "next_node_id": "2",
                        "turntable": {
                            "start_angle": 0.0,
                            "end_angle": 180.0,
                            "scan_count": 2,
                        },
                    },
                    {
                        "id": "2",
                        "type": "end",
                        "point_id": "p2",
                        "prev_node_id": "1",
                        "turntable": {"angle": 180.0},
                    },
                ],
                "safe_route_ids": ["p0", "p1", "p2"],
                "safe_routes": [
                    [True, True, False],
                    [True, True, True],
                    [False, True, True],
                ],
            }
        )

        points = parse_path_document(document)
        point_types = [point.point_type for point in points]

        self.assertEqual(point_types[0], "home")
        self.assertEqual(point_types[1], "transition")
        self.assertEqual(point_types[2:], ["scan", "scan", "end"])

    def test_two_transitions_interpolate_turntable_angles(self) -> None:
        document = normalize_path_document(
            {
                "points": [
                    {"id": "p0", "name": "home", "axes": _axes(0)},
                    {"id": "p1", "name": "waypoint_a", "axes": _axes(1)},
                    {"id": "p2", "name": "waypoint_b", "axes": _axes(2)},
                    {"id": "p3", "name": "scan", "axes": _axes(3)},
                ],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "p0",
                        "next_node_id": "1",
                        "turntable": {"angle": 360.0},
                    },
                    {
                        "id": "1",
                        "type": "basic_scan",
                        "point_id": "p3",
                        "prev_node_id": "0",
                        "next_node_id": "2",
                        "turntable": {"angle": 0.0},
                    },
                    {
                        "id": "2",
                        "type": "end",
                        "point_id": "p3",
                        "prev_node_id": "1",
                        "turntable": {"angle": 0.0},
                    },
                ],
                "safe_route_ids": ["p0", "p1", "p2", "p3"],
                "safe_routes": [
                    [True, True, False, False],
                    [True, True, True, False],
                    [False, True, True, True],
                    [False, False, True, True],
                ],
            }
        )

        points = parse_path_document(document)
        transition_angles = [point.a7 for point in points if point.point_type == "transition"]

        self.assertEqual(transition_angles, [240.0, 120.0])


if __name__ == "__main__":
    unittest.main()
