from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.runtime_settings import RuntimeSettings
from app.pipeline.service import PipelineService
from app.trajectory.path_normalize import normalize_path_document


class SinglePointPathTests(unittest.TestCase):
    def test_single_catalog_point_with_home_and_scan_nodes_normalizes(self) -> None:
        document = {
            "points": [
                {
                    "id": "0",
                    "name": "shared",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                }
            ],
            "nodes": [
                {"id": "0", "type": "home", "point_id": "0", "next_node_id": "1"},
                {"id": "1", "type": "advanced_scan", "point_id": "0", "prev_node_id": "0"},
            ],
            "safe_route_ids": ["0"],
            "safe_routes": [[True]],
        }

        normalized = normalize_path_document(document)

        self.assertEqual(len(normalized["points"]), 1)
        self.assertEqual(normalized["nodes"][0]["point_id"], "0")
        self.assertEqual(normalized["nodes"][1]["point_id"], "0")

    def test_single_point_path_save_round_trip(self) -> None:
        payload = {
            "points": [
                {
                    "id": "0",
                    "name": "shared",
                    "axes": {"J1": 1, "J2": 2, "J3": 3, "J4": 4, "J5": 5, "J6": 6},
                }
            ],
            "nodes": [
                {"id": "0", "type": "home", "point_id": "0", "next_node_id": "1"},
                {"id": "1", "type": "basic_scan", "point_id": "0", "prev_node_id": "0"},
            ],
            "safe_route_ids": ["0"],
            "safe_routes": [[True]],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "single_point.json"
            active_path.write_text(json.dumps(payload), encoding="utf-8")

            from app.trajectory.service import TrajectoryService

            with patch("app.trajectory.service.get_runtime_settings") as get_settings:
                get_settings.return_value = RuntimeSettings(
                    paths_folder=temp_dir,
                    active_path_file="single_point.json",
                )
                service = TrajectoryService()
                saved = service.save_active_document(payload)

            self.assertEqual(len(saved.normalized_document["points"]), 1)
            self.assertEqual(saved.normalized_document["nodes"][1]["type"], "basic_scan")


class MoveToZeroTurntableTests(unittest.TestCase):
    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_move_to_sends_zero_turntable_angle(
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
                {
                    "id": "0",
                    "type": "home",
                    "point_id": "0",
                    "next_node_id": "1",
                    "turntable": {"angle": 45.0},
                },
                {
                    "id": "1",
                    "type": "advanced_scan",
                    "point_id": "1",
                    "prev_node_id": "0",
                    "turntable": {"start_angle": 90.0, "end_angle": 360.0, "scan_count": 1},
                },
            ],
            "safe_route_ids": ["0", "1"],
            "safe_routes": [
                [True, True],
                [True, True],
            ],
        }

        service = PipelineService()
        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.jog_to_target = MagicMock()
        service._ensure_jog_robot_client = MagicMock(return_value=robot)

        service.move_to_path_position(1, document, node_id="1")

        robot.jog_to_target.assert_called()
        for call in robot.jog_to_target.call_args_list:
            self.assertEqual(call.args[1], 0.0)


class MoveToBasicScanAngleTests(unittest.TestCase):
    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_move_to_basic_scan_sends_node_turntable_angle(
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
                {
                    "id": "0",
                    "type": "home",
                    "point_id": "0",
                    "next_node_id": "1",
                    "turntable": {"angle": 0.0},
                },
                {
                    "id": "1",
                    "type": "basic_scan",
                    "point_id": "1",
                    "prev_node_id": "0",
                    "turntable": {"angle": 90.0},
                },
            ],
            "safe_route_ids": ["0", "1"],
            "safe_routes": [[True, True], [True, True]],
        }

        service = PipelineService()
        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.jog_to_target = MagicMock()
        service._ensure_jog_robot_client = MagicMock(return_value=robot)

        service.move_to_path_position(1, document, node_id="1")

        robot.jog_to_target.assert_called_once()
        self.assertEqual(robot.jog_to_target.call_args.args[1], 90.0)


class PostStopMoveToTests(unittest.TestCase):
    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_move_to_works_after_cycle_cancel_flag(
        self,
        get_runtime_settings: MagicMock,
        read_axes: MagicMock,
        try_connect_robot: MagicMock,
        try_connect_turntable: MagicMock,
    ) -> None:
        from app.eki.path_client import KukaEkiPathClient

        get_runtime_settings.return_value = RuntimeSettings()
        read_axes.return_value = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        document = {
            "points": [
                {"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "1", "name": "scan", "axes": {"J1": 5, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            ],
            "nodes": [
                {
                    "id": "0",
                    "type": "home",
                    "point_id": "0",
                    "next_node_id": "1",
                    "turntable": {"angle": 0.0},
                },
                {
                    "id": "1",
                    "type": "basic_scan",
                    "point_id": "1",
                    "prev_node_id": "0",
                    "turntable": {"angle": 90.0},
                },
            ],
            "safe_route_ids": ["0", "1"],
            "safe_routes": [[True, True], [True, True]],
        }

        service = PipelineService()
        robot = KukaEkiPathClient(robot_ip="127.0.0.1")
        robot.connected = True
        robot.turn_connected = True
        robot.cancel_motion()
        self.assertTrue(robot._motion_cancel_event.is_set())
        robot.wait_until_status = MagicMock(return_value=True)
        robot.wait_motion_done = MagicMock(return_value=True)
        service._ensure_jog_robot_client = MagicMock(return_value=robot)

        result = service.move_to_path_position(1, document, node_id="1")

        self.assertFalse(robot._motion_cancel_event.is_set())
        self.assertEqual(result["hops_executed"], 1)


class BasicScanForceTravelTests(unittest.TestCase):
    def _shared_point_document(self) -> dict:
        return {
            "points": [
                {
                    "id": "0",
                    "name": "shared",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                }
            ],
            "nodes": [
                {
                    "id": "home-node",
                    "type": "home",
                    "point_id": "0",
                    "next_node_id": "scan-node",
                    "turntable": {"angle": 0.0},
                },
                {
                    "id": "scan-node",
                    "type": "basic_scan",
                    "point_id": "0",
                    "prev_node_id": "home-node",
                    "turntable": {"angle": 90.0},
                },
            ],
            "safe_route_ids": ["0"],
            "safe_routes": [[True]],
        }

    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_move_to_basic_scan_forces_jog_when_axes_match(
        self,
        get_runtime_settings: MagicMock,
        read_axes: MagicMock,
        try_connect_robot: MagicMock,
        try_connect_turntable: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        read_axes.return_value = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        service = PipelineService()
        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.jog_to_target = MagicMock()
        service._ensure_jog_robot_client = MagicMock(return_value=robot)

        result = service.move_to_path_position(1, self._shared_point_document(), node_id="scan-node")

        self.assertEqual(result["hops_executed"], 1)
        robot.jog_to_target.assert_called_once()

    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_move_to_home_skips_when_axes_match(
        self,
        get_runtime_settings: MagicMock,
        read_axes: MagicMock,
        try_connect_robot: MagicMock,
        try_connect_turntable: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        read_axes.return_value = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        service = PipelineService()
        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.jog_to_target = MagicMock()
        service._ensure_jog_robot_client = MagicMock(return_value=robot)

        result = service.move_to_path_position(0, self._shared_point_document(), node_id="home-node")

        self.assertEqual(result["hops_executed"], 0)
        robot.jog_to_target.assert_not_called()

    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_startup_travel_forces_jog_for_basic_scan_at_shared_point(
        self,
        get_runtime_settings: MagicMock,
        read_axes: MagicMock,
        try_connect_robot: MagicMock,
        try_connect_turntable: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        read_axes.return_value = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        service = PipelineService()
        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.jog_to_target = MagicMock()

        service._plan_first_scan_travel = MagicMock(
            return_value=(
                self._shared_point_document(),
                "0",
                ["0"],
                ["0"],
            )
        )

        result = service._travel_by_id_route(
            robot,
            self._shared_point_document()["points"],
            ["0"],
            "0",
            ["0"],
            nodes=self._shared_point_document()["nodes"],
            force_travel=True,
            goal_node_id="scan-node",
        )

        self.assertEqual(result["hops_executed"], 1)
        robot.jog_to_target.assert_called_once()


class GraphLinkPreservationTests(unittest.TestCase):
    def _three_node_document(self) -> dict:
        return {
            "points": [
                {"id": "p0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "p1", "name": "scan", "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "p2", "name": "end", "axes": {"J1": 2, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            ],
            "nodes": [
                {"id": "0", "type": "home", "point_id": "p0", "next_node_id": "1", "x": 40, "y": 40},
                {"id": "1", "type": "basic_scan", "point_id": "p1", "prev_node_id": "0", "next_node_id": "2", "x": 260, "y": 40},
                {"id": "2", "type": "end", "point_id": "p2", "prev_node_id": "1", "x": 480, "y": 40},
            ],
            "safe_route_ids": ["p0", "p1", "p2"],
            "safe_routes": [
                [True, True, True],
                [True, True, True],
                [True, True, True],
            ],
        }

    def test_normalize_preserves_skip_connection(self) -> None:
        document = self._three_node_document()
        document["nodes"][0]["next_node_id"] = "2"
        document["nodes"][2]["prev_node_id"] = "0"
        document["nodes"][1].pop("prev_node_id", None)
        document["nodes"][1].pop("next_node_id", None)

        normalized = normalize_path_document(document)

        by_id = {node["id"]: node for node in normalized["nodes"]}
        self.assertEqual(by_id["0"].get("next_node_id"), "2")
        self.assertEqual(by_id["2"].get("prev_node_id"), "0")
        self.assertNotIn("next_node_id", by_id["1"])
        self.assertNotIn("prev_node_id", by_id["1"])

    def test_normalize_does_not_rechain_after_disconnect(self) -> None:
        document = self._three_node_document()
        document["nodes"][0].pop("next_node_id", None)
        document["nodes"][1].pop("prev_node_id", None)

        normalized = normalize_path_document(document)

        by_id = {node["id"]: node for node in normalized["nodes"]}
        self.assertNotIn("next_node_id", by_id["0"])
        self.assertNotIn("prev_node_id", by_id["1"])

    def test_normalize_preserves_orphan_connect_to_middle(self) -> None:
        document = self._three_node_document()
        document["nodes"][0].pop("next_node_id", None)
        document["nodes"][1].pop("prev_node_id", None)
        document["nodes"][1]["next_node_id"] = "0"
        document["nodes"][0]["prev_node_id"] = "1"

        normalized = normalize_path_document(document)

        by_id = {node["id"]: node for node in normalized["nodes"]}
        self.assertEqual(by_id["1"].get("next_node_id"), "0")
        self.assertEqual(by_id["0"].get("prev_node_id"), "1")
        self.assertNotIn("next_node_id", by_id["0"])

    def test_normalize_preserves_node_positions(self) -> None:
        document = self._three_node_document()

        normalized = normalize_path_document(document)

        by_id = {node["id"]: node for node in normalized["nodes"]}
        self.assertEqual(by_id["0"]["x"], 40)
        self.assertEqual(by_id["0"]["y"], 40)
        self.assertEqual(by_id["1"]["x"], 260)
        self.assertEqual(by_id["2"]["x"], 480)


class AngleInputPreservationTests(unittest.TestCase):
    def test_normalize_preserves_raw_advanced_scan_angles(self) -> None:
        document = {
            "points": [
                {"id": "p0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "p1", "name": "scan", "axes": {"J1": 1, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
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
                    "point_id": "p1",
                    "prev_node_id": "0",
                    "turntable": {"start_angle": 288.0, "end_angle": 360.0, "scan_count": 1},
                },
            ],
            "safe_route_ids": ["p0", "p1"],
            "safe_routes": [[True, True], [True, True]],
        }

        normalized = normalize_path_document(document)

        scan = normalized["nodes"][1]
        self.assertEqual(scan["turntable"]["start_angle"], 288.0)
        self.assertEqual(scan["turntable"]["end_angle"], 360.0)
        self.assertNotEqual(scan["turntable"]["start_angle"], 2.0004)


class MoveAfterTouchUpTests(unittest.TestCase):
    @patch("app.pipeline.service.axis_receiver_service")
    @patch("app.pipeline.service.try_connect_turntable")
    @patch("app.pipeline.service.try_connect_robot_path")
    @patch("app.pipeline.service.read_current_axes_from_snapshot")
    @patch("app.pipeline.service.get_runtime_settings")
    def test_move_skips_stale_start_hop_after_touch_up(
        self,
        get_runtime_settings: MagicMock,
        read_axes: MagicMock,
        try_connect_robot: MagicMock,
        try_connect_turntable: MagicMock,
        axis_service: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        new_axes = [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        axis_service.get_snapshot.return_value = {
            "connected": True,
            "axes_available": True,
            "a1": new_axes[0],
            "a2": new_axes[1],
            "a3": new_axes[2],
            "a4": new_axes[3],
            "a5": new_axes[4],
            "a6": new_axes[5],
        }
        read_axes.return_value = new_axes

        document = {
            "points": [
                {"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
                {"id": "1", "name": "scan", "axes": {"J1": 10, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}},
            ],
            "nodes": [
                {
                    "id": "0",
                    "type": "home",
                    "point_id": "0",
                    "next_node_id": "1",
                    "turntable": {"angle": 0.0},
                },
                {
                    "id": "1",
                    "type": "basic_scan",
                    "point_id": "1",
                    "prev_node_id": "0",
                    "turntable": {"angle": 90.0},
                },
            ],
            "safe_route_ids": ["0", "1"],
            "safe_routes": [[True, True], [True, True]],
        }

        service = PipelineService()
        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.jog_to_target = MagicMock()
        service._ensure_jog_robot_client = MagicMock(return_value=robot)

        result = service.move_to_path_position(0, document, node_id="0")

        self.assertGreaterEqual(result["hops_executed"], 1)
        first_call_axes = robot.jog_to_target.call_args_list[0].args[0]
        self.assertEqual(first_call_axes[0], 0.0)
        self.assertNotEqual(first_call_axes[0], 10.0)


if __name__ == "__main__":
    unittest.main()
