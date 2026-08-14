from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from app.axis.forwarder import CoreControlVisualForwarder
from app.axis.models import AxisSample, ForwardSettings


class AxisSampleMessageTests(unittest.TestCase):
    def test_to_core_control_visual_message_shape(self) -> None:
        sample = AxisSample(
            a1=1.0,
            a2=2.0,
            a3=3.0,
            a4=4.0,
            a5=5.0,
            a6=6.0,
            external_axis=30.0,
            timestamp_ms=1710000000123,
        )

        message = sample.to_core_control_visual_message()
        payload = json.loads(message)

        self.assertEqual(payload["Timestamp"], 1710000000123)
        self.assertEqual(
            payload["RobotAndExternalAxisJointValues"],
            [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 30.0],
        )
        self.assertTrue(message.endswith("\n"))


class CoreControlVisualForwarderTests(unittest.TestCase):
    def test_send_axis_sample_uses_json_line(self) -> None:
        settings = ForwardSettings(host="192.168.40.154", port=3400)
        forwarder = CoreControlVisualForwarder(settings)
        sample = AxisSample(
            a1=10.0,
            a2=20.0,
            a3=30.0,
            a4=40.0,
            a5=50.0,
            a6=60.0,
            external_axis=0.0,
            timestamp_ms=1234567890,
        )
        expected_payload = sample.to_core_control_visual_message().encode("utf-8")

        mock_socket = MagicMock()
        forwarder._socket = mock_socket

        forwarder.send_axis_sample(sample)

        mock_socket.sendall.assert_called_once_with(expected_payload)

    def test_send_axis_sample_connects_when_needed(self) -> None:
        settings = ForwardSettings(host="192.168.40.154", port=3400)
        forwarder = CoreControlVisualForwarder(settings)
        sample = AxisSample(1.0, 2.0, 3.0, 4.0, 5.0, 6.0)

        mock_socket = MagicMock()
        with patch.object(forwarder, "connect", side_effect=lambda: setattr(forwarder, "_socket", mock_socket)):
            forwarder.send_axis_sample(sample)

        mock_socket.sendall.assert_called_once()


if __name__ == "__main__":
    unittest.main()
