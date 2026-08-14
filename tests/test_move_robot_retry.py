import threading
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from app.eki.constants import PATH_STATUS_IDLE
from app.eki.messages import TrajectoryPoint
from app.models.pipeline_settings import PipelineSettings
from app.models.runtime_settings import RuntimeSettings
from app.pipeline.config import POSITION_RESEND_MAX_ATTEMPTS
from app.pipeline.cycle import move_robot_to_point
from app.pipeline.service import PipelineService
from app.scanner.service import ScannerService


def make_point(index: int = 0) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid="",
        point_type="scan",
        comment="test",
        speed=50.0,
        acceleration=50.0,
        a7=0.0,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[0.0] * 6,
    )


def make_runtime_settings(delay_sec: float = 0.5) -> RuntimeSettings:
    return RuntimeSettings(
        pipeline=PipelineSettings(
            error_turntable_delay_sec=delay_sec,
        ),
    )


class MoveRobotRetryTests(unittest.TestCase):
    def test_slow_motion_does_not_resend(self) -> None:
        delay = 0.5
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, delay + 0.1)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle.time.sleep"):
            position_resent = move_robot_to_point(robot, 2, make_point(2))

        self.assertFalse(position_resent)
        self.assertEqual(robot.trigger_point_by_list_index.call_count, 1)

    def test_fast_motion_retries_until_slow(self) -> None:
        delay = 0.5
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        fast = delay - 0.1
        slow = delay + 0.1
        robot.wait_motion_done_timed.side_effect = [
            (True, fast),
            (True, fast),
            (True, slow),
        ]

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle.time.sleep"):
            position_resent = move_robot_to_point(robot, 3, make_point(3))

        self.assertTrue(position_resent)
        self.assertEqual(robot.trigger_point_by_list_index.call_count, 3)

    def test_fast_motion_waits_before_resend(self) -> None:
        delay = 0.5
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.is_idle.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        fast = delay - 0.1
        slow = delay + 0.1
        robot.wait_motion_done_timed.side_effect = [(True, fast), (True, slow)]

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle._sleep_interruptible") as sleep_mock:
            position_resent = move_robot_to_point(robot, 3, make_point(3))

        self.assertTrue(position_resent)
        self.assertEqual(robot.trigger_point_by_list_index.call_count, 2)
        sleep_mock.assert_called_once()
        self.assertAlmostEqual(sleep_mock.call_args[0][0], 0.1, places=3)

    def test_fast_motion_retries_max_attempts(self) -> None:
        delay = 0.5
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.is_idle.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        fast = delay - 0.05
        robot.wait_motion_done_timed.return_value = (True, fast)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle._sleep_interruptible"):
            position_resent = move_robot_to_point(robot, 4, make_point(4))

        self.assertTrue(position_resent)
        self.assertEqual(
            robot.trigger_point_by_list_index.call_count,
            POSITION_RESEND_MAX_ATTEMPTS,
        )

    def test_custom_delay_from_settings(self) -> None:
        delay = 1.0
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, delay + 0.05)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle.time.sleep"):
            position_resent = move_robot_to_point(robot, 7, make_point(7))

        self.assertFalse(position_resent)
        self.assertEqual(robot.trigger_point_by_list_index.call_count, 1)

    def test_motion_failure_raises(self) -> None:
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (False, 0.1)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(),
        ), patch("app.pipeline.cycle.time.sleep"):
            with self.assertRaises(RuntimeError):
                move_robot_to_point(robot, 5, make_point(5))

    def test_abort_during_motion_wait_raises(self) -> None:
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        abort_event = threading.Event()
        robot.wait_motion_done_timed.return_value = (False, 0.1)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(),
        ), patch("app.pipeline.cycle.time.sleep"):
            abort_event.set()
            with self.assertRaisesRegex(RuntimeError, "Cycle aborted"):
                move_robot_to_point(robot, 6, make_point(6), abort_event=abort_event)

    def test_same_pose_skips_delay_retry(self) -> None:
        delay = 0.5
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, delay - 0.2)
        previous = make_point(1)
        current = make_point(2)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle.time.sleep"):
            position_resent = move_robot_to_point(
                robot,
                2,
                current,
                previous_point=previous,
            )

        self.assertFalse(position_resent)
        self.assertEqual(robot.trigger_point_by_list_index.call_count, 1)

    def test_different_turntable_still_retries(self) -> None:
        delay = 0.5
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.wait_until_status.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        fast = delay - 0.1
        slow = delay + 0.1
        robot.wait_motion_done_timed.side_effect = [(True, fast), (True, slow)]
        previous = TrajectoryPoint(
            index=1,
            guid="",
            point_type="scan",
            comment="test",
            speed=50.0,
            acceleration=50.0,
            a7=0.0,
            a7_speed=50.0,
            a7_acceleration=50.0,
            axes=[0.0] * 6,
        )
        current = TrajectoryPoint(
            index=2,
            guid="",
            point_type="scan",
            comment="test",
            speed=50.0,
            acceleration=50.0,
            a7=90.0,
            a7_speed=50.0,
            a7_acceleration=50.0,
            axes=[0.0] * 6,
        )

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
            return_value=make_runtime_settings(delay),
        ), patch("app.pipeline.cycle.time.sleep"):
            position_resent = move_robot_to_point(
                robot,
                2,
                current,
                previous_point=previous,
            )

        self.assertTrue(position_resent)
        self.assertEqual(robot.trigger_point_by_list_index.call_count, 2)


class PipelineStopTests(unittest.TestCase):
    def test_stop_cycle_calls_cancel_motion(self) -> None:
        service = PipelineService()
        robot = MagicMock()
        service._state = "running"
        service._robot = robot
        service._worker_thread = None

        service.stop_cycle()

        robot.cancel_motion.assert_called_once()
        self.assertTrue(service._abort_event.is_set())


class PipelineResendMarkerTests(unittest.TestCase):
    def test_resend_indices_cleared_on_new_cycle_start(self) -> None:
        service = PipelineService()
        service._position_resend_step_indices = {1, 3, 5}
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        scan_point = make_point(0)
        end_point = TrajectoryPoint(
            index=1,
            guid="",
            point_type="end",
            comment="end",
            speed=50.0,
            acceleration=50.0,
            a7=0.0,
            a7_speed=50.0,
            a7_acceleration=50.0,
            axes=[0.0] * 6,
        )
        snapshot = MagicMock()
        snapshot.points = [scan_point, end_point]

        with patch.object(service, "_validate_ready_to_start"), patch.object(
            service,
            "_preflight_startup_travel",
        ), patch.object(
            service,
            "_create_project",
        ), patch.object(service, "_set_state"), patch(
            "app.pipeline.service.trajectory_service.get_snapshot",
            return_value=snapshot,
        ), patch(
            "app.pipeline.service.threading.Thread",
        ) as thread_cls:
            service._run_lock = mock_lock
            thread_cls.return_value = MagicMock()
            service.start_cycle()

        self.assertEqual(service._position_resend_step_indices, set())

    def test_resend_indices_kept_on_continue(self) -> None:
        service = PipelineService()
        service._position_resend_step_indices = {2, 4}
        service._project_name = "scan_test"
        service._current_step_index = 2
        service._scan_count = 1
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True

        with patch.object(service, "_can_resume", return_value=True), patch.object(
            service,
            "_validate_ready_to_start",
        ), patch.object(service, "_set_state"), patch(
            "app.pipeline.service.scanner_service.ensure_project",
        ), patch(
            "app.pipeline.service.threading.Thread",
        ) as thread_cls:
            service._run_lock = mock_lock
            thread_cls.return_value = MagicMock()
            service.continue_cycle()

        self.assertEqual(service._position_resend_step_indices, {2, 4})

    def test_get_status_includes_sorted_resend_indices(self) -> None:
        service = PipelineService()
        service._position_resend_step_indices = {5, 1, 3}

        snapshot = MagicMock()
        snapshot.load_error = None
        snapshot.points = [make_point()]

        with patch(
            "app.pipeline.service.trajectory_service.get_snapshot",
            return_value=snapshot,
        ), patch.object(
            ScannerService,
            "is_connected",
            new_callable=PropertyMock,
            return_value=True,
        ), patch.object(service, "_is_robot_path_connected", return_value=True), patch.object(
            service,
            "_is_turntable_connected",
            return_value=True,
        ), patch.object(service, "_can_resume_locked", return_value=False):
            status = service.get_status()

        self.assertEqual(status.position_resend_step_indices, [1, 3, 5])


if __name__ == "__main__":
    unittest.main()
