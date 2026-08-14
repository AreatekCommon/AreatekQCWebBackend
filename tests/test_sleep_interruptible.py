from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from app.eki.path_client import KukaEkiPathClient
from app.pipeline.cycle import _sleep_interruptible


class CycleSleepInterruptibleTests(unittest.TestCase):
    def test_does_not_sleep_negative_when_deadline_already_passed(self) -> None:
        with patch("app.pipeline.cycle.time.monotonic", side_effect=[0.0, 2.0]), patch(
            "app.pipeline.cycle.time.sleep",
        ) as sleep_mock:
            _sleep_interruptible(1.0)

        sleep_mock.assert_not_called()

    def test_does_not_raise_when_monotonic_crosses_deadline_between_iterations(self) -> None:
        with patch(
            "app.pipeline.cycle.time.monotonic",
            side_effect=[0.0, 0.99, 1.01],
        ), patch("app.pipeline.cycle.time.sleep") as sleep_mock:
            _sleep_interruptible(1.0)

        sleep_mock.assert_called_once()
        self.assertAlmostEqual(sleep_mock.call_args[0][0], 0.01, places=5)

    def test_abort_during_sleep_raises(self) -> None:
        abort_event = threading.Event()
        abort_event.set()

        with self.assertRaises(RuntimeError) as ctx:
            _sleep_interruptible(1.0, abort_event)

        self.assertEqual(str(ctx.exception), "Cycle aborted")


class PathClientSleepInterruptibleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = KukaEkiPathClient(robot_ip="127.0.0.1")

    def test_does_not_sleep_negative_when_deadline_already_passed(self) -> None:
        with patch("app.eki.path_client.time.monotonic", side_effect=[0.0, 2.0]), patch(
            "app.eki.path_client.time.sleep",
        ) as sleep_mock:
            self.client._sleep_interruptible(1.0)

        sleep_mock.assert_not_called()

    def test_does_not_raise_when_monotonic_crosses_deadline_between_iterations(self) -> None:
        with patch(
            "app.eki.path_client.time.monotonic",
            side_effect=[0.0, 0.99, 1.01],
        ), patch("app.eki.path_client.time.sleep") as sleep_mock:
            self.client._sleep_interruptible(1.0)

        sleep_mock.assert_called_once()
        self.assertAlmostEqual(sleep_mock.call_args[0][0], 0.01, places=5)


if __name__ == "__main__":
    unittest.main()
