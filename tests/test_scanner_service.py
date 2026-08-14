from __future__ import annotations

import math
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.pipeline_settings import PipelineSettings
from app.models.runtime_settings import RuntimeSettings
from app.models.scanner_settings import ScannerExposureSettings, ScannerScanParams, ScannerSettings
from app.scanner.service import ScannerService
from app.settings_sections import (
    SETTINGS_SECTION_DEVICE_PARAMS,
    SETTINGS_SECTION_EXPOSURE_SETTINGS,
)
from q12_client import Sn3dCommandFactory


def _runtime_settings(
    *,
    import_markers: bool,
    marker_path: str,
    reapply_params_each_cycle: bool = False,
    scan: ScannerScanParams | None = None,
) -> RuntimeSettings:
    scanner = ScannerSettings(reapply_params_each_cycle=reapply_params_each_cycle)
    if scan is not None:
        scanner = scanner.model_copy(update={"scan": scan})
    return RuntimeSettings(
        pipeline=PipelineSettings(
            import_markers=import_markers,
            marker_framework_path=marker_path,
        ),
        scanner=scanner,
    )


def _scan_paras_calls(sdk: MagicMock) -> list[dict]:
    return [
        call.args[0]
        for call in sdk.send_command.call_args_list
        if call.args[0].get("cmd") == "setScanParas"
    ]


def _command_indices(sdk: MagicMock) -> dict[str, list[int]]:
    commands = [call.args[0].get("cmd") for call in sdk.send_command.call_args_list]
    indices: dict[str, list[int]] = {}
    for index, command in enumerate(commands):
        indices.setdefault(command, []).append(index)
    return indices


class ScannerServiceMarkerLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ScannerService()
        self.service._connected = True
        self.service._sdk = MagicMock()
        self.sdk = self.service._sdk
        self.sdk.send_command.return_value = {"finish": {"retCode": 0}}

    def test_create_project_uses_import_phase_params_before_load(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".p3", delete=False) as handle:
            marker_path = handle.name

        try:
            final_scan = ScannerScanParams(
                align_mod=8,
                scan_markers=False,
                scan_point_cloud=True,
                add_global_markers=True,
            )
            settings = _runtime_settings(
                import_markers=True,
                marker_path=marker_path,
                reapply_params_each_cycle=True,
                scan=final_scan,
            )
            with patch(
                "app.scanner.service.get_runtime_settings",
                return_value=settings,
            ):
                self.service.create_project("scan_test")

            indices = _command_indices(self.sdk)
            load_index = indices["loadFramework"][0]
            scan_paras_calls = _scan_paras_calls(self.sdk)
            self.assertEqual(len(scan_paras_calls), 2)

            import_payload = scan_paras_calls[0]
            final_payload = scan_paras_calls[1]
            self.assertTrue(import_payload["scanMarkers"])
            self.assertFalse(import_payload["scanPointCloud"])
            self.assertEqual(import_payload["alignMod"], 8)
            self.assertFalse(final_payload["scanMarkers"])
            self.assertTrue(final_payload["scanPointCloud"])

            first_scan_paras_index = indices["setScanParas"][0]
            second_scan_paras_index = indices["setScanParas"][1]
            self.assertLess(first_scan_paras_index, load_index)
            self.assertLess(load_index, second_scan_paras_index)

            if "setScanParams" in indices:
                bulk_index = indices["setScanParams"][0]
                self.assertLess(load_index, bulk_index)

            load_calls = [
                call
                for call in self.sdk.send_command.call_args_list
                if call.args[0].get("cmd") == "loadFramework"
            ]
            self.assertEqual(len(load_calls), 1)
            self.assertEqual(load_calls[0].args[0]["path"], marker_path)
        finally:
            Path(marker_path).unlink(missing_ok=True)

    def test_create_project_loads_markers_when_enabled(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".p3", delete=False) as handle:
            marker_path = handle.name

        try:
            settings = _runtime_settings(import_markers=True, marker_path=marker_path)
            with patch(
                "app.scanner.service.get_runtime_settings",
                return_value=settings,
            ):
                self.service.create_project("scan_test")

            commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
            scan_paras_calls = _scan_paras_calls(self.sdk)
            load_index = commands.index("loadFramework")
            self.assertLess(commands.index("setScanParas"), load_index)
            self.assertTrue(scan_paras_calls[0]["scanMarkers"])
            self.assertFalse(scan_paras_calls[0]["scanPointCloud"])
            self.assertEqual(len(scan_paras_calls), 2)

            load_calls = [
                call
                for call in self.sdk.send_command.call_args_list
                if call.args[0].get("cmd") == "loadFramework"
            ]
            self.assertEqual(len(load_calls), 1)
            self.assertEqual(load_calls[0].args[0]["path"], marker_path)
        finally:
            Path(marker_path).unlink(missing_ok=True)

    def test_ensure_project_loads_markers_when_project_opened(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".p3", delete=False) as handle:
            marker_path = handle.name

        try:
            settings = _runtime_settings(import_markers=True, marker_path=marker_path)
            with patch(
                "app.scanner.service.get_runtime_settings",
                return_value=settings,
            ):
                self.service.ensure_project("scan_resume")

            commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
            scan_paras_calls = _scan_paras_calls(self.sdk)
            load_index = commands.index("loadFramework")
            self.assertLess(commands.index("setScanParas"), load_index)
            self.assertTrue(scan_paras_calls[0]["scanMarkers"])
            self.assertFalse(scan_paras_calls[0]["scanPointCloud"])
            self.assertEqual(len(scan_paras_calls), 2)

            load_calls = [
                call
                for call in self.sdk.send_command.call_args_list
                if call.args[0].get("cmd") == "loadFramework"
            ]
            self.assertEqual(len(load_calls), 1)
        finally:
            Path(marker_path).unlink(missing_ok=True)

    def test_ensure_project_reloads_markers_when_project_already_open(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".p3", delete=False) as handle:
            marker_path = handle.name

        try:
            settings = _runtime_settings(import_markers=True, marker_path=marker_path)
            self.service._sdk_project_ready = True
            self.service._sdk_project_name = "scan_resume"

            with patch(
                "app.scanner.service.get_runtime_settings",
                return_value=settings,
            ):
                self.service.ensure_project("scan_resume")

            load_calls = [
                call
                for call in self.sdk.send_command.call_args_list
                if call.args[0].get("cmd") == "loadFramework"
            ]
            self.assertEqual(len(load_calls), 1)
        finally:
            Path(marker_path).unlink(missing_ok=True)

    def test_ensure_project_for_resume_skips_setup_when_project_already_open(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".p3", delete=False) as handle:
            marker_path = handle.name

        try:
            settings = _runtime_settings(import_markers=True, marker_path=marker_path)
            self.service._sdk_project_ready = True
            self.service._sdk_project_name = "scan_resume"

            with patch(
                "app.scanner.service.get_runtime_settings",
                return_value=settings,
            ):
                self.service.ensure_project("scan_resume", for_resume=True)

            self.sdk.send_command.assert_not_called()
        finally:
            Path(marker_path).unlink(missing_ok=True)

    def test_load_marker_framework_skips_when_import_disabled(self) -> None:
        settings = _runtime_settings(import_markers=False, marker_path="ignored.p3")
        with patch(
            "app.scanner.service.get_runtime_settings",
            return_value=settings,
        ):
            ScannerService._load_marker_framework_if_enabled(self.sdk)

        self.sdk.send_command.assert_not_called()

    def test_load_framework_command_shape(self) -> None:
        payload = Sn3dCommandFactory.load_framework(r"C:\markers\ref.p3")
        self.assertEqual(payload["cmd"], "loadFramework")
        self.assertEqual(payload["path"], r"C:\markers\ref.p3")


class ScannerServiceApplyOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sdk = MagicMock()
        self.sdk.send_command.return_value = {"finish": {"retCode": 0}}
        self.scanner = ScannerSettings(
            scan=ScannerScanParams(marker_radius=4, resolution=3),
        )

    def test_apply_device_params_sends_set_scan_paras_before_bulk(self) -> None:
        ScannerService._apply_device_params(self.sdk, self.scanner)

        commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
        scan_paras_index = commands.index("setScanParas")
        bulk_index = commands.index("setScanParams")
        self.assertLess(scan_paras_index, bulk_index)
        self.assertNotIn("setCameraExp", commands)

        scan_paras_payload = self.sdk.send_command.call_args_list[scan_paras_index].args[0]
        self.assertEqual(scan_paras_payload["markerRadius"], 4)
        self.assertEqual(scan_paras_payload["resolution"], 3)

        bulk_payload = self.sdk.send_command.call_args_list[bulk_index].args[0]
        bulk_scan_pars = bulk_payload["scanPars"]
        self.assertEqual(bulk_scan_pars["markerRadius"], "4")
        self.assertEqual(bulk_scan_pars["resolution"], "3")
        self.assertEqual(bulk_scan_pars["autoCutFace"], "false")
        self.assertIn("alignMod", bulk_scan_pars)
        self.assertIn("scanMarkers", bulk_scan_pars)
        self.assertIn("scanPointCloud", bulk_scan_pars)
        self.assertEqual(bulk_scan_pars["addGlobalMarkers"], "true")
        self.assertIn("monocularScan", bulk_scan_pars)

        device_pars = bulk_payload["devicePars"]
        self.assertEqual(device_pars["val1"], "1")
        self.assertEqual(device_pars["markerExp"], "1")
        self.assertEqual(device_pars["expType"], "1")
        self.assertIn("leftGain", device_pars)
        self.assertIn("maskEnable", device_pars)

    def test_apply_scanner_parameters_sends_dual_camera_exposure(self) -> None:
        scanner = ScannerSettings(
            exposure_settings=ScannerExposureSettings(
                mode="first",
                marker_exp=12,
                val1=25,
                val2=18,
                val3=9,
            ),
            scan=ScannerScanParams(marker_radius=4, resolution=3),
        )
        ScannerService._apply_scanner_parameters(self.sdk, scanner)

        camera_exp_calls = [
            call.args[0]
            for call in self.sdk.send_command.call_args_list
            if call.args[0].get("cmd") == "setCameraExp"
        ]
        self.assertEqual(len(camera_exp_calls), 2)
        self.assertEqual(camera_exp_calls[0]["expObj"], 1)
        self.assertEqual(camera_exp_calls[1]["expObj"], 0)
        self.assertEqual(camera_exp_calls[0]["val1"], 25)
        self.assertEqual(camera_exp_calls[0]["val2"], 1)
        self.assertEqual(camera_exp_calls[0]["markerExp"], 12)

    def test_apply_exposure_settings_auto_sends_single_camera_exposure(self) -> None:
        scanner = ScannerSettings(
            exposure_settings=ScannerExposureSettings(mode="auto"),
        )
        ScannerService._apply_exposure_settings(self.sdk, scanner)

        camera_exp_calls = [
            call.args[0]
            for call in self.sdk.send_command.call_args_list
            if call.args[0].get("cmd") == "setCameraExp"
        ]
        self.assertEqual(len(camera_exp_calls), 1)
        self.assertEqual(camera_exp_calls[0]["expObj"], 0)
        self.assertEqual(camera_exp_calls[0]["expType"], 1)

    def test_apply_scanner_parameters_does_not_duplicate_set_scan_paras(self) -> None:
        ScannerService._apply_scanner_parameters(self.sdk, self.scanner)

        scan_paras_count = sum(
            1
            for call in self.sdk.send_command.call_args_list
            if call.args[0].get("cmd") == "setScanParas"
        )
        self.assertEqual(scan_paras_count, 1)

    def test_apply_device_params_only_sends_hardware_and_device_bulk(self) -> None:
        ScannerService._apply_device_params_only(self.sdk, self.scanner)

        commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
        self.assertNotIn("setScanParas", commands)
        self.assertNotIn("setCameraExp", commands)
        self.assertIn("setScanParams", commands)

        bulk_payload = next(
            call.args[0]
            for call in self.sdk.send_command.call_args_list
            if call.args[0].get("cmd") == "setScanParams"
        )
        self.assertEqual(bulk_payload["devicePars"]["RGBLevel"], "14")
        self.assertEqual(bulk_payload["devicePars"]["val1"], "1")
        self.assertEqual(bulk_payload["devicePars"]["markerExp"], "1")
        bulk_scan_pars = bulk_payload["scanPars"]
        self.assertEqual(bulk_scan_pars["markerRadius"], "4")
        self.assertEqual(bulk_scan_pars["resolution"], "3")
        self.assertEqual(bulk_scan_pars["alignMod"], "4")
        self.assertEqual(bulk_scan_pars["scanMarkers"], "true")
        self.assertEqual(bulk_scan_pars["scanPointCloud"], "false")


class ScannerServiceApplySectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ScannerService()
        self.service._connected = True
        self.service._sdk = MagicMock()
        self.service._sdk_project_name = "scan_test_project"
        self.service._sdk_project_ready = True
        self.sdk = self.service._sdk
        self.sdk.send_command.return_value = {"finish": {"retCode": 0}}

    def test_apply_device_params_section_does_not_open_preview_project(self) -> None:
        with patch.object(
            ScannerService,
            "_open_settings_preview_project",
        ) as open_preview:
            self.service.apply_section(SETTINGS_SECTION_DEVICE_PARAMS)

        open_preview.assert_not_called()
        commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
        self.assertNotIn("createSln", commands)
        self.assertNotIn("setScanParas", commands)
        self.assertIn("setScanParams", commands)
        self.assertNotIn("setCameraExp", commands)

    def test_apply_exposure_settings_section_auto_sends_single_camera_exposure_and_bulk(
        self,
    ) -> None:
        self.service.apply_section(SETTINGS_SECTION_EXPOSURE_SETTINGS)

        commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
        self.assertIn("setScanParams", commands)

        camera_exp_calls = [
            call.args[0]
            for call in self.sdk.send_command.call_args_list
            if call.args[0].get("cmd") == "setCameraExp"
        ]
        self.assertEqual(len(camera_exp_calls), 1)
        self.assertEqual(camera_exp_calls[0]["expObj"], 0)
        self.assertEqual(camera_exp_calls[0]["expType"], 1)

    def test_apply_exposure_settings_section_manual_sends_dual_camera_exposure(
        self,
    ) -> None:
        manual_scanner = ScannerSettings(
            exposure_settings=ScannerExposureSettings(
                mode="first",
                marker_exp=12,
                val1=25,
            )
        )
        settings = RuntimeSettings(scanner=manual_scanner)

        with patch(
            "app.scanner.service.get_runtime_settings",
            return_value=settings,
        ):
            self.service.apply_section(SETTINGS_SECTION_EXPOSURE_SETTINGS, settings)

        camera_exp_calls = [
            call.args[0]
            for call in self.sdk.send_command.call_args_list
            if call.args[0].get("cmd") == "setCameraExp"
        ]
        self.assertEqual(len(camera_exp_calls), 2)
        self.assertEqual(camera_exp_calls[0]["expObj"], 1)
        self.assertEqual(camera_exp_calls[1]["expObj"], 0)
        self.assertEqual(camera_exp_calls[0]["val1"], 25)
        self.assertEqual(camera_exp_calls[0]["markerExp"], 12)


class ScannerServiceInitRetryTests(unittest.TestCase):
    def test_initialize_sdk_retries_after_stuck_command_state(self) -> None:
        sdk = MagicMock()
        sdk.initialize_sdk.side_effect = [
            RuntimeError("Команда 'init' еще выполняется"),
            {"finish": {"cmd": "initFinish", "retCode": 0}},
        ]

        with patch(
            "app.scanner.service.ScannerService._recover_sdk_after_init_failure",
        ) as recover:
            ScannerService._initialize_sdk_with_retry(sdk, r"C:\OptimScan\Sn3DProcessManager.exe")

        self.assertEqual(sdk.initialize_sdk.call_count, 2)
        recover.assert_called_once()


class ScannerServiceRunScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ScannerService()
        self.service._connected = True
        self.service._sdk = MagicMock()
        self.sdk = self.service._sdk

    def test_run_scan_accepts_start_scan_finish_success(self) -> None:
        self.sdk.send_command.return_value = {
            "finish": {
                "cmd": "startScanFinish",
                "type": "rep",
                "result": "success",
                "erroCode": "0x",
            }
        }

        self.service.run_scan(1, 0, "scan", "test point")

        self.sdk.send_command.assert_called_once()
        start_scan_payload = self.sdk.send_command.call_args.args[0]
        self.assertEqual(start_scan_payload["cmd"], "startScan")

    def test_run_scan_accepts_scan_finish_with_counts(self) -> None:
        self.sdk.send_command.return_value = {
            "finish": {
                "cmd": "scanFinish",
                "markerCount": 25,
                "pointCount": 1393553,
                "type": "slice",
            }
        }

        self.service.run_scan(2, 1, "scan", "second point")

        self.sdk.send_command.assert_called_once()

    def test_run_scan_rejects_unexpected_finish(self) -> None:
        self.sdk.send_command.return_value = {
            "finish": {"cmd": "startScanBegin", "type": "rep"}
        }

        with self.assertRaises(RuntimeError) as ctx:
            self.service.run_scan(1, 0, "scan", "test point")

        self.assertIn("Unexpected startScan finish", str(ctx.exception))

    def test_run_scan_rejects_failed_start_scan_finish(self) -> None:
        self.sdk.send_command.return_value = {
            "finish": {
                "cmd": "startScanFinish",
                "type": "rep",
                "result": "failed",
                "erroCode": "0x38",
            }
        }

        with self.assertRaises(RuntimeError) as ctx:
            self.service.run_scan(1, 0, "scan", "test point")

        self.assertIn("Unexpected startScan finish", str(ctx.exception))


class ScannerServiceStartSerializationTests(unittest.TestCase):
    def test_concurrent_start_runs_one_connect_sequence(self) -> None:
        import time

        service = ScannerService()
        connect_attempts = 0
        connect_lock = threading.Lock()

        def fake_start_unlocked(_settings: RuntimeSettings | None = None) -> None:
            nonlocal connect_attempts
            with service._lock:
                if service._connected and service._sdk is not None:
                    return
                service._connecting = True

            try:
                time.sleep(0.15)
                with connect_lock:
                    connect_attempts += 1
                with service._lock:
                    service._sdk = MagicMock()
                    service._connected = True
            finally:
                with service._lock:
                    service._connecting = False

        with patch.object(ScannerService, "_start_unlocked", side_effect=fake_start_unlocked):
            first = threading.Thread(target=service.start)
            second = threading.Thread(target=service.start)
            first.start()
            time.sleep(0.02)
            second.start()
            first.join(timeout=5.0)
            second.join(timeout=5.0)

        self.assertEqual(connect_attempts, 1)
        self.assertTrue(service.is_connected)


class ScannerServiceForceReconnectTests(unittest.TestCase):
    def test_force_reconnect_stops_with_release_then_starts_when_disconnected(self) -> None:
        service = ScannerService()
        settings = RuntimeSettings()
        stop_calls: list[bool] = []

        def fake_stop_unlocked(*, release: bool = True) -> None:
            stop_calls.append(release)

        with patch.object(service, "_wait_for_connecting_to_finish"), patch.object(
            service, "_stop_unlocked", side_effect=fake_stop_unlocked
        ) as stop_mock, patch("app.scanner.service.time.sleep"), patch.object(
            service, "_start_unlocked"
        ) as start_mock:
            service.force_reconnect(settings)

        stop_mock.assert_called_once_with(release=True)
        self.assertEqual(stop_calls, [True])
        start_mock.assert_called_once_with(settings)


class ScannerServiceReconnectLifecycleTests(unittest.TestCase):
    def test_stop_uses_shutdown_release_timeout(self) -> None:
        service = ScannerService()
        sdk = MagicMock()
        service._sdk = sdk
        service._connected = True

        with patch("app.scanner.service.sdk_log_collector") as sdk_log_collector:
            service.stop(release=True)

        sdk.release_sdk.assert_called_once()
        self.assertEqual(
            sdk.release_sdk.call_args.kwargs["timeout_sec"],
            15.0,
        )
        sdk.disconnect.assert_called_once()
        sdk_log_collector.stop.assert_called_once()

    def test_format_connect_failure_connection_refused(self) -> None:
        message = ScannerService._format_connect_failure(
            "127.0.0.1",
            3001,
            ConnectionRefusedError(10061, "refused"),
        )

        self.assertIn("not accepting connections", message)
        self.assertIn("OptimScanProtocolHost", message)

    def test_start_sends_release_before_init(self) -> None:
        service = ScannerService()
        settings = RuntimeSettings()
        sdk = MagicMock()

        with patch.object(service, "_connect_with_retry"), patch.object(
            service, "_release_stale_sdk_session"
        ) as release_stale, patch("app.scanner.service.time.sleep") as sleep_mock, patch.object(
            service, "_initialize_sdk_with_retry"
        ), patch.object(service, "_open_settings_preview_project"), patch.object(
            service, "_apply_scanner_parameters"
        ), patch("app.scanner.service.sdk_log_collector"), patch(
            "app.scanner.service.apply_sdk_logging"
        ), patch(
            "app.scanner.service.TcpJsonTransport",
            return_value=MagicMock(),
        ), patch(
            "app.scanner.service.Sn3dSdkClient",
            return_value=sdk,
        ):
            service.start(settings)

        release_stale.assert_called_once_with(sdk)
        sleep_mock.assert_any_call(1.0)

    def test_release_stale_sdk_session_reconnects_after_preamble_release(self) -> None:
        sdk = MagicMock()
        sdk.release_sdk_best_effort.return_value = None

        ScannerService._release_stale_sdk_session(sdk)

        sdk.release_sdk_best_effort.assert_called_once_with(timeout_sec=3.0)
        sdk.reconnect.assert_called_once()

    def test_handle_scanner_disconnect_ignored_while_connecting(self) -> None:
        service = ScannerService()
        service._connecting = True

        with patch.object(service, "stop") as stop_mock:
            service._handle_scanner_disconnect()

        stop_mock.assert_not_called()


class ScannerServiceMeshExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = ScannerService()
        self.service._connected = True
        self.service._sdk = MagicMock()
        self.sdk = self.service._sdk
        self.sdk.send_command.return_value = {"finish": {"retCode": 0}}

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_generate_mesh_and_save_uses_infinite_timeout(self) -> None:
        settings = RuntimeSettings(
            scanner=ScannerSettings(
                export_root=self.temp_dir.name,
                save_type="stl",
                run_global_opt=True,
            )
        )

        with patch(
            "app.scanner.service.get_runtime_settings",
            return_value=settings,
        ):
            self.service.generate_mesh_and_save("scan_mesh_test")

        commands = [call.args[0].get("cmd") for call in self.sdk.send_command.call_args_list]
        self.assertEqual(commands, ["globalOpt", "mesh", "saveData"])
        for call in self.sdk.send_command.call_args_list:
            self.assertTrue(math.isinf(call.kwargs["timeout_sec"]))

    def test_generate_mesh_and_save_p3_uses_flat_markers_dir(self) -> None:
        markers_dir = Path(self.temp_dir.name) / "Markers"
        settings = RuntimeSettings(
            scanner=ScannerSettings(
                export_root=self.temp_dir.name,
                save_type="p3",
                run_global_opt=False,
            )
        )

        with patch("app.scanner.service.get_runtime_settings", return_value=settings), patch(
            "app.scanner.service.MARKERS_DIR", markers_dir
        ):
            self.service.generate_mesh_and_save("marker_project")

        save_call = self.sdk.send_command.call_args_list[-1]
        save_payload = save_call.args[0]
        self.assertEqual(save_payload.get("cmd"), "saveData")
        expected_path = markers_dir / "marker_project.p3"
        self.assertEqual(save_payload.get("savePath"), str(expected_path))
        self.assertFalse((Path(self.temp_dir.name) / "marker_project").exists())


if __name__ == "__main__":
    unittest.main()
