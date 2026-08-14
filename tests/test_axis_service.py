from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock

from app.axis.models import AxisSample
from app.axis.service import AxisReceiverService, _axes_available_from_snapshot
from app.trajectory.routing import read_current_axes_from_snapshot


class AxesAvailableTests(unittest.TestCase):
    def test_axes_available_when_all_joints_present(self) -> None:
        snapshot = {
            "a1": 1.0,
            "a2": 2.0,
            "a3": 3.0,
            "a4": 4.0,
            "a5": 5.0,
            "a6": 6.0,
        }
        self.assertTrue(_axes_available_from_snapshot(snapshot))

    def test_axes_not_available_when_joint_missing(self) -> None:
        snapshot = {"a1": 1.0, "a2": 2.0}
        self.assertFalse(_axes_available_from_snapshot(snapshot))

    def test_read_current_axes_without_connected(self) -> None:
        snapshot = {
            "connected": False,
            "a1": 10.0,
            "a2": 20.0,
            "a3": 30.0,
            "a4": 40.0,
            "a5": 50.0,
            "a6": 60.0,
        }
        axes = read_current_axes_from_snapshot(snapshot)
        self.assertEqual(axes, [10.0, 20.0, 30.0, 40.0, 50.0, 60.0])


class AxisReceiverServiceForwardTests(unittest.TestCase):
    def test_publish_does_not_block_on_forward_failure(self) -> None:
        service = AxisReceiverService()
        forwarder = MagicMock()
        forwarder.send_axis_sample_with_reconnect.side_effect = ConnectionError("CoreControl down")
        service._forwarder = forwarder
        service._forward_thread = threading.Thread(
            target=service._forward_worker_loop,
            name="AxisForwardWorkerTest",
            daemon=True,
        )
        service._forward_thread.start()

        try:
            samples = [
                AxisSample(1.0 + index, 2.0, 3.0, 4.0, 5.0, 6.0, timestamp_ms=1000 + index)
                for index in range(5)
            ]
            start = time.monotonic()
            for sample in samples:
                service.publish(sample)
            elapsed = time.monotonic() - start

            self.assertLess(elapsed, 0.5)

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if forwarder.send_axis_sample_with_reconnect.call_count >= 1:
                    break
                time.sleep(0.05)

            snapshot = service.get_snapshot()
            self.assertEqual(snapshot["a1"], 5.0)
            self.assertTrue(snapshot["axes_available"])
            self.assertFalse(snapshot["forward_connected"])
            self.assertIn("CoreControl down", snapshot.get("forward_last_error") or "")
            self.assertGreaterEqual(forwarder.send_axis_sample_with_reconnect.call_count, 1)
        finally:
            service._forward_stop_event.set()
            if service._forward_thread is not None:
                service._forward_thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
