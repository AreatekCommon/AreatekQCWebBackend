import unittest
from unittest.mock import patch

from app.eki.messages import TrajectoryPoint
from app.eki.path_client import KukaEkiPathClient
from app.eki.turntable_units import turntable_wire_display_value
from app.models.runtime_settings import RuntimeSettings


def make_client() -> KukaEkiPathClient:
    client = KukaEkiPathClient(robot_ip="127.0.0.1")
    client.connected = True
    client.turn_connected = True
    client.robot_status = client.STATUS_IDLE
    return client


def make_point(a7: float = 45.0) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=0,
        guid="guid-0",
        point_type="scan",
        comment="scan",
        speed=50.0,
        acceleration=50.0,
        a7=a7,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[0.0] * 6,
    )


class PathClientExecuteGateTests(unittest.TestCase):
    def test_trigger_point_clears_turntable_ready(self) -> None:
        client = make_client()
        client.points = [make_point()]
        client._turntable_ready_for_execute = True

        client.trigger_point_by_list_index(0)

        self.assertFalse(client._turntable_ready_for_execute)

    def test_can_send_execute_false_when_pending_but_turntable_not_ready(self) -> None:
        client = make_client()
        client.pending_execute = True
        client._turntable_ready_for_execute = False

        self.assertFalse(client._can_send_execute())

    def test_can_send_execute_true_when_pending_and_turntable_ready(self) -> None:
        client = make_client()
        client.pending_execute = True
        client._turntable_ready_for_execute = True

        self.assertTrue(client._can_send_execute())

    def test_can_send_execute_false_when_moving(self) -> None:
        client = make_client()
        client.pending_execute = True
        client._turntable_ready_for_execute = True
        client.robot_status = client.STATUS_MOVING

        self.assertFalse(client._can_send_execute())

    def test_mark_turntable_ready_when_wire_angle_matches(self) -> None:
        client = make_client()
        client.current_target = [0.0] * 6 + [32.72727272727273]
        client.pending_execute = True
        settings = RuntimeSettings(turntable_wire_format="decimal_2")

        with patch("app.eki.path_client.get_runtime_settings", return_value=settings):
            wire_turn = turntable_wire_display_value(
                client.current_target[6],
                settings.turntable_wire_format,
            )
            client._mark_turntable_ready_if_pending(wire_turn, settings.turntable_wire_format)

        self.assertTrue(client._turntable_ready_for_execute)

    def test_mark_turntable_ready_ignored_when_not_pending(self) -> None:
        client = make_client()
        client.current_target = [0.0] * 6 + [45.0]
        client.pending_execute = False

        client._mark_turntable_ready_if_pending(45.0, "decimal_2")

        self.assertFalse(client._turntable_ready_for_execute)

    def test_safe_close_turn_clears_turntable_ready(self) -> None:
        client = make_client()
        client._turntable_ready_for_execute = True
        client._safe_close_turn()
        self.assertFalse(client._turntable_ready_for_execute)


if __name__ == "__main__":
    unittest.main()
