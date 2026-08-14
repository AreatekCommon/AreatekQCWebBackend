from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from app.eki.constants import PATH_STATUS_IDLE, PATH_STATUS_MOVING
from app.eki.path_client import KukaEkiPathClient


class PathClientMotionCancelTests(unittest.TestCase):
    def _client(self) -> KukaEkiPathClient:
        return KukaEkiPathClient(robot_ip="127.0.0.1")

    def test_cancel_motion_clears_pending_execute_and_sets_event(self) -> None:
        client = self._client()
        client.pending_execute = True
        client._turntable_ready_for_execute = True

        client.cancel_motion()

        self.assertFalse(client.pending_execute)
        self.assertFalse(client._turntable_ready_for_execute)
        self.assertTrue(client._motion_cancel_event.is_set())

    def test_clear_motion_cancel_resets_event(self) -> None:
        client = self._client()
        client.cancel_motion()
        client.clear_motion_cancel()
        self.assertFalse(client._motion_cancel_event.is_set())

    def test_wait_until_status_returns_false_when_cancelled(self) -> None:
        client = self._client()
        client.robot_status = PATH_STATUS_MOVING

        with patch("app.eki.path_client.time.sleep"):
            client.cancel_motion()
            result = client.wait_until_status(PATH_STATUS_IDLE)

        self.assertFalse(result)

    def test_wait_until_status_returns_false_when_abort_event_set(self) -> None:
        client = self._client()
        client.robot_status = PATH_STATUS_MOVING
        abort_event = threading.Event()
        abort_event.set()

        with patch("app.eki.path_client.time.sleep"):
            result = client.wait_until_status(PATH_STATUS_IDLE, abort_event=abort_event)

        self.assertFalse(result)

    def test_wait_motion_done_timed_aborts_while_waiting_for_moving(self) -> None:
        client = self._client()
        client.robot_status = PATH_STATUS_IDLE

        with patch("app.eki.path_client.time.sleep"):
            client.cancel_motion()
            success, _elapsed = client.wait_motion_done_timed()

        self.assertFalse(success)

    def test_jog_to_target_raises_when_aborted_before_idle(self) -> None:
        client = self._client()
        abort_event = threading.Event()
        abort_event.set()

        with self.assertRaisesRegex(RuntimeError, "Cycle aborted"):
            client.jog_to_target([0.0] * 6, 0.0, abort_event=abort_event)


if __name__ == "__main__":
    unittest.main()
