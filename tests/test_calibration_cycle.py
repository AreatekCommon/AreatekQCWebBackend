from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from app.eki.constants import PATH_STATUS_IDLE
from app.eki.messages import TrajectoryPoint
from app.pipeline.calibration_cycle import run_calibration_cycle
from app.pipeline.service import PipelineService
from app.trajectory.service import validate_calibration_document


def make_point(
    index: int,
    point_type: str,
    *,
    a7: float = 0.0,
) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid=str(index),
        point_type=point_type,
        comment=point_type,
        speed=50.0,
        acceleration=50.0,
        a7=a7,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[float(index)] * 6,
    )


def make_calibration_trajectory() -> list[TrajectoryPoint]:
    return [
        make_point(0, "home"),
        make_point(1, "scan"),
        make_point(2, "end"),
    ]


def make_valid_calibration_document() -> dict:
    return {
        "points": [
            {
                "id": "0",
                "name": "cal",
                "axes": {
                    "J1": 0.0,
                    "J2": 0.0,
                    "J3": 0.0,
                    "J4": 0.0,
                    "J5": 0.0,
                    "J6": 0.0,
                },
            }
        ],
        "nodes": [
            {
                "id": "0",
                "type": "home",
                "point_id": "0",
                "next_node_id": "1",
                "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
                "motion": {"speed": 50.0, "acceleration": 50.0},
            },
            {
                "id": "1",
                "type": "basic_scan",
                "point_id": "0",
                "prev_node_id": "0",
                "next_node_id": "2",
                "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
                "motion": {"speed": 50.0, "acceleration": 50.0},
            },
            {
                "id": "2",
                "type": "end",
                "point_id": "0",
                "prev_node_id": "1",
                "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
                "motion": {"speed": 50.0, "acceleration": 50.0},
            },
        ],
        "safe_route_ids": ["0"],
        "safe_routes": [[True]],
    }


class ValidateCalibrationDocumentTests(unittest.TestCase):
    def test_accepts_basic_scan_only_path(self) -> None:
        validate_calibration_document(make_valid_calibration_document())

    def test_rejects_advanced_scan_nodes(self) -> None:
        document = make_valid_calibration_document()
        document["nodes"][1]["type"] = "advanced_scan"
        document["nodes"][1]["turntable"] = {
            "start_angle": 0.0,
            "end_angle": 90.0,
            "scan_count": 2,
            "speed": 50.0,
            "acceleration": 50.0,
        }

        with self.assertRaises(ValueError) as ctx:
            validate_calibration_document(document)

        self.assertIn("basic_scan", str(ctx.exception))

    def test_rejects_missing_end_point(self) -> None:
        document = make_valid_calibration_document()
        document["nodes"] = document["nodes"][:2]

        with self.assertRaises(ValueError) as ctx:
            validate_calibration_document(document)

        self.assertIn("end point", str(ctx.exception).lower())


class RunCalibrationCycleTests(unittest.TestCase):
    def test_capture_called_for_scan_point(self) -> None:
        points = make_calibration_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()

        with patch("app.pipeline.calibration_cycle.move_robot_to_point", return_value=False):
            run_calibration_cycle(robot, scanner)

        scanner.capture_calibration.assert_called_once_with(1, 1, "scan")

    def test_abort_during_cycle(self) -> None:
        points = make_calibration_trajectory()
        robot = MagicMock()
        robot.points = points
        abort_event = threading.Event()
        abort_event.set()

        scanner = MagicMock()

        with self.assertRaises(RuntimeError) as ctx:
            run_calibration_cycle(robot, scanner, abort_event=abort_event)

        self.assertEqual(str(ctx.exception), "Cycle aborted")
        scanner.capture_calibration.assert_not_called()


class StartCalibrationCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = PipelineService()

    @patch("app.pipeline.service.threading.Thread")
    @patch("app.pipeline.service.trajectory_service")
    @patch("app.pipeline.service.scanner_service")
    @patch("app.pipeline.service.app_state")
    def test_start_calibration_loads_calibration_file(
        self,
        app_state: MagicMock,
        scanner_service: MagicMock,
        trajectory_service: MagicMock,
        thread_cls: MagicMock,
    ) -> None:
        document = make_valid_calibration_document()
        points = make_calibration_trajectory()
        snapshot = MagicMock(
            load_error=None,
            points=points,
            point_count=len(points),
        )

        app_state.current_position = {"connected": True}
        scanner_service.is_connecting.return_value = False
        scanner_service.is_restarting.return_value = False
        scanner_service.is_connected = True
        trajectory_service.read_named_document.return_value = document
        trajectory_service.is_calibration_trajectory_ready.return_value = True
        trajectory_service.load_named_file.return_value = snapshot
        trajectory_service.get_snapshot.return_value = snapshot

        self.pipeline._robot = MagicMock()
        self.pipeline._robot.connected = True
        self.pipeline._robot.turn_connected = True
        self.pipeline._robot.STATUS_IDLE = PATH_STATUS_IDLE
        self.pipeline._robot.lock = threading.Lock()
        self.pipeline._robot.robot_status = self.pipeline._robot.STATUS_IDLE

        with patch.object(self.pipeline, "_preflight_startup_travel"):
            self.pipeline.start_calibration_cycle()

        trajectory_service.load_named_file.assert_called_once_with("calibration.json")
        thread_cls.assert_called_once()
        self.assertEqual(self.pipeline._cycle_mode, "calibration")

    @patch("app.pipeline.service.scanner_service")
    def test_start_calibration_blocked_while_running(
        self,
        scanner_service: MagicMock,
    ) -> None:
        self.pipeline._run_lock.acquire()
        try:
            with self.assertRaises(RuntimeError) as ctx:
                self.pipeline.start_calibration_cycle()
            self.assertIn("already running", str(ctx.exception).lower())
        finally:
            self.pipeline._run_lock.release()


if __name__ == "__main__":
    unittest.main()
