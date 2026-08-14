from __future__ import annotations

import math
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from q12_client import (
    SdkCommandError,
    SNSDK_ERR_MARKER_ALIGN_ERROR,
    SNSDK_ERR_MARKER_TRACK_FAILED,
    Sn3dCommandFactory,
    Sn3dSdkClient,
    _is_init_version_warning,
    _parse_sdk_error_code,
    _scan_finish_error,
    _sdk_finish_error,
)


class SdkFinishErrorTests(unittest.TestCase):
    def test_set_scan_paras_failed_with_erro_code_hex(self) -> None:
        finish = {
            "cmd": "setScanParasFinish",
            "type": "rep",
            "result": "failed",
            "erroCode": "0x28",
        }

        error_info = _sdk_finish_error(finish)

        assert error_info is not None
        self.assertEqual(error_info.ret_code, 40)
        self.assertEqual(error_info.result, "failed")
        self.assertEqual(error_info.error_code_hex, "0x28")
        self.assertIn("result=failed", error_info.detail)
        self.assertIn("erroCode=0x28 (decimal 40)", error_info.detail)
        self.assertIn("finish=", error_info.detail)

    def test_begin_erro_code_zero_is_success(self) -> None:
        finish = {
            "cmd": "setScanParasFinish",
            "type": "rep",
            "erroCode": "0x",
        }

        self.assertIsNone(_sdk_finish_error(finish))

    def test_ret_code_failure(self) -> None:
        finish = {"retCode": 40, "_detail": "invalid params"}

        error_info = _sdk_finish_error(finish)

        assert error_info is not None
        self.assertEqual(error_info.ret_code, 40)
        self.assertIn("invalid params", error_info.detail)

    def test_sdk_command_error_user_message_no_global_markers(self) -> None:
        error = SdkCommandError(
            "loadFramework",
            29,
            "result=NO_GLOBAL_MARKERS",
            result="NO_GLOBAL_MARKERS",
        )

        self.assertTrue(error.is_no_global_markers)
        self.assertIn("no global markers", error.user_message().lower())

    def test_sdk_command_error_user_message_marker_align(self) -> None:
        error = SdkCommandError(
            "startScan",
            SNSDK_ERR_MARKER_ALIGN_ERROR,
            "scanException exception=9",
            finish={"cmd": "scanException", "exception": 9},
            result="scanException",
        )

        self.assertTrue(error.is_marker_align_error)
        self.assertIn("retcode 56", error.user_message().lower())

    def test_sdk_command_error_user_message_scan_exception(self) -> None:
        error = SdkCommandError(
            "startScan",
            9,
            "scanException exception=9",
            finish={"cmd": "scanException", "exception": 9},
            result="scanException",
        )

        self.assertTrue(error.is_scan_exception)
        self.assertIn("scan failed", error.user_message().lower())

    def test_is_alignment_retryable_for_retcode_55(self) -> None:
        error = SdkCommandError(
            "startScan",
            SNSDK_ERR_MARKER_TRACK_FAILED,
            "result=failed; erroCode=0x37",
            finish={"cmd": "startScanFinish", "result": "failed", "erroCode": "0x37"},
            result="failed",
        )

        self.assertTrue(error.is_marker_track_failed)
        self.assertTrue(error.is_alignment_retryable)
        self.assertIn("retcode 55", error.user_message().lower())

    def test_is_alignment_retryable_for_retcode_56(self) -> None:
        error = SdkCommandError(
            "startScan",
            SNSDK_ERR_MARKER_ALIGN_ERROR,
            "scanException",
            finish={"cmd": "scanException"},
            result="scanException",
        )

        self.assertTrue(error.is_alignment_retryable)

    def test_is_alignment_retryable_for_scan_exception(self) -> None:
        error = SdkCommandError(
            "startScan",
            9,
            "scanException exception=9",
            finish={"cmd": "scanException", "exception": 9},
            result="scanException",
        )

        self.assertTrue(error.is_alignment_retryable)

    def test_is_alignment_retryable_false_for_no_global_markers(self) -> None:
        error = SdkCommandError(
            "startScan",
            29,
            "result=NO_GLOBAL_MARKERS",
            result="NO_GLOBAL_MARKERS",
        )

        self.assertFalse(error.is_alignment_retryable)

    def test_is_alignment_retryable_false_for_non_start_scan(self) -> None:
        error = SdkCommandError("setScanParas", 40, "invalid params")

        self.assertFalse(error.is_alignment_retryable)

    def test_scan_finish_error_detects_scan_exception(self) -> None:
        finish = {
            "cmd": "scanException",
            "exception": 9,
            "isScanException": True,
            "level": 3,
        }

        error_info = _scan_finish_error(finish)

        assert error_info is not None
        self.assertEqual(error_info.ret_code, 9)
        self.assertEqual(error_info.result, "scanException")

    def test_scan_finish_error_with_retcode_56(self) -> None:
        finish = {
            "cmd": "scanException",
            "exception": 9,
            "retCode": SNSDK_ERR_MARKER_ALIGN_ERROR,
            "isScanException": True,
        }

        error_info = _sdk_finish_error(finish, command="startScan")

        assert error_info is not None
        self.assertEqual(error_info.ret_code, SNSDK_ERR_MARKER_ALIGN_ERROR)

    def test_scan_finish_success_returns_none(self) -> None:
        finish = {
            "cmd": "scanFinish",
            "markerCount": 12,
            "pointCount": 500000,
        }

        self.assertIsNone(_scan_finish_error(finish))
        self.assertIsNone(_sdk_finish_error(finish, command="startScan"))

    def test_calibration_command_factory_payloads(self) -> None:
        enter_payload = Sn3dCommandFactory.enter_calibration(
            big_range=1,
            factory_mode=0,
            read_xml_mode=1,
        )
        self.assertEqual(enter_payload["cmd"], "enterCalib")
        self.assertEqual(enter_payload["bigRange"], 1)
        self.assertEqual(enter_payload["factoryMode"], 0)
        self.assertEqual(enter_payload["readXmlMode"], 1)

        self.assertEqual(Sn3dCommandFactory.capture_calibration()["cmd"], "captureCali")
        self.assertEqual(Sn3dCommandFactory.prev_calibration()["cmd"], "prevCali")
        self.assertEqual(Sn3dCommandFactory.exit_calibration()["cmd"], "exitCali")

    def test_sdk_command_error_user_message_generic(self) -> None:
        error = SdkCommandError("setScanParas", 40, "invalid params")

        self.assertFalse(error.is_no_global_markers)
        self.assertIn("setScanParas", error.user_message())

    def test_load_framework_no_global_markers(self) -> None:
        finish = {"cmd": "loadP3Finish", "result": "NO_GLOBAL_MARKERS", "retCode": 29}

        error_info = _sdk_finish_error(finish, command="loadFramework")

        assert error_info is not None
        self.assertEqual(error_info.ret_code, 29)
        self.assertEqual(error_info.result, "NO_GLOBAL_MARKERS")
        self.assertIn("result=NO_GLOBAL_MARKERS", error_info.detail)

    def test_load_framework_no_global_markers_without_ret_code(self) -> None:
        finish = {"cmd": "loadP3Finish", "result": "NO_GLOBAL_MARKERS"}

        error_info = _sdk_finish_error(finish, command="loadFramework")

        assert error_info is not None
        self.assertEqual(error_info.ret_code, -1)
        self.assertEqual(error_info.result, "NO_GLOBAL_MARKERS")

    def test_init_finish_retcode_1_is_success_with_warning(self) -> None:
        finish = {"cmd": "initFinish", "retCode": 1}

        self.assertIsNone(_sdk_finish_error(finish, command="init"))

    def test_init_finish_retcode_1_still_fails_other_commands(self) -> None:
        finish = {"cmd": "createSlnFinish", "retCode": 1}

        error_info = _sdk_finish_error(finish, command="createSln")

        assert error_info is not None
        self.assertEqual(error_info.ret_code, 1)

    def test_init_finish_result_failed_errocode_0x1_is_success(self) -> None:
        finish = {
            "cmd": "initFinish",
            "type": "rep",
            "result": "failed",
            "erroCode": "0x1",
        }

        self.assertIsNone(_sdk_finish_error(finish, command="init"))
        self.assertTrue(_is_init_version_warning(finish, command="init"))

        error_info = _sdk_finish_error(finish, command="createSln")
        assert error_info is not None
        self.assertEqual(error_info.ret_code, 1)

    def test_parse_sdk_error_code_hex(self) -> None:
        self.assertEqual(_parse_sdk_error_code("0x28"), 40)
        self.assertEqual(_parse_sdk_error_code("0x"), 0)
        self.assertEqual(_parse_sdk_error_code("40"), 40)

    def test_sdk_command_error_detail_dict(self) -> None:
        finish = {"cmd": "setScanParasFinish", "type": "rep", "result": "failed", "erroCode": "0x28"}
        begin = {"cmd": "setScanParasBegin", "erroCode": "0x"}
        error = SdkCommandError(
            "setScanParas",
            40,
            "result=failed; erroCode=0x28 (decimal 40)",
            begin=begin,
            finish=finish,
            result="failed",
            error_code_hex="0x28",
        )

        detail = error.to_detail_dict()
        self.assertEqual(detail["command"], "setScanParas")
        self.assertEqual(detail["ret_code"], 40)
        self.assertEqual(detail["error_code_hex"], "0x28")
        self.assertEqual(detail["result"], "failed")
        self.assertIn("failed", detail["finish_json"] or "")


class Sn3dSdkClientInitTests(unittest.TestCase):
    def _make_client(self) -> Sn3dSdkClient:
        transport = MagicMock()
        return Sn3dSdkClient(transport, timeout_sec=5.0)

    def test_show_main_view_completes_init(self) -> None:
        client = self._make_client()
        with client._state_lock:
            client._command_in_progress = "init"
            client._command_finished_event.clear()

        client._handle_incoming_message(
            {
                "cmd": "showMainView",
                "useSdkVersion": "1.75.0",
                "tModule": "Sn3DSDKOptimScanQ12Plugin",
            }
        )

        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())
        self.assertEqual(client._last_finish_message["cmd"], "showMainView")

    def test_load_p3_finish_completes_load_framework(self) -> None:
        client = self._make_client()
        with client._state_lock:
            client._command_in_progress = "loadFramework"
            client._command_finished_event.clear()

        client._handle_incoming_message(
            {
                "cmd": "loadP3Finish",
                "result": "NO_GLOBAL_MARKERS",
                "retCode": 29,
            }
        )

        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())
        self.assertEqual(client._last_finish_message["cmd"], "loadP3Finish")

    def test_duplicate_initialize_sdk_is_noop(self) -> None:
        client = self._make_client()
        with client._state_lock:
            client._sdk_initialized = True

        result = client.initialize_sdk("C:/Program Files/OptimScan Q/Sn3DProcessManager.exe")

        self.assertTrue(result.get("skipped"))
        transport = client._transport
        transport.send_json.assert_not_called()

    def test_release_sdk_uses_custom_timeout(self) -> None:
        client = self._make_client()
        client._is_connected = True

        with patch.object(client, "send_command", return_value={"cmd": "release"}) as send_command:
            client.release_sdk(timeout_sec=7.5)

        send_command.assert_called_once()
        self.assertEqual(send_command.call_args.kwargs["timeout_sec"], 7.5)
        self.assertFalse(client.is_sdk_initialized)

    def test_release_sdk_best_effort_swallows_errors(self) -> None:
        client = self._make_client()
        client._is_connected = True

        with patch.object(
            client,
            "release_sdk",
            side_effect=TimeoutError("release timed out"),
        ):
            result = client.release_sdk_best_effort(timeout_sec=3.0)

        self.assertIsNone(result)
        self.assertFalse(client.is_sdk_initialized)
        self.assertFalse(client.is_command_in_progress())


class Sn3dSdkClientCommandStateTests(unittest.TestCase):
    def _make_connected_client(self, *, timeout_sec: float = 0.1) -> Sn3dSdkClient:
        transport = MagicMock()
        client = Sn3dSdkClient(transport, timeout_sec=timeout_sec)
        client._is_connected = True
        return client

    def test_reset_command_state_clears_in_progress(self) -> None:
        client = self._make_connected_client()
        with client._state_lock:
            client._command_in_progress = "init"
            client._command_finished_event.clear()

        client.reset_command_state()

        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())

    def test_timeout_clears_in_progress(self) -> None:
        client = self._make_connected_client(timeout_sec=0.05)

        with self.assertRaises(TimeoutError):
            client.send_command(Sn3dCommandFactory.init())

        self.assertFalse(client.is_command_in_progress())

    def test_infinite_timeout_waits_past_default(self) -> None:
        client = self._make_connected_client(timeout_sec=0.05)

        def finish_later() -> None:
            time.sleep(0.15)
            client._handle_incoming_message({"cmd": "initFinish", "retCode": 0})

        thread = threading.Thread(target=finish_later)
        thread.start()
        try:
            result = client.send_command(
                Sn3dCommandFactory.init(),
                timeout_sec=math.inf,
            )
        finally:
            thread.join(timeout=2.0)

        self.assertEqual(result["cmd"], "init")
        self.assertFalse(client.is_command_in_progress())

    def test_timeout_allows_subsequent_command(self) -> None:
        client = self._make_connected_client(timeout_sec=0.05)

        with self.assertRaises(TimeoutError):
            client.send_command(Sn3dCommandFactory.init())

        client._handle_incoming_message({"cmd": "initFinish", "retCode": 0})
        result = client.send_command(
            Sn3dCommandFactory.create_solution(),
            wait_for_finish=False,
        )
        self.assertEqual(result["cmd"], "createSln")
        self.assertTrue(client.is_command_in_progress())

    def test_concurrent_send_command_raises(self) -> None:
        client = self._make_connected_client(timeout_sec=1.0)
        started = threading.Event()
        release = threading.Event()
        errors: list[Exception] = []

        def first_command() -> None:
            with client._state_lock:
                client._command_in_progress = "init"
                client._command_finished_event.clear()
            started.set()
            release.wait(timeout=2.0)

        thread = threading.Thread(target=first_command)
        thread.start()
        self.assertTrue(started.wait(timeout=2.0))

        try:
            with self.assertRaises(RuntimeError) as ctx:
                client.send_command(Sn3dCommandFactory.create_solution())
            self.assertIn("еще выполняется", str(ctx.exception))
        finally:
            release.set()
            thread.join(timeout=2.0)


class Sn3dSdkClientStartScanTests(unittest.TestCase):
    def _make_client(self) -> Sn3dSdkClient:
        transport = MagicMock()
        client = Sn3dSdkClient(transport, timeout_sec=5.0)
        client._is_connected = True
        return client

    def test_scan_finish_completes_start_scan(self) -> None:
        client = self._make_client()
        with client._state_lock:
            client._command_in_progress = "startScan"
            client._command_finished_event.clear()

        client._handle_incoming_message(
            {
                "cmd": "scanFinish",
                "markerCount": 16,
                "pointCount": 806385,
                "type": "slice",
            }
        )

        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())
        self.assertEqual(client._last_finish_message["cmd"], "scanFinish")

    def test_scan_exception_completes_start_scan(self) -> None:
        client = self._make_client()
        with client._state_lock:
            client._command_in_progress = "startScan"
            client._command_finished_event.clear()

        client._handle_incoming_message(
            {
                "cmd": "scanException",
                "exception": 9,
                "isScanException": True,
                "level": 3,
            }
        )

        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())
        self.assertEqual(client._last_finish_message["cmd"], "scanException")

    def test_start_scan_finish_completes_via_generic_handler(self) -> None:
        client = self._make_client()
        with client._state_lock:
            client._command_in_progress = "startScan"
            client._command_finished_event.clear()

        client._handle_incoming_message(
            {
                "cmd": "startScanFinish",
                "type": "rep",
                "result": "success",
                "erroCode": "0x",
            }
        )

        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())
        self.assertEqual(client._last_finish_message["cmd"], "startScanFinish")

    def test_send_command_raises_on_scan_exception(self) -> None:
        client = self._make_client()
        transport = client._transport

        def trigger_scan_exception(_payload: dict) -> None:
            client._handle_incoming_message(
                {
                    "cmd": "scanException",
                    "exception": 9,
                    "retCode": SNSDK_ERR_MARKER_ALIGN_ERROR,
                    "isScanException": True,
                }
            )

        transport.send_json.side_effect = trigger_scan_exception

        with self.assertRaises(SdkCommandError) as ctx:
            client.send_command(Sn3dCommandFactory.start_scan())

        self.assertTrue(ctx.exception.is_marker_align_error)


class TransportDisconnectTests(unittest.TestCase):
    def test_transport_disconnect_callback_marks_client_offline(self) -> None:
        transport = MagicMock()
        client = Sn3dSdkClient(transport, timeout_sec=5.0)
        client._is_connected = True
        with client._state_lock:
            client._sdk_initialized = True
            client._command_in_progress = "init"
            client._command_finished_event.clear()

        disconnect_calls: list[str] = []

        def on_disconnect() -> None:
            disconnect_calls.append("called")

        client.set_transport_disconnect_callback(on_disconnect)

        wrapped = transport.set_transport_disconnect_callback.call_args[0][0]
        wrapped()

        self.assertFalse(client._is_connected)
        self.assertFalse(client.is_sdk_initialized)
        self.assertFalse(client.is_command_in_progress())
        self.assertTrue(client._command_finished_event.is_set())
        self.assertEqual(disconnect_calls, ["called"])


if __name__ == "__main__":
    unittest.main()
