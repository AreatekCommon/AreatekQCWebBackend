from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.scanner.sdk_tcp_trace import configure_sdk_trace_logging, log_sdk_trace
from q12_client import Sn3dSdkClient, TcpJsonTransport


class SdkTcpTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        configure_sdk_trace_logging(
            enabled=False,
            log_dir=self._temp_dir.name,
        )

    def tearDown(self) -> None:
        configure_sdk_trace_logging(enabled=False, log_dir=self._temp_dir.name)
        self._temp_dir.cleanup()

    def test_configure_sdk_trace_logging_writes_to_file(self) -> None:
        configure_sdk_trace_logging(
            enabled=True,
            log_dir=self._temp_dir.name,
            log_to_console=False,
        )
        log_sdk_trace("test_event", value=123)

        log_path = Path(self._temp_dir.name) / "sdk_tcp" / "sdk_tcp.log"
        self.assertTrue(log_path.is_file())
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("test_event", content)
        self.assertIn('"value":123', content)

    def test_incoming_message_is_traced(self) -> None:
        configure_sdk_trace_logging(
            enabled=True,
            log_dir=self._temp_dir.name,
            log_to_console=False,
        )

        TcpJsonTransport._print_incoming(
            {
                "cmd": "startScanFinish",
                "type": "rep",
                "result": "success",
            }
        )

        transport = MagicMock()
        client = Sn3dSdkClient(transport, timeout_sec=5.0)
        client._is_connected = True

        with client._state_lock:
            client._command_in_progress = "startScan"
            client._command_finished_event.clear()

        client._handle_incoming_message(
            {
                "cmd": "startScanFinish",
                "type": "rep",
                "result": "success",
            }
        )

        log_path = Path(self._temp_dir.name) / "sdk_tcp" / "sdk_tcp.log"
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("incoming_json", content)
        self.assertIn("startScanFinish", content)
        self.assertIn("command_finish", content)


if __name__ == "__main__":
    unittest.main()
