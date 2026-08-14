from __future__ import annotations

import atexit
import json
import math
import signal
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from app.core.logger import get_logger
from app.core.fixed_paths import MARKERS_DIR
from app.core.runtime_settings_store import get_runtime_settings
from app.eki.messages import TrajectoryPoint
from app.models.runtime_settings import RuntimeSettings
from app.models.scanner_settings import ScannerScanParams, ScannerSettings
from app.models.pipeline_settings import CalibrationSettings
from app.scanner.sdk_log_collector import sdk_log_collector
from app.scanner.sdk_logging import apply_sdk_logging
from app.scanner.constraints import ALIGN_MOD_GLOBAL_MARKER
from app.scanner.config import (
    COMMAND_STILL_RUNNING_MARKER,
    SDK_CONNECTING_WAIT_TIMEOUT_SEC,
    SDK_CONNECT_MAX_ATTEMPTS,
    SDK_CONNECT_RETRY_DELAY_SEC,
    SDK_EXIT_RELEASE_TIMEOUT_SEC,
    SDK_INIT_MAX_ATTEMPTS,
    SDK_INIT_RETRY_DELAY_SEC,
    SDK_PREAMBLE_RELEASE_TIMEOUT_SEC,
    SDK_RESTART_DELAY_SEC,
    SDK_SESSION_SETTLE_SEC,
    SDK_SHUTDOWN_RELEASE_TIMEOUT_SEC,
    SDK_TIMEOUT_SEC,
    SETTINGS_PREVIEW_PROJECT_NAME,
    is_scan_save_type,
)
from app.exposure_wire import (
    PointExposureValues,
    WireExposurePayload,
    build_point_scan_exposure_commands,
    encode_exposure_wire,
    exposure_sdk_commands,
)
from app.settings_sections import (
    SETTINGS_SECTION_DEVICE_PARAMS,
    SETTINGS_SECTION_EXPOSURE_RANGE,
    SETTINGS_SECTION_EXPOSURE_SETTINGS,
    SETTINGS_SECTION_SCAN_PARAMS,
    SETTINGS_SECTION_SDK_PATHS,
    SCANNER_APPLY_SECTIONS,
    SAVE_ONLY_SCANNER_SECTIONS,
)
from q12_client import SdkConfig, Sn3dCommandFactory, Sn3dSdkClient, TcpJsonTransport

logger = get_logger(__name__)


class ScannerService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._sdk_command_lock = threading.Lock()
        self._exit_lock = threading.Lock()
        self._exit_cleanup_registered = False
        self._sdk: Optional[Sn3dSdkClient] = None
        self._connected = False
        self._connecting = False
        self._restarting = False
        self._disconnect_callback: Optional[Callable[[], None]] = None
        self._handling_offline = False
        self._sdk_project_name: Optional[str] = None
        self._sdk_project_ready = False

    def _ensure_exit_cleanup_registered(self) -> None:
        with self._exit_lock:
            if self._exit_cleanup_registered:
                return
            atexit.register(self._atexit_release)
            self._register_signal_handlers()
            self._exit_cleanup_registered = True

    def _register_signal_handlers(self) -> None:
        signum = getattr(signal, "SIGTERM", None)
        if signum is None:
            return

        def handler(_signum: int, _frame: object) -> None:
            logger.info("ScannerService received SIGTERM; releasing SDK")
            self._atexit_release()

        try:
            signal.signal(signum, handler)
        except (OSError, ValueError, RuntimeError):
            pass

    def _atexit_release(self) -> None:
        with self._exit_lock:
            try:
                self.stop(
                    release=True,
                    release_timeout_sec=SDK_EXIT_RELEASE_TIMEOUT_SEC,
                )
            except Exception as exc:
                logger.warning("Scanner atexit release warning: %s", exc)

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._sdk is not None

    def is_connecting(self) -> bool:
        with self._lock:
            return self._connecting

    def is_restarting(self) -> bool:
        with self._lock:
            return self._restarting

    def set_disconnect_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._disconnect_callback = callback

    @staticmethod
    def needs_connection_restart(old: RuntimeSettings, new: RuntimeSettings) -> bool:
        return (
            old.scanner_host != new.scanner_host
            or old.scanner_port != new.scanner_port
            or old.scanner.process_path != new.scanner.process_path
        )

    def start(self, settings: RuntimeSettings | None = None) -> None:
        with self._start_lock:
            self._start_unlocked(settings)

    def _start_unlocked(self, settings: RuntimeSettings | None = None) -> None:
        runtime_settings = settings or get_runtime_settings()
        self._ensure_exit_cleanup_registered()

        with self._lock:
            if self._connected and self._sdk is not None:
                logger.debug("ScannerService already started")
                return
            self._connecting = True

        sdk: Optional[Sn3dSdkClient] = None
        scanner = runtime_settings.scanner
        try:
            logger.info(
                "Starting scanner SDK connection to %s:%d...",
                runtime_settings.scanner_host,
                runtime_settings.scanner_port,
            )
            config = SdkConfig(
                host=runtime_settings.scanner_host,
                port=runtime_settings.scanner_port,
                timeout_sec=SDK_TIMEOUT_SEC,
            )
            transport = TcpJsonTransport(config)
            sdk = Sn3dSdkClient(transport, timeout_sec=SDK_TIMEOUT_SEC)
            sdk.set_device_offline_callback(self._on_device_offline)
            sdk.set_transport_disconnect_callback(self._on_transport_disconnect)
            self._connect_with_retry(
                sdk,
                runtime_settings.scanner_host,
                runtime_settings.scanner_port,
            )
            self._invalidate_sdk_project_state()
            with self._sdk_command_lock:
                self._release_stale_sdk_session(sdk)
                time.sleep(SDK_SESSION_SETTLE_SEC)
                self._initialize_sdk_with_retry(sdk, scanner.process_path)

                logger.info("Applying scanner parameters...")
                self._open_settings_preview_project(sdk, scanner)
                self._apply_scanner_parameters(sdk, scanner)
            apply_sdk_logging(runtime_settings)
            sdk_log_collector.start(runtime_settings)

            with self._lock:
                self._sdk = sdk
                self._connected = True
                self._handling_offline = False
            logger.info("Scanner SDK ready")
        except Exception:
            if sdk is not None:
                sdk.set_device_offline_callback(None)
                sdk.set_transport_disconnect_callback(None)
                try:
                    sdk.disconnect()
                except Exception as exc:
                    logger.warning("Scanner cleanup disconnect warning: %s", exc)
            raise
        finally:
            with self._lock:
                self._connecting = False

    def stop(
        self,
        *,
        release: bool = True,
        release_timeout_sec: float | None = None,
    ) -> None:
        self._wait_for_connecting_to_finish()
        self._stop_unlocked(release=release, release_timeout_sec=release_timeout_sec)

    def _stop_unlocked(
        self,
        *,
        release: bool = True,
        release_timeout_sec: float | None = None,
    ) -> None:
        sdk_log_collector.stop()

        with self._lock:
            sdk = self._sdk
            self._sdk = None
            self._connected = False
            self._clear_sdk_project_state_locked()

        if sdk is None:
            return

        sdk.set_device_offline_callback(None)
        sdk.set_transport_disconnect_callback(None)

        if release:
            timeout_sec = (
                release_timeout_sec
                if release_timeout_sec is not None
                else SDK_SHUTDOWN_RELEASE_TIMEOUT_SEC
            )
            try:
                sdk.release_sdk(timeout_sec=timeout_sec)
                logger.info("Scanner SDK released")
            except Exception as exc:
                logger.warning("Scanner release warning: %s", exc)

        try:
            sdk.disconnect()
            logger.info("Scanner disconnected")
        except Exception as exc:
            logger.warning("Scanner disconnect warning: %s", exc)

    def restart(self, settings: RuntimeSettings | None = None) -> None:
        with self._start_lock:
            with self._lock:
                self._restarting = True
            try:
                self._stop_unlocked(release=True)
                time.sleep(SDK_RESTART_DELAY_SEC)
                self._start_unlocked(settings)
            finally:
                with self._lock:
                    self._restarting = False

    def force_reconnect(self, settings: RuntimeSettings | None = None) -> None:
        with self._start_lock:
            self._wait_for_connecting_to_finish()
            with self._lock:
                if self._connecting:
                    logger.warning("Force-clearing stuck scanner connecting flag")
                    self._connecting = False
            self._stop_unlocked(release=True)
            time.sleep(SDK_RESTART_DELAY_SEC)
            self._start_unlocked(settings)

    def ensure_connected(
        self,
        settings: RuntimeSettings | None = None,
        *,
        timeout_sec: float = 30.0,
    ) -> bool:
        if self.is_connected:
            return True

        if self.is_connecting() or self.is_restarting():
            self._wait_for_connecting_to_finish()
            if self.is_connected:
                return True

        runtime_settings = settings or get_runtime_settings()
        deadline = time.time() + timeout_sec
        retry_delay_sec = min(SDK_CONNECT_RETRY_DELAY_SEC, 2.0)

        while time.time() < deadline:
            try:
                self.start(runtime_settings)
                return self.is_connected
            except Exception as exc:
                logger.warning("Scanner ensure_connected attempt failed: %s", exc)
            time.sleep(retry_delay_sec)

        return self.is_connected

    def _wait_for_connecting_to_finish(self) -> None:
        deadline = time.time() + SDK_CONNECTING_WAIT_TIMEOUT_SEC
        while time.time() < deadline:
            with self._lock:
                if not self._connecting:
                    return
            time.sleep(0.05)
        logger.warning(
            "Timed out waiting %.1fs for scanner connect to finish",
            SDK_CONNECTING_WAIT_TIMEOUT_SEC,
        )

    def apply_parameters(self, settings: RuntimeSettings | None = None) -> None:
        runtime_settings = settings or get_runtime_settings()
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            scanner = runtime_settings.scanner
            logger.info("Applying scanner parameters without reconnect...")
            self._open_settings_preview_project(sdk, scanner)
            self._apply_scanner_parameters(sdk, scanner)

    def apply_section(
        self,
        section: str,
        settings: RuntimeSettings | None = None,
        *,
        previous: RuntimeSettings | None = None,
    ) -> None:
        runtime_settings = settings or get_runtime_settings()
        scanner = runtime_settings.scanner

        if section in SAVE_ONLY_SCANNER_SECTIONS:
            logger.info("Scanner section %s saved (no live SDK apply)", section)
            return

        if section not in SCANNER_APPLY_SECTIONS:
            raise ValueError(f"Unknown scanner apply section: {section}")

        with self._sdk_command_lock:
            sdk = self._require_sdk()

            if section == SETTINGS_SECTION_SDK_PATHS:
                self._open_settings_preview_project(sdk, scanner)
                return

            if section == SETTINGS_SECTION_DEVICE_PARAMS:
                logger.info(
                    "Applying device params in-place on current SDK project: %s",
                    self._sdk_project_name or "(none)",
                )
                self._apply_device_params_only(sdk, scanner)
            elif section == SETTINGS_SECTION_SCAN_PARAMS:
                logger.info(
                    "Applying scan params in-place on current SDK project: %s",
                    self._sdk_project_name or "(none)",
                )
                self._apply_scan_params(sdk, scanner)
                self._apply_scan_params_bulk(sdk, scanner)
            elif section == SETTINGS_SECTION_EXPOSURE_RANGE:
                logger.info(
                    "Applying exposure range in-place on current SDK project: %s",
                    self._sdk_project_name or "(none)",
                )
                self._apply_exposure_range(sdk, scanner)
            elif section == SETTINGS_SECTION_EXPOSURE_SETTINGS:
                logger.info(
                    "Applying exposure settings in-place on current SDK project: %s",
                    self._sdk_project_name or "(none)",
                )
                self._apply_device_bulk_only(sdk, scanner)
                self._apply_exposure_settings(sdk, scanner)

    def create_project(self, project_name: str) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            settings = get_runtime_settings()
            scanner = settings.scanner
            logger.info("Creating project: %s", project_name)
            self._open_sdk_project(sdk, scanner, project_name)
            self._setup_scanner_for_project(sdk, scanner)

    def ensure_project(self, project_name: str, *, for_resume: bool = False) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            settings = get_runtime_settings()
            scanner = settings.scanner
            logger.info("Ensuring scanner project: %s", project_name)
            opened = self._ensure_sdk_project(sdk, scanner, project_name)
            if for_resume and not opened:
                logger.info("Resume: project %s already open; skipping scanner setup", project_name)
                return
            self._setup_scanner_for_project(sdk, scanner)

    def run_scan(
        self,
        scan_index: int,
        point_index: int,
        point_type: str,
        comment: str,
        *,
        point: TrajectoryPoint | None = None,
        per_point_exposure: bool = False,
        per_point_marker_exposure: bool = False,
    ) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            if point is not None and (per_point_exposure or per_point_marker_exposure):
                self._apply_point_exposure(
                    sdk,
                    point,
                    per_point_exposure=per_point_exposure,
                    per_point_marker_exposure=per_point_marker_exposure,
                )
            logger.info(
                "Scan #%d: idx=%s type=%s comment=%s",
                scan_index,
                point_index,
                point_type,
                comment,
            )
            result = sdk.send_command(Sn3dCommandFactory.start_scan())
            finish = result.get("finish") or {}
            finish_cmd = finish.get("cmd")
            if finish_cmd == "scanFinish":
                logger.info(
                    "Scan #%d completed (markerCount=%s pointCount=%s)",
                    scan_index,
                    finish.get("markerCount"),
                    finish.get("pointCount"),
                )
            elif finish_cmd == "startScanFinish":
                result_value = str(finish.get("result", "")).strip().lower()
                if result_value != "success":
                    raise RuntimeError(
                        f"Unexpected startScan finish: {json.dumps(finish, ensure_ascii=False)}"
                    )
                logger.info("Scan #%d completed (startScanFinish success)", scan_index)
            else:
                raise RuntimeError(
                    f"Unexpected startScan finish: {json.dumps(finish, ensure_ascii=False)}"
                )

    def enter_calibration(self, settings: CalibrationSettings) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            logger.info(
                "Entering calibration mode (bigRange=%s factoryMode=%s readXmlMode=%s)",
                settings.big_range,
                settings.factory_mode,
                settings.read_xml_mode,
            )
            sdk.send_command(
                Sn3dCommandFactory.enter_calibration(
                    big_range=settings.big_range,
                    factory_mode=settings.factory_mode,
                    read_xml_mode=settings.read_xml_mode,
                )
            )

    def capture_calibration(
        self,
        capture_index: int,
        point_index: int,
        comment: str,
    ) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            logger.info(
                "Calibration capture #%d: idx=%s comment=%s",
                capture_index,
                point_index,
                comment,
            )
            sdk.send_command(Sn3dCommandFactory.capture_calibration())

    def exit_calibration(self) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            logger.info("Exiting calibration mode")
            sdk.send_command(Sn3dCommandFactory.exit_calibration())

    def generate_mesh_and_save(self, project_name: str) -> None:
        with self._sdk_command_lock:
            sdk = self._require_sdk()
            scanner = get_runtime_settings().scanner
            if scanner.save_type == "p3":
                export_dir = MARKERS_DIR
            else:
                export_dir = Path(scanner.export_root) / project_name
            export_dir.mkdir(parents=True, exist_ok=True)

            if scanner.run_global_opt:
                logger.info("Running global optimization...")
                sdk.send_command(
                    Sn3dCommandFactory.global_optimization(),
                    timeout_sec=math.inf,
                )

            if is_scan_save_type(scanner.save_type):
                logger.info(
                    "Exporting scan data as %s (mesh skipped)",
                    scanner.save_type,
                )
            else:
                mesh = scanner.mesh
                logger.info("Generating mesh...")
                sdk.send_command(
                    Sn3dCommandFactory.mesh(
                        mesh_type=mesh.mesh_type,
                        unwatertight_detail=mesh.unwatertight_detail,
                        depth=mesh.depth,
                        filter_level=mesh.filter_level,
                        smooth_level=mesh.smooth_level,
                        remove_small=mesh.remove_small,
                        max_face=mesh.max_face,
                        face_limit=mesh.face_limit,
                        fill_small_hole=mesh.fill_small_hole,
                        small_hole_perimeter=mesh.small_hole_perimeter,
                        neighbourhood=mesh.neighbourhood,
                        spike_sensitivity=mesh.spike_sensitivity,
                        fill_marker_hole=mesh.fill_marker_hole,
                        border_opt=mesh.border_opt,
                        need_thin_obj_mesh=mesh.need_thin_obj_mesh,
                    ),
                    timeout_sec=math.inf,
                )

            save_path = export_dir / f"{project_name}.{scanner.save_type}"
            logger.info("Saving data: %s", save_path)
            sdk.send_command(
                Sn3dCommandFactory.save_data(
                    save_type=scanner.save_type,
                    save_path=str(save_path),
                    name=save_path.name,
                ),
                timeout_sec=math.inf,
            )
            if is_scan_save_type(scanner.save_type):
                logger.info("Scan export completed")
            else:
                logger.info("Mesh and save completed")

    def _on_transport_disconnect(self) -> None:
        logger.warning("Scanner SDK TCP connection lost; scheduling reconnect")
        self._handle_scanner_disconnect()

    def _on_device_offline(self) -> None:
        logger.warning("Scanner device reported offline; scheduling reconnect")
        self._handle_scanner_disconnect()

    def _handle_scanner_disconnect(self) -> None:
        with self._lock:
            if self._connecting:
                logger.debug(
                    "Ignoring transport disconnect during scanner connect sequence"
                )
                return
            if self._handling_offline:
                return
            self._handling_offline = True

        self.stop(release=False)

        callback = self._disconnect_callback
        if callback is not None:
            callback()

    def _require_sdk(self) -> Sn3dSdkClient:
        with self._lock:
            if self._sdk is None or not self._connected:
                raise RuntimeError("Scanner SDK is not connected")
            return self._sdk

    def _clear_sdk_project_state_locked(self) -> None:
        self._sdk_project_name = None
        self._sdk_project_ready = False

    def _invalidate_sdk_project_state(self) -> None:
        with self._lock:
            self._clear_sdk_project_state_locked()

    def _open_settings_preview_project(
        self,
        sdk: Sn3dSdkClient,
        scanner: ScannerSettings,
    ) -> None:
        logger.info(
            "Opening settings preview project: %s at %s",
            SETTINGS_PREVIEW_PROJECT_NAME,
            scanner.project_root,
        )
        self._open_sdk_project(sdk, scanner, SETTINGS_PREVIEW_PROJECT_NAME)

    def _ensure_sdk_project(
        self,
        sdk: Sn3dSdkClient,
        scanner: ScannerSettings,
        project_name: str,
    ) -> bool:
        with self._lock:
            if self._sdk_project_ready and self._sdk_project_name == project_name:
                return False

        self._open_sdk_project(sdk, scanner, project_name)
        return True

    @staticmethod
    def _load_marker_framework_if_enabled(sdk: Sn3dSdkClient) -> None:
        settings = get_runtime_settings()
        pipeline = settings.pipeline
        if not pipeline.import_markers:
            return

        marker_path = pipeline.marker_framework_path.strip()
        if not marker_path:
            raise RuntimeError(
                "Marker framework path is required when import_markers is enabled"
            )
        if not Path(marker_path).is_file():
            raise RuntimeError(f"Marker framework file not found: {marker_path}")

        scan = settings.scanner.scan
        import_scan = ScannerService._import_phase_scan_params(settings.scanner)
        if scan.align_mod != ALIGN_MOD_GLOBAL_MARKER:
            logger.warning(
                "Saved align_mod=%d differs from global-marker import mode (%d); "
                "import phase will use align_mod=%d",
                scan.align_mod,
                ALIGN_MOD_GLOBAL_MARKER,
                ALIGN_MOD_GLOBAL_MARKER,
            )
        logger.info(
            "Loading marker framework (import phase: align_mod=%d scan_markers=%s "
            "scan_point_cloud=%s; final phase: align_mod=%d scan_markers=%s "
            "scan_point_cloud=%s add_global_markers=%s): %s",
            import_scan.align_mod,
            import_scan.scan_markers,
            import_scan.scan_point_cloud,
            scan.align_mod,
            scan.scan_markers,
            scan.scan_point_cloud,
            scan.add_global_markers,
            marker_path,
        )
        sdk.send_command(Sn3dCommandFactory.load_framework(marker_path))
        logger.info("Marker framework loaded")

    @staticmethod
    def _import_phase_scan_params(scanner: ScannerSettings) -> ScannerScanParams:
        scan = scanner.scan.model_copy(deep=True)
        scan.align_mod = ALIGN_MOD_GLOBAL_MARKER
        scan.scan_markers = True
        scan.scan_point_cloud = False
        return scan

    @staticmethod
    def _setup_scanner_for_project(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        settings = get_runtime_settings()
        needs_import = settings.pipeline.import_markers

        if needs_import:
            if scanner.reapply_params_each_cycle:
                ScannerService._apply_exposure_range(sdk, scanner)
                ScannerService._apply_device_hardware_params(sdk, scanner)

            import_scan = ScannerService._import_phase_scan_params(scanner)
            logger.info(
                "Applying marker-import scan params before loadFramework "
                "(align_mod=%d scan_markers=%s scan_point_cloud=%s)",
                import_scan.align_mod,
                import_scan.scan_markers,
                import_scan.scan_point_cloud,
            )
            ScannerService._apply_scan_params(sdk, scanner, scan=import_scan)
            ScannerService._load_marker_framework_if_enabled(sdk)

            logger.info(
                "Applying final scan params after marker framework load "
                "(align_mod=%d scan_markers=%s scan_point_cloud=%s)",
                scanner.scan.align_mod,
                scanner.scan.scan_markers,
                scanner.scan.scan_point_cloud,
            )
            ScannerService._apply_scan_params(sdk, scanner)
            if scanner.reapply_params_each_cycle:
                ScannerService._apply_scan_params_bulk(sdk, scanner)
            return

        if scanner.reapply_params_each_cycle:
            ScannerService._apply_scanner_parameters(sdk, scanner)
        else:
            ScannerService._apply_scan_params(sdk, scanner)

    def _open_sdk_project(
        self,
        sdk: Sn3dSdkClient,
        scanner: ScannerSettings,
        project_name: str,
    ) -> None:
        self._invalidate_sdk_project_state()
        logger.info(
            "Sending createSln: slnName=%s szSlnDirPath=%s workRange=%d iNeedLimit=%d",
            project_name,
            scanner.project_root,
            scanner.work_range,
            scanner.need_limit,
        )
        result = sdk.send_command(
            Sn3dCommandFactory.create_solution(
                sln_dir_path=scanner.project_root,
                sln_name=project_name,
                work_range=scanner.work_range,
                need_limit=scanner.need_limit,
            )
        )
        finish = result.get("finish")
        if finish:
            logger.info(
                "createSln finish: %s",
                json.dumps(finish, ensure_ascii=False, separators=(",", ":")),
            )
        with self._lock:
            self._sdk_project_name = project_name
            self._sdk_project_ready = True
        logger.info("SDK project opened: %s", project_name)

    @staticmethod
    def _recover_sdk_after_init_failure(sdk: Sn3dSdkClient) -> None:
        sdk.reset_command_state()
        try:
            sdk.reconnect()
        except Exception as exc:
            logger.warning("Scanner reconnect after init failure: %s", exc)

    @staticmethod
    def _initialize_sdk_with_retry(sdk: Sn3dSdkClient, process_path: str) -> None:
        last_error: Optional[Exception] = None
        for attempt in range(1, SDK_INIT_MAX_ATTEMPTS + 1):
            logger.info(
                "Initializing scanner SDK (attempt %d/%d)...",
                attempt,
                SDK_INIT_MAX_ATTEMPTS,
            )
            try:
                result = sdk.initialize_sdk(process_path)
                if result.get("skipped"):
                    logger.info("Scanner SDK init skipped (already initialized)")
                    return

                begin = result.get("begin")
                finish = result.get("finish")
                if begin:
                    logger.info(
                        "Scanner init begin: %s",
                        json.dumps(begin, ensure_ascii=False, separators=(",", ":")),
                    )
                if finish:
                    finish_cmd = finish.get("cmd", "unknown")
                    logger.info(
                        "Scanner init finish (%s): %s",
                        finish_cmd,
                        json.dumps(finish, ensure_ascii=False, separators=(",", ":")),
                    )
                return
            except (TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
                ScannerService._recover_sdk_after_init_failure(sdk)
                if attempt == SDK_INIT_MAX_ATTEMPTS:
                    break
                logger.warning(
                    "Scanner init timed out or disconnected (attempt %d/%d): %s",
                    attempt,
                    SDK_INIT_MAX_ATTEMPTS,
                    exc,
                )
                time.sleep(SDK_INIT_RETRY_DELAY_SEC)
            except RuntimeError as exc:
                if (
                    COMMAND_STILL_RUNNING_MARKER in str(exc)
                    and attempt < SDK_INIT_MAX_ATTEMPTS
                ):
                    last_error = exc
                    ScannerService._recover_sdk_after_init_failure(sdk)
                    logger.warning(
                        "Scanner init blocked by stale command state (attempt %d/%d): %s",
                        attempt,
                        SDK_INIT_MAX_ATTEMPTS,
                        exc,
                    )
                    time.sleep(SDK_INIT_RETRY_DELAY_SEC)
                    continue
                raise RuntimeError(f"Scanner SDK init failed: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"Scanner SDK init failed: {exc}") from exc

        raise RuntimeError(
            f"Scanner SDK init failed after {SDK_INIT_MAX_ATTEMPTS} attempts"
        ) from last_error

    @staticmethod
    def _release_stale_sdk_session(sdk: Sn3dSdkClient) -> None:
        logger.info("Sending best-effort SDK release before init...")
        result = sdk.release_sdk_best_effort(timeout_sec=SDK_PREAMBLE_RELEASE_TIMEOUT_SEC)
        if result is not None:
            logger.info("Stale SDK session released before init")
        else:
            logger.info(
                "Preamble release skipped or timed out; resetting TCP before init"
            )
        try:
            sdk.reconnect()
            logger.info("Scanner TCP session reset before init")
        except Exception as exc:
            logger.warning("Scanner TCP reset before init failed: %s", exc)
            raise

    @staticmethod
    def _format_connect_failure(host: str, port: int, exc: OSError) -> str:
        errno_value = getattr(exc, "winerror", None) or exc.errno
        refused = isinstance(exc, ConnectionRefusedError) or errno_value in {
            10061,
            111,
        }
        if refused:
            return (
                f"Scanner socket server at {host}:{port} is not accepting connections. "
                "OptimScanProtocolHost may still be running but its SDK socket listener "
                "stopped after the previous Python session — restart OptimScanProtocolHost "
                "or wait a few seconds for host auto-recovery, then use Reconnect to scanner."
            )
        return (
            f"Scanner socket server not available at {host}:{port} "
            f"({exc}) — start OptimScanProtocolHost.exe first or wait for host recovery"
        )

    @staticmethod
    def _connect_with_retry(
        sdk: Sn3dSdkClient,
        host: str,
        port: int,
        max_attempts: int = SDK_CONNECT_MAX_ATTEMPTS,
        retry_delay_sec: float = SDK_CONNECT_RETRY_DELAY_SEC,
    ) -> None:
        logger.info(
            "Waiting for OptimScanProtocolHost / SDK socket server on %s:%d...",
            host,
            port,
        )

        last_error: Optional[OSError] = None
        for attempt in range(1, max_attempts + 1):
            try:
                sdk.connect()
                logger.info("Connected to scanner SDK at %s:%d", host, port)
                return
            except OSError as exc:
                last_error = exc
                if attempt == max_attempts:
                    break
                logger.info(
                    "Scanner socket server not ready (attempt %d/%d): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
                time.sleep(retry_delay_sec)

        message = ScannerService._format_connect_failure(host, port, last_error) if last_error else (
            f"Scanner socket server not available at {host}:{port}"
        )
        raise RuntimeError(message) from last_error

    @staticmethod
    def _apply_scanner_parameters(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        ScannerService._apply_exposure_range(sdk, scanner)
        ScannerService._apply_device_params(sdk, scanner)
        ScannerService._apply_exposure_settings(sdk, scanner)

    @staticmethod
    def _apply_device_params(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        ScannerService._apply_scan_params(sdk, scanner)
        ScannerService._apply_scan_params_bulk(sdk, scanner)
        ScannerService._apply_device_hardware_params(sdk, scanner)

    @staticmethod
    def _apply_device_params_only(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        ScannerService._apply_device_bulk_only(sdk, scanner)
        ScannerService._apply_device_hardware_params(sdk, scanner)

    @staticmethod
    def _bulk_device_pars(scanner: ScannerSettings) -> dict[str, str]:
        device = scanner.device
        wire = encode_exposure_wire(scanner.exposure_settings)
        return {
            "RGBLevel": str(device.rgb_level),
            "preMarker": "true" if device.pre_marker else "false",
            "expType": str(wire.exp_type),
            "expObj": "0",
            "markerExp": str(wire.marker_exp),
            "val1": str(wire.val1),
            "val2": str(wire.val2),
            "val3": str(wire.val3),
            "leftGain": str(device.left_gain),
            "rightGain": str(device.right_gain),
            "maskEnable": "true" if device.mask_enable else "false",
            "maskVal": str(device.mask_val),
        }

    @staticmethod
    def _bulk_scan_pars(
        scanner: ScannerSettings,
        *,
        scan: ScannerScanParams | None = None,
    ) -> dict[str, str]:
        scan_params = scan or scanner.scan
        return {
            "autoCutFace": "true" if scan_params.auto_cut_face else "false",
            "markerRadius": str(scan_params.marker_radius),
            "resolution": str(scan_params.resolution),
            "alignMod": str(scan_params.align_mod),
            "scanMarkers": "true" if scan_params.scan_markers else "false",
            "scanPointCloud": "true" if scan_params.scan_point_cloud else "false",
            "addGlobalMarkers": "true" if scan_params.add_global_markers else "false",
            "monocularScan": "true" if scan_params.monocular_scan else "false",
        }

    @staticmethod
    def _apply_device_bulk_only(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        sdk.send_command(
            Sn3dCommandFactory.set_scan_params_bulk(
                device_pars=ScannerService._bulk_device_pars(scanner),
                scan_pars=ScannerService._bulk_scan_pars(scanner),
            )
        )

    @staticmethod
    def _apply_exposure_settings(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        exposure = scanner.exposure_settings
        wire = encode_exposure_wire(exposure)

        for exp_obj, payload in exposure_sdk_commands(wire, mode=exposure.mode):
            ScannerService._send_camera_exposure(sdk, exp_obj, payload)

    @staticmethod
    def _apply_point_exposure(
        sdk: Sn3dSdkClient,
        point: TrajectoryPoint,
        *,
        per_point_exposure: bool,
        per_point_marker_exposure: bool,
    ) -> None:
        scanner = get_runtime_settings().scanner
        point_vals = PointExposureValues(
            val1=point.exposure_val1,
            val2=point.exposure_val2,
            val3=point.exposure_val3,
            marker_exp=point.exposure_marker_exp,
        )
        commands = build_point_scan_exposure_commands(
            scanner.exposure_settings,
            per_point_exposure=per_point_exposure,
            per_point_marker_exposure=per_point_marker_exposure,
            point_vals=point_vals,
        )
        for exp_obj, payload in commands:
            ScannerService._send_camera_exposure(sdk, exp_obj, payload)

    @staticmethod
    def _send_camera_exposure(
        sdk: Sn3dSdkClient,
        exp_obj: int,
        payload: WireExposurePayload,
    ) -> None:
        target = "markers" if exp_obj == 1 else "point cloud"
        logger.info(
            "Applying camera exposure (%s): exp_type=%d exp_obj=%d marker_exp=%d "
            "val1=%d val2=%d val3=%d",
            target,
            payload.exp_type,
            exp_obj,
            payload.marker_exp,
            payload.val1,
            payload.val2,
            payload.val3,
        )
        sdk.send_command(
            Sn3dCommandFactory.set_camera_exposure(
                exp_type=payload.exp_type,
                exp_obj=exp_obj,
                marker_exp=payload.marker_exp,
                val1=payload.val1,
                val2=payload.val2,
                val3=payload.val3,
            )
        )

    @staticmethod
    def _apply_device_hardware_params(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        device = scanner.device

        sdk.send_command(
            Sn3dCommandFactory.set_background_mask(
                mask_enable=device.mask_enable,
                mask_val=device.mask_val,
            )
        )
        sdk.send_command(
            Sn3dCommandFactory.set_camera_gain(
                camera=0,
                val=device.left_gain,
            )
        )
        sdk.send_command(
            Sn3dCommandFactory.set_camera_gain(
                camera=1,
                val=device.right_gain,
            )
        )
        logger.info(
            "Applying laser_switch=%s (work_range=%d)",
            device.laser_switch,
            scanner.work_range,
        )
        sdk.send_command(
            Sn3dCommandFactory.set_laser_switch(
                enable=device.laser_switch,
                work_range=scanner.work_range,
            )
        )

    @staticmethod
    def _apply_scan_params_bulk(
        sdk: Sn3dSdkClient,
        scanner: ScannerSettings,
        *,
        scan: ScannerScanParams | None = None,
    ) -> None:
        sdk.send_command(
            Sn3dCommandFactory.set_scan_params_bulk(
                device_pars=ScannerService._bulk_device_pars(scanner),
                scan_pars=ScannerService._bulk_scan_pars(scanner, scan=scan),
            )
        )

    @staticmethod
    def _apply_exposure_range(sdk: Sn3dSdkClient, scanner: ScannerSettings) -> None:
        exposure = scanner.exposure_range
        sdk.send_command(
            Sn3dCommandFactory.set_exposure_range(
                center_x=exposure.center_x,
                center_y=exposure.center_y,
                radius=exposure.radius,
            )
        )

    @staticmethod
    def _apply_scan_params(
        sdk: Sn3dSdkClient,
        scanner: ScannerSettings,
        *,
        scan: ScannerScanParams | None = None,
    ) -> None:
        scan_params = scan or scanner.scan
        logger.info(
            "Applying scan params: marker_radius=%d resolution=%d align_mod=%d "
            "scan_markers=%s scan_point_cloud=%s",
            scan_params.marker_radius,
            scan_params.resolution,
            scan_params.align_mod,
            scan_params.scan_markers,
            scan_params.scan_point_cloud,
        )
        sdk.send_command(
            Sn3dCommandFactory.set_scan_params(
                align_mod=scan_params.align_mod,
                scan_markers=scan_params.scan_markers,
                scan_point_cloud=scan_params.scan_point_cloud,
                add_global_markers=scan_params.add_global_markers,
                monocular_scan=scan_params.monocular_scan,
                resolution=scan_params.resolution,
                marker_radius=scan_params.marker_radius,
                scan_obj=scan_params.scan_obj,
            )
        )


scanner_service = ScannerService()
