import unittest
from unittest.mock import MagicMock, patch

from app.eki.messages import PathRobotStatus, TrajectoryPoint
from app.eki.path_client import KukaEkiPathClient


def make_client() -> KukaEkiPathClient:
    client = KukaEkiPathClient(robot_ip="127.0.0.1")
    client._logger = MagicMock()
    return client


def make_point(index: int = 0) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid=f"guid-{index}",
        point_type="scan",
        comment="scan",
        speed=50.0,
        acceleration=50.0,
        a7=0.0,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )


class ExecuteInPositionTimingTests(unittest.TestCase):
    def test_trigger_point_resets_execute_timing_state(self) -> None:
        client = make_client()
        client.points = [make_point()]
        client._execute_sent_at = 1.0
        client._execute_awaiting_idle = True

        client.trigger_point_by_list_index(0)

        self.assertIsNone(client._execute_sent_at)
        self.assertFalse(client._execute_awaiting_idle)

    def test_trigger_point_wakes_tx_loops(self) -> None:
        client = make_client()
        client.points = [make_point()]

        client.trigger_point_by_list_index(0)

        self.assertTrue(client._turn_tx_wake.is_set())
        self.assertTrue(client._robot_tx_wake.is_set())
        self.assertIsNotNone(client._dispatch_started_at)

    def test_turntable_ready_wakes_robot_tx(self) -> None:
        client = make_client()
        client.pending_execute = True
        client.current_target = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        client._robot_tx_wake.clear()

        with patch(
            "app.eki.path_client.get_runtime_settings",
        ) as settings_mock:
            settings_mock.return_value.turntable_wire_format = "decimal_2"
            client._mark_turntable_ready_if_pending(0.0, "decimal_2")

        self.assertTrue(client._turntable_ready_for_execute)
        self.assertTrue(client._robot_tx_wake.is_set())
        self.assertIsNotNone(client._turntable_ready_at)

    def test_move_to_target_resets_execute_timing_state(self) -> None:
        client = make_client()
        client._execute_sent_at = 1.0
        client._execute_awaiting_idle = True

        client.move_to_target([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 45.0)

        self.assertIsNone(client._execute_sent_at)
        self.assertFalse(client._execute_awaiting_idle)

    def test_first_execute_send_sets_sent_at(self) -> None:
        client = make_client()

        with patch("app.eki.path_client.time.monotonic", return_value=100.0):
            with client.lock:
                if client._execute_sent_at is None:
                    client._execute_sent_at = __import__("time").monotonic()

        self.assertEqual(client._execute_sent_at, 100.0)

        with patch("app.eki.path_client.time.monotonic", return_value=200.0):
            with client.lock:
                if client._execute_sent_at is None:
                    client._execute_sent_at = __import__("time").monotonic()

        self.assertEqual(client._execute_sent_at, 100.0)

    def test_moving_then_idle_logs_once(self) -> None:
        client = make_client()
        client._execute_sent_at = 10.0
        client.robot_status = client.STATUS_IDLE

        client._handle_robot_status(PathRobotStatus(status=client.STATUS_MOVING))

        with patch("app.eki.path_client.time.monotonic", return_value=12.345):
            client._handle_robot_status(PathRobotStatus(status=client.STATUS_IDLE))

        client._logger.info.assert_called_once()
        args, _ = client._logger.info.call_args
        self.assertEqual(args[0], "In-position response time: %.2f s")
        self.assertAlmostEqual(args[1], 2.345)

    def test_idle_before_moving_does_not_log(self) -> None:
        client = make_client()
        client._execute_sent_at = 10.0
        client.robot_status = client.STATUS_IDLE

        client._handle_robot_status(PathRobotStatus(status=client.STATUS_IDLE))

        client._logger.info.assert_not_called()
        self.assertFalse(client._execute_awaiting_idle)

    def test_second_idle_after_log_does_not_log_again(self) -> None:
        client = make_client()
        client._execute_sent_at = 10.0
        client.robot_status = client.STATUS_IDLE

        client._handle_robot_status(PathRobotStatus(status=client.STATUS_MOVING))

        with patch("app.eki.path_client.time.monotonic", return_value=11.0):
            client._handle_robot_status(PathRobotStatus(status=client.STATUS_IDLE))

        with patch("app.eki.path_client.time.monotonic", return_value=12.0):
            client._handle_robot_status(PathRobotStatus(status=client.STATUS_IDLE))

        client._logger.info.assert_called_once()

    def test_safe_close_clears_execute_state(self) -> None:
        client = make_client()
        client._execute_sent_at = 1.0
        client._execute_awaiting_idle = True
        client._safe_close()
        self.assertIsNone(client._execute_sent_at)
        self.assertFalse(client._execute_awaiting_idle)


if __name__ == "__main__":
    unittest.main()
