from __future__ import annotations



import json

import tempfile

import unittest

from pathlib import Path

from unittest.mock import MagicMock, patch



from app.models.runtime_settings import RuntimeSettings

from app.pipeline.service import PipelineService

from app.trajectory.path_normalize import ensure_neighbor_safe_routes, normalize_path_document

from app.trajectory.routing import normalize_id_safe_routes





class PathNeighborRoutesTests(unittest.TestCase):

    def test_explicit_two_point_matrix_preserved_on_normalize(self) -> None:

        document = {

            "points": [

                {

                    "id": "0",

                    "name": "home",

                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},

                },

                {

                    "id": "1",

                    "name": "scan",

                    "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},

                },

            ],

            "nodes": [

                {"id": "n0", "type": "home", "point_id": "0", "next_node_id": "n1"},

                {"id": "n1", "type": "advanced_scan", "point_id": "1", "prev_node_id": "n0"},

            ],

            "safe_route_ids": ["0", "1"],

            "safe_routes": [

                [True, False],

                [False, True],

            ],

        }



        normalized = normalize_path_document(document)

        matrix = normalized["safe_routes"]



        self.assertFalse(matrix[0][1])

        self.assertFalse(matrix[1][0])



    def test_neighbor_routes_auto_enabled_without_explicit_matrix(self) -> None:

        document = {

            "points": [

                {

                    "id": "0",

                    "comment": "a",

                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},

                    "turntable": {"angle": 0},

                },

                {

                    "id": "1",

                    "comment": "b",

                    "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},

                    "turntable": {"angle": 0},

                },

            ],

            "nodes": [

                {"id": "n0", "type": "home", "point_id": "0", "next_node_id": "n1"},

                {"id": "n1", "type": "end", "point_id": "1", "prev_node_id": "n0"},

            ],

        }



        normalized = normalize_path_document(document)

        matrix = normalized["safe_routes"]

        self.assertTrue(matrix[0][1])

        self.assertTrue(matrix[1][0])



    def test_explicit_neighbor_matrix_not_forced_when_user_disabled(self) -> None:

        document = {

            "points": [

                {

                    "id": "0",

                    "comment": "a",

                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},

                    "turntable": {"angle": 0},

                },

                {

                    "id": "1",

                    "comment": "b",

                    "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},

                    "turntable": {"angle": 0},

                },

            ],

            "nodes": [

                {"id": "n0", "type": "home", "point_id": "0", "next_node_id": "n1"},

                {"id": "n1", "type": "end", "point_id": "1", "prev_node_id": "n0"},

            ],

            "safe_route_ids": ["0", "1"],

            "safe_routes": [

                [True, False],

                [False, True],

            ],

        }



        normalized = normalize_path_document(document)

        matrix = normalized["safe_routes"]

        self.assertFalse(matrix[0][1])

        self.assertFalse(matrix[1][0])



    def test_three_point_non_neighbor_false_survives_save_round_trip(self) -> None:

        payload = {

            "points": [

                {"id": "0", "name": "a", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},

                {"id": "1", "name": "b", "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},

                {"id": "2", "name": "c", "axes": {"J1": 2, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},

            ],

            "nodes": [

                {"id": "n0", "type": "home", "point_id": "0"},

                {"id": "n1", "type": "basic_scan", "point_id": "1"},

                {"id": "n2", "type": "end", "point_id": "2"},

            ],

            "safe_route_ids": ["0", "1", "2"],

            "safe_routes": [

                [True, True, False],

                [True, True, True],

                [False, True, True],

            ],

        }



        with tempfile.TemporaryDirectory() as temp_dir:

            active_path = Path(temp_dir) / "routes_test.json"

            active_path.write_text(json.dumps(payload), encoding="utf-8")



            from app.trajectory.service import TrajectoryService



            with patch("app.trajectory.service.get_runtime_settings") as get_settings:

                get_settings.return_value = RuntimeSettings(

                    paths_folder=temp_dir,

                    active_path_file="routes_test.json",

                )

                service = TrajectoryService()

                saved = service.save_active_document(payload)



            matrix = saved.normalized_document["safe_routes"]

            self.assertFalse(matrix[0][2])

            self.assertFalse(matrix[2][0])



    def test_normalize_id_safe_routes_defaults_two_points_to_all_true(self) -> None:

        matrix = normalize_id_safe_routes(["0", "1"], None)

        self.assertTrue(matrix[0][1])

        self.assertTrue(matrix[1][0])



    def test_normalize_id_safe_routes_respects_explicit_two_point_matrix(self) -> None:

        matrix = normalize_id_safe_routes(

            ["0", "1"],

            [

                [True, False],

                [False, True],

            ],

        )

        self.assertFalse(matrix[0][1])

        self.assertFalse(matrix[1][0])



    def test_same_point_neighbors_do_not_force_route(self) -> None:

        nodes = [

            {"id": "n0", "type": "home", "point_id": "0", "next_node_id": "n1"},

            {"id": "n1", "type": "end", "point_id": "0", "prev_node_id": "n0"},

        ]

        safe_route_ids = ["0"]

        safe_routes = [[True]]



        ensure_neighbor_safe_routes(nodes, safe_route_ids, safe_routes)



        self.assertEqual(safe_routes, [[True]])





class MoveToPathPositionTests(unittest.TestCase):

    @patch("app.pipeline.service.try_connect_turntable")

    @patch("app.pipeline.service.try_connect_robot_path")

    @patch("app.pipeline.service.read_current_axes_from_snapshot")

    @patch("app.pipeline.service.get_runtime_settings")

    def test_move_to_uses_ordered_node_after_normalize(

        self,

        get_runtime_settings: MagicMock,

        read_axes: MagicMock,

        try_connect_robot: MagicMock,

        try_connect_turntable: MagicMock,

    ) -> None:

        get_runtime_settings.return_value = RuntimeSettings()

        read_axes.return_value = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]



        document = {

            "points": [

                {"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},

                {"id": "1", "name": "scan", "axes": {"J1": 5, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},

            ],

            "nodes": [

                {"id": "scan-node", "type": "advanced_scan", "point_id": "1"},

                {"id": "home-node", "type": "home", "point_id": "0"},

            ],

            "safe_route_ids": ["0", "1"],

            "safe_routes": [

                [True, True],

                [True, True],

            ],

        }



        service = PipelineService()

        service._travel_by_id_route = MagicMock(return_value={"route": ["1"], "hops_executed": 1})



        robot = MagicMock()

        robot.connected = True

        robot.turn_connected = True

        service._ensure_jog_robot_client = MagicMock(return_value=robot)



        result = service.move_to_path_position(0, document, node_id="home-node")



        self.assertEqual(result["route"], ["1"])

        service._travel_by_id_route.assert_called_once()
        call_args = service._travel_by_id_route.call_args[0]
        self.assertEqual(call_args[3], "0")





if __name__ == "__main__":

    unittest.main()

