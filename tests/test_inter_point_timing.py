import unittest
from unittest.mock import MagicMock, patch

from app.eki.constants import PATH_STATUS_IDLE
from app.eki.messages import TrajectoryPoint
from app.pipeline.cycle import (
    PendingGapTimer,
    _clear_pending_gap_timer,
    _log_pending_gap_before_move,
    move_robot_to_point,
)
import app.pipeline.cycle as cycle_module


def make_point(index: int = 0, *, point_type: str = "scan") -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid="",
        point_type=point_type,
        comment="test",
        speed=50.0,
        acceleration=50.0,
        a7=0.0,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[0.0] * 6,
    )


class InterPointGapTimerTests(unittest.TestCase):
    def tearDown(self) -> None:
        _clear_pending_gap_timer()

    def test_transition_gap_logged_on_next_move(self) -> None:
        cycle_module._pending_gap_timer = PendingGapTimer(
            kind="transition",
            started_at=100.0,
            from_list_index=3,
        )

        with patch("app.pipeline.cycle.time.monotonic", return_value=100.42), patch(
            "app.pipeline.cycle.logger"
        ) as logger_mock:
            _log_pending_gap_before_move(4)

        logger_mock.info.assert_called_once()
        args = logger_mock.info.call_args[0]
        self.assertEqual(args[0], "Transition idle before next move: %.2fs (list %s → %s)")
        self.assertAlmostEqual(args[1], 0.42, places=2)
        self.assertEqual(args[2], 3)
        self.assertEqual(args[3], 4)

    def test_scan_gap_logged_on_next_move(self) -> None:
        cycle_module._pending_gap_timer = PendingGapTimer(
            kind="scan",
            started_at=200.0,
            from_list_index=5,
        )

        with patch("app.pipeline.cycle.time.monotonic", return_value=200.38), patch(
            "app.pipeline.cycle.logger"
        ) as logger_mock:
            _log_pending_gap_before_move(6)

        logger_mock.info.assert_called_once()
        args = logger_mock.info.call_args[0]
        self.assertEqual(args[0], "Post-scan idle before next move: %.2fs (list %s → %s)")
        self.assertAlmostEqual(args[1], 0.38, places=2)
        self.assertEqual(args[2], 5)
        self.assertEqual(args[3], 6)

    def test_move_robot_to_point_logs_pending_transition_gap(self) -> None:
        cycle_module._pending_gap_timer = PendingGapTimer(
            kind="transition",
            started_at=50.0,
            from_list_index=2,
        )
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.is_idle.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
        ) as settings_mock, patch("app.pipeline.cycle.time.monotonic", return_value=50.25), patch(
            "app.pipeline.cycle.logger"
        ) as logger_mock, patch("app.pipeline.cycle._sleep_interruptible"):
            settings_mock.return_value.pipeline.error_turntable_delay_sec = 0.5
            move_robot_to_point(robot, 3, make_point(3, point_type="transition"))

        gap_logs = [
            call
            for call in logger_mock.info.call_args_list
            if call.args and "idle before next move" in call.args[0]
        ]
        self.assertEqual(len(gap_logs), 1)
        self.assertIn("Transition idle", gap_logs[0].args[0])


class SkipIdleBeforeTriggerTests(unittest.TestCase):
    def test_skips_wait_when_robot_already_idle(self) -> None:
        robot = MagicMock()
        robot.STATUS_IDLE = PATH_STATUS_IDLE
        robot.is_idle.return_value = True
        robot.trigger_point_by_list_index.return_value = True
        robot.wait_motion_done_timed.return_value = (True, 1.0)

        with patch(
            "app.core.runtime_settings_store.get_runtime_settings",
        ) as settings_mock, patch("app.pipeline.cycle._sleep_interruptible"):
            settings_mock.return_value.pipeline.error_turntable_delay_sec = 0.5
            move_robot_to_point(robot, 1, make_point(1))

        robot.wait_until_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
