import threading
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from app.eki.constants import PATH_STATUS_IDLE
from app.eki.messages import TrajectoryPoint
from app.models.pipeline_settings import PipelineSettings
from app.models.runtime_settings import RuntimeSettings
from app.pipeline.cycle import CycleRunResult, run_cycle


def make_point(
    index: int,
    point_type: str,
    *,
    a7: float = 0.0,
    axes: list[float] | None = None,
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
        axes=axes if axes is not None else [float(index)] * 6,
    )


def make_sample_trajectory() -> list[TrajectoryPoint]:
    return [
        make_point(0, "home"),
        make_point(1, "scan", a7=0.0),
        make_point(2, "scan", a7=90.0),
        make_point(3, "end"),
    ]


class CycleMeshTimingTests(unittest.TestCase):
    def test_mesh_starts_after_last_scan_before_end_motion(self) -> None:
        points = make_sample_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)

        mesh_started = threading.Event()
        end_motion_started = threading.Event()
        call_order: list[str] = []

        def generate_mesh_and_save(_project_name: str) -> None:
            call_order.append("mesh")
            mesh_started.set()

        def wait_motion_done(*_args, **_kwargs) -> bool:
            call_order.append("end_motion")
            end_motion_started.set()
            mesh_started.wait(timeout=1.0)
            return True

        robot.wait_motion_done.side_effect = wait_motion_done

        scanner = MagicMock()
        scanner.run_scan.return_value = None
        scanner.generate_mesh_and_save.side_effect = generate_mesh_and_save

        with patch("app.pipeline.cycle._sleep_interruptible"), patch(
            "app.pipeline.cycle._finalize_mesh_worker",
            return_value=None,
        ):
            result = run_cycle(robot, scanner, "scan_test")

        self.assertEqual(result.project_name, "scan_test")
        scanner.generate_mesh_and_save.assert_called_once_with("scan_test")
        self.assertEqual(call_order[0], "mesh")
        self.assertEqual(call_order[1], "end_motion")

    def test_resume_past_last_scan_starts_mesh_at_cycle_start(self) -> None:
        points = make_sample_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.return_value = None

        with patch("app.pipeline.cycle._sleep_interruptible"), patch(
            "app.pipeline.cycle._finalize_mesh_worker",
            return_value=None,
        ):
            run_cycle(
                robot,
                scanner,
                "scan_test",
                start_list_index=3,
                initial_scan_count=2,
            )

        scanner.generate_mesh_and_save.assert_called_once_with("scan_test")
        scanner.run_scan.assert_not_called()

    def test_end_joins_existing_mesh_worker_without_duplicate_start(self) -> None:
        points = make_sample_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.return_value = None

        with patch("app.pipeline.cycle._sleep_interruptible"), patch(
            "app.pipeline.cycle._start_mesh_worker",
        ) as start_mesh_worker, patch(
            "app.pipeline.cycle._finalize_mesh_worker",
            return_value=None,
        ):
            existing_worker = MagicMock()
            start_mesh_worker.return_value = existing_worker
            run_cycle(robot, scanner, "scan_test")

        self.assertEqual(start_mesh_worker.call_count, 1)

    def test_stop_after_last_scan_skips_mesh_and_end(self) -> None:
        points = make_sample_trajectory()
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)

        scanner = MagicMock()
        scanner.run_scan.return_value = None
        before = datetime.now(UTC)

        with patch("app.pipeline.cycle._sleep_interruptible"):
            result = run_cycle(
                robot,
                scanner,
                "scan_test",
                stop_after_last_scan=True,
            )

        after = datetime.now(UTC)

        self.assertEqual(result.project_name, "scan_test")
        self.assertIsNotNone(result.last_position_reached_at)
        assert result.last_position_reached_at is not None
        self.assertGreaterEqual(result.last_position_reached_at, before)
        self.assertLessEqual(result.last_position_reached_at, after)
        scanner.generate_mesh_and_save.assert_not_called()
        robot.wait_motion_done.assert_not_called()
        self.assertEqual(scanner.run_scan.call_count, 2)

    def test_stop_after_last_scan_on_resume_past_last_scan(self) -> None:
        points = make_sample_trajectory()
        robot = MagicMock()
        robot.points = points

        scanner = MagicMock()

        with patch("app.pipeline.cycle._sleep_interruptible"):
            result = run_cycle(
                robot,
                scanner,
                "scan_test",
                start_list_index=3,
                initial_scan_count=2,
                stop_after_last_scan=True,
            )

        self.assertEqual(result.project_name, "scan_test")
        scanner.generate_mesh_and_save.assert_not_called()
        scanner.run_scan.assert_not_called()


class CycleHomePoseTests(unittest.TestCase):
    def test_home_then_same_pose_skips_delay_retry(self) -> None:
        shared_axes = [-58.48, -69.60, 50.84, 62.98, -49.68, -82.71]
        points = [
            make_point(0, "home", a7=0.0, axes=shared_axes),
            make_point(1, "scan", a7=0.0, axes=shared_axes),
            TrajectoryPoint(
                index=2,
                guid="2",
                point_type="end",
                comment="end",
                speed=50.0,
                acceleration=50.0,
                a7=0.0,
                a7_speed=50.0,
                a7_acceleration=50.0,
                axes=shared_axes,
            ),
        ]
        robot = MagicMock()
        robot.points = points
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 0.1)
        robot.wait_motion_done.return_value = True

        scanner = MagicMock()
        scanner.run_scan.return_value = None
        settings = RuntimeSettings(pipeline=PipelineSettings(error_turntable_delay_sec=0.5))

        trigger_counts: dict[int, int] = {}

        def track_trigger(list_index: int) -> bool:
            trigger_counts[list_index] = trigger_counts.get(list_index, 0) + 1
            return True

        robot.trigger_point_by_list_index.side_effect = track_trigger

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=settings,
        ), patch("app.pipeline.cycle._sleep_interruptible"), patch(
            "app.pipeline.cycle._finalize_mesh_worker",
            return_value=None,
        ):
            run_cycle(robot, scanner, "scan_test")

        self.assertEqual(trigger_counts.get(1, 0), 1)


if __name__ == "__main__":
    unittest.main()
