from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.eki.constants import PATH_STATUS_IDLE
from app.eki.messages import TrajectoryPoint
from app.pipeline.cycle import CycleRunResult, _finalize_mesh_worker, _start_mesh_worker, run_cycle


def make_point(index: int, point_type: str) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid=str(index),
        point_type=point_type,
        comment=point_type,
        speed=50.0,
        acceleration=50.0,
        a7=0.0,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[float(index)] * 6,
    )


class CycleExportTimingTests(unittest.TestCase):
    def test_mesh_worker_records_export_timestamp(self) -> None:
        mesh_timing: dict[str, datetime] = {}
        worker_error: dict[str, Exception] = {}
        scanner = MagicMock()
        export_finished_at = datetime(2026, 8, 4, 10, 18, 5, tzinfo=UTC)

        with patch("app.pipeline.cycle.datetime") as mock_datetime:
            mock_datetime.now.return_value = export_finished_at
            worker = _start_mesh_worker(scanner, "scan_test", worker_error, mesh_timing)
            worker.join(timeout=2.0)

        scanner.generate_mesh_and_save.assert_called_once_with("scan_test")
        self.assertEqual(mesh_timing["finished_at"], export_finished_at)
        self.assertNotIn("error", worker_error)

    def test_run_cycle_returns_mesh_export_timestamp(self) -> None:
        points = [
            make_point(0, "home"),
            make_point(1, "scan"),
            make_point(2, "end"),
        ]
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.return_value = None
        with patch("app.pipeline.cycle._sleep_interruptible"):
            result = run_cycle(robot, scanner, "scan_test")

        self.assertIsInstance(result, CycleRunResult)
        self.assertEqual(result.project_name, "scan_test")
        self.assertIsNotNone(result.mesh_export_finished_at)
        self.assertIsInstance(result.mesh_export_finished_at, datetime)

    def test_stop_after_last_scan_has_no_export_timestamp(self) -> None:
        points = [
            make_point(0, "home"),
            make_point(1, "scan"),
            make_point(2, "end"),
        ]
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)

        scanner = MagicMock()
        scanner.run_scan.return_value = None

        with patch("app.pipeline.cycle._sleep_interruptible"):
            result = run_cycle(
                robot,
                scanner,
                "scan_test",
                stop_after_last_scan=True,
            )

        self.assertEqual(result.project_name, "scan_test")
        self.assertIsNone(result.mesh_export_finished_at)
        scanner.generate_mesh_and_save.assert_not_called()

    def test_finalize_mesh_worker_waits_for_slow_export(self) -> None:
        mesh_timing: dict[str, datetime] = {}
        worker_error: dict[str, Exception] = {}
        scanner = MagicMock()
        export_finished_at = datetime(2026, 8, 4, 10, 18, 5, tzinfo=UTC)

        def slow_export(_project_name: str) -> None:
            time.sleep(0.3)

        scanner.generate_mesh_and_save.side_effect = slow_export

        with patch("app.pipeline.cycle.datetime") as mock_datetime:
            mock_datetime.now.return_value = export_finished_at
            worker = _start_mesh_worker(scanner, "scan_test", worker_error, mesh_timing)
            _finalize_mesh_worker(worker, worker_error)

        self.assertEqual(mesh_timing["finished_at"], export_finished_at)
        self.assertNotIn("error", worker_error)

    def test_run_cycle_waits_for_slow_mesh_export(self) -> None:
        points = [
            make_point(0, "home"),
            make_point(1, "scan"),
            make_point(2, "end"),
        ]
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.return_value = None

        def slow_mesh(_project_name: str) -> None:
            time.sleep(0.3)

        scanner.generate_mesh_and_save.side_effect = slow_mesh

        with patch("app.pipeline.cycle._sleep_interruptible"):
            result = run_cycle(robot, scanner, "scan_test")

        self.assertIsNotNone(result.mesh_export_finished_at)
        self.assertIsInstance(result.mesh_export_finished_at, datetime)


if __name__ == "__main__":
    unittest.main()
