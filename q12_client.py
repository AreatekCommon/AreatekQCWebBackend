from __future__ import annotations

import json
import math
import socket
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional


def _log_sdk_trace(event: str, **fields: Any) -> None:
    try:
        from app.scanner.sdk_tcp_trace import log_sdk_trace

        log_sdk_trace(event, **fields)
    except ImportError:
        print(f"[SDK-TRACE] {event}: {fields}")

SNSDK_ERR_SCANFAILED = 9
SNSDK_ERR_MARKER_TRACK_FAILED = 55
SNSDK_ERR_MARKER_ALIGN_ERROR = 56


@dataclass
class SdkFinishErrorInfo:
    ret_code: int | None
    detail: str
    result: str | None = None
    error_code_hex: str | None = None
    finish: Dict[str, Any] | None = None


class SdkCommandError(RuntimeError):
    def __init__(
        self,
        command: str,
        ret_code: int | None = None,
        detail: str = "",
        *,
        begin: Dict[str, Any] | None = None,
        finish: Dict[str, Any] | None = None,
        result: str | None = None,
        error_code_hex: str | None = None,
    ) -> None:
        self.command = command
        self.ret_code = ret_code
        self.detail = detail
        self.begin = begin
        self.finish = finish
        self.result = result
        self.error_code_hex = error_code_hex
        message = f"SDK command '{command}' failed"
        if ret_code is not None:
            message = f"{message} (retCode={ret_code})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)

    @property
    def is_no_global_markers(self) -> bool:
        return (self.result or "").strip().upper() == "NO_GLOBAL_MARKERS"

    @property
    def is_marker_align_error(self) -> bool:
        return self.ret_code == SNSDK_ERR_MARKER_ALIGN_ERROR

    @property
    def is_marker_track_failed(self) -> bool:
        return self.ret_code == SNSDK_ERR_MARKER_TRACK_FAILED

    @property
    def is_scan_exception(self) -> bool:
        finish_cmd = (self.finish or {}).get("cmd")
        return (
            (self.result or "").strip().lower() == "scanexception"
            or finish_cmd == "scanException"
        )

    @property
    def is_alignment_retryable(self) -> bool:
        if self.command != "startScan":
            return False
        if self.is_no_global_markers:
            return False
        return (
            self.is_marker_align_error
            or self.is_marker_track_failed
            or self.is_scan_exception
        )

    def user_message(self) -> str:
        if self.is_no_global_markers:
            return (
                "Marker framework P3 contains no global markers (retCode 29). "
                "Export a reference/framework P3 from OptimScan with global markers visible "
                "in the project—not a scan-only export."
            )
        if self.is_marker_align_error:
            return (
                "Single-slice marker alignment failed (retCode 56). "
                "Ensure enough markers are visible in the scanner view, marker radius matches "
                "physical stickers, and alignment mode/framework import match your workflow."
            )
        if self.is_marker_track_failed:
            return (
                "Scan could not start — marker tracking failed (retCode 55). "
                "Ensure enough markers are visible in the scanner view at the current turntable angle, "
                "and that marker radius matches physical stickers."
            )
        if self.command == "startScan" and self.is_scan_exception:
            return (
                "Scan failed (scanException). Check marker visibility in the current pose, "
                "marker radius setting, and whether global-marker framework import is enabled "
                "when using align mode Global Markers."
            )
        return str(self)

    def to_detail_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "ret_code": self.ret_code,
            "error_code_hex": self.error_code_hex,
            "result": self.result,
            "message": str(self),
            "finish_json": (
                json.dumps(self.finish, ensure_ascii=False, separators=(",", ":"))
                if self.finish
                else None
            ),
            "begin_json": (
                json.dumps(self.begin, ensure_ascii=False, separators=(",", ":"))
                if self.begin
                else None
            ),
        }


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_sdk_error_code(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text or text.lower() in {"0x", "0x0"}:
        return 0

    try:
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text)
    except ValueError:
        return None


def _is_init_version_warning(
    finish: Dict[str, Any] | None,
    *,
    command: str | None = None,
) -> bool:
    if not finish or command != "init":
        return False

    ret_code = _coerce_int(finish.get("retCode"))
    if ret_code is None:
        ret_code = _coerce_int(finish.get("ret_code"))
    if ret_code == 1:
        return True

    result_value = finish.get("result")
    result_str = str(result_value).strip().lower() if result_value is not None else ""
    result_failed = result_str in {"failed", "failure", "error"}

    erro_code_raw = finish.get("erroCode")
    if erro_code_raw is None:
        erro_code_raw = finish.get("errorCode")
    erro_code_parsed = _parse_sdk_error_code(erro_code_raw)

    return result_failed and erro_code_parsed == 1


def _scan_finish_error(finish: Dict[str, Any] | None) -> SdkFinishErrorInfo | None:
    if not finish:
        return None

    cmd = finish.get("cmd")
    if cmd == "scanFinish":
        return None

    if cmd != "scanException" and not finish.get("isScanException"):
        return None

    exception_code = _coerce_int(finish.get("exception"))
    ret_code = _coerce_int(finish.get("retCode"))
    if ret_code is None:
        ret_code = _coerce_int(finish.get("ret_code"))

    failure_code = ret_code if ret_code not in (None, 0) else exception_code
    if failure_code is None:
        failure_code = -1

    detail_parts = ["cmd=scanException"]
    if exception_code is not None:
        detail_parts.append(f"exception={exception_code}")
    if ret_code is not None and ret_code != 0:
        detail_parts.append(f"retCode={ret_code}")

    finish_json = json.dumps(finish, ensure_ascii=False, separators=(",", ":"))
    detail_parts.append(f"finish={finish_json}")

    return SdkFinishErrorInfo(
        ret_code=failure_code,
        detail="; ".join(detail_parts),
        result="scanException",
        finish=finish,
    )


def _sdk_finish_error(
    finish: Dict[str, Any] | None,
    *,
    command: str | None = None,
) -> SdkFinishErrorInfo | None:
    if not finish:
        return None

    if _is_init_version_warning(finish, command=command):
        return None

    if command == "startScan" or (isinstance(finish.get("cmd"), str) and finish.get("cmd") in {
        "scanFinish",
        "scanException",
    }):
        scan_error = _scan_finish_error(finish)
        if scan_error is not None:
            return scan_error

    ret_code = _coerce_int(finish.get("retCode"))
    if ret_code is None:
        ret_code = _coerce_int(finish.get("ret_code"))

    error_code = _coerce_int(finish.get("_error"))
    success_flag = finish.get("_success")

    erro_code_raw = finish.get("erroCode")
    if erro_code_raw is None:
        erro_code_raw = finish.get("errorCode")
    erro_code_parsed = _parse_sdk_error_code(erro_code_raw)
    error_code_hex = str(erro_code_raw).strip() if erro_code_raw is not None else None

    result_value = finish.get("result")
    result_str = str(result_value).strip() if result_value is not None else None
    result_failed = result_str is not None and result_str.lower() in {
        "failed",
        "failure",
        "error",
        "no_global_markers",
    }

    text_detail = str(
        finish.get("_detail") or finish.get("detail") or finish.get("message") or ""
    ).strip()

    failure_code: int | None = None

    if ret_code is not None and ret_code != 0:
        failure_code = ret_code
    elif error_code is not None and error_code != 0:
        failure_code = error_code
    elif success_flag is not None and success_flag in (0, False, "0"):
        failure_code = error_code if error_code is not None else -1
    elif result_failed:
        if erro_code_parsed is not None and erro_code_parsed != 0:
            failure_code = erro_code_parsed
        else:
            failure_code = -1
    elif erro_code_parsed is not None and erro_code_parsed != 0:
        failure_code = erro_code_parsed

    if failure_code is None:
        return None

    detail_parts: list[str] = []
    if result_str:
        detail_parts.append(f"result={result_str}")
    if error_code_hex and erro_code_parsed is not None:
        detail_parts.append(f"erroCode={error_code_hex} (decimal {erro_code_parsed})")
    elif failure_code is not None:
        detail_parts.append(f"code={failure_code}")
    if text_detail:
        detail_parts.append(text_detail)

    finish_json = json.dumps(finish, ensure_ascii=False, separators=(",", ":"))
    detail_parts.append(f"finish={finish_json}")

    return SdkFinishErrorInfo(
        ret_code=failure_code,
        detail="; ".join(detail_parts),
        result=result_str,
        error_code_hex=error_code_hex if erro_code_parsed not in (None, 0) else None,
        finish=finish,
    )


class CommandKey(Enum):
    INIT = "1"
    RELEASE = "2"
    CREATE_SOLUTION = "3"
    SET_CAMERA_EXPOSURE = "4"
    SET_EXPOSURE_RANGE = "5"
    SET_BACKGROUND_MASK = "6"
    SET_CAMERA_GAIN = "7"
    SET_SCAN_PARAMS = "8"
    START_SCAN = "9"
    GLOBAL_OPT = "10"
    GENERATE_MESH = "11"
    SAVE_DATA = "12"
    SHOW_COMMANDS = "13"
    EXIT = "0"


@dataclass(frozen=True)
class SdkConfig:
    host: str = "127.0.0.1"
    port: int = 3001
    timeout_sec: float = 30.0
    buffer_size: int = 65536
    receiver_poll_sec: float = 0.2


class Transport(ABC):
    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def send_json(self, payload: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        pass

    @abstractmethod
    def set_transport_disconnect_callback(
        self,
        callback: Optional[Callable[[], None]],
    ) -> None:
        pass


class TcpJsonTransport(Transport):
    def __init__(self, config: SdkConfig) -> None:
        self._config = config
        self._socket: Optional[socket.socket] = None
        self._recv_buffer = ""
        self._stop_event = threading.Event()
        self._receiver_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._message_handler: Optional[Callable[[Dict[str, Any]], None]] = None
        self._transport_disconnect_callback: Optional[Callable[[], None]] = None

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._message_handler = handler

    def set_transport_disconnect_callback(
        self,
        callback: Optional[Callable[[], None]],
    ) -> None:
        self._transport_disconnect_callback = callback

    def _notify_transport_disconnect(self) -> None:
        callback = self._transport_disconnect_callback
        if callback is not None:
            callback()

    def connect(self) -> None:
        if self._socket is not None:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._config.receiver_poll_sec)
        sock.connect((self._config.host, self._config.port))

        self._socket = sock
        self._stop_event.clear()
        self._receiver_thread = threading.Thread(
            target=self._receive_loop,
            name="sn3d-json-receiver",
            daemon=True,
        )
        self._receiver_thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()

        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

        if self._receiver_thread is not None and self._receiver_thread.is_alive():
            self._receiver_thread.join(timeout=1.0)

        self._receiver_thread = None
        self._recv_buffer = ""

    def send_json(self, payload: Dict[str, Any]) -> None:
        if self._socket is None:
            raise ConnectionError("Transport is not connected")

        message = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._write_lock:
            self._socket.sendall(message.encode("utf-8"))

    def _receive_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._socket is None:
                return

            try:
                data = self._socket.recv(self._config.buffer_size)
                if not data:
                    _log_sdk_trace("rx_connection_closed")
                    if not self._stop_event.is_set():
                        self._notify_transport_disconnect()
                    return

                self._recv_buffer += data.decode("utf-8", errors="replace")
                self._drain_complete_json_messages()

            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop_event.is_set():
                    _log_sdk_trace("rx_socket_error", error=str(exc))
                    self._notify_transport_disconnect()
                return
            except Exception as exc:
                _log_sdk_trace("rx_receive_error", error=str(exc))
                if not self._stop_event.is_set():
                    self._notify_transport_disconnect()
                return

    def _drain_complete_json_messages(self) -> None:
        while True:
            extracted = self._extract_one_json_object()
            if extracted is None:
                return

            message = self._parse_message(extracted)
            self._print_incoming(message)

            if self._message_handler is not None:
                self._message_handler(message)

    def _extract_one_json_object(self) -> Optional[str]:
        start = self._recv_buffer.find("{")
        if start == -1:
            self._recv_buffer = ""
            return None

        depth = 0
        in_string = False
        escape = False

        for index in range(start, len(self._recv_buffer)):
            char = self._recv_buffer[index]

            if escape:
                escape = False
                continue

            if char == "\\":
                escape = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    raw = self._recv_buffer[start:index + 1]
                    self._recv_buffer = self._recv_buffer[index + 1:]
                    return raw.strip()

        return None

    @staticmethod
    def _parse_message(raw_message: str) -> Dict[str, Any]:
        try:
            return json.loads(raw_message)
        except json.JSONDecodeError:
            return {"raw_response": raw_message}

    @staticmethod
    def _print_incoming(message: Dict[str, Any]) -> None:
        _log_sdk_trace(
            "incoming_json",
            message=message,
        )


class Sn3dCommandFactory:
    @staticmethod
    def init(process_path: str = "C:/Program Files/Shining3D/OptimScan Q/Sn3DProcessManager.exe") -> Dict[str, Any]:
        return {
            "cmd": "init",
            "processPath": process_path,
        }

    @staticmethod
    def release() -> Dict[str, Any]:
        return {"cmd": "release"}

    @staticmethod
    def create_solution(
        sln_dir_path: str = r"C:\Shining Projects",
        sln_name: str = "project",
        work_range: int = 1,
        need_limit: int = 2,
    ) -> Dict[str, Any]:
        return {
            "cmd": "createSln",
            "szSlnDirPath": sln_dir_path,
            "slnName": sln_name,
            "workRange": work_range,
            "iNeedLimit": need_limit,
        }

    @staticmethod
    def load_framework(path: str) -> Dict[str, Any]:
        return {
            "cmd": "loadFramework",
            "path": path,
        }

    @staticmethod
    def set_camera_exposure(
        exp_type: int = 1,
        exp_obj: int = 0,
        marker_exp: int = 10,
        val1: int = 45,
        val2: int = 1,
        val3: int = 1,
    ) -> Dict[str, Any]:
        return {
            "cmd": "setCameraExp",
            "expType": exp_type,
            "expObj": exp_obj,
            "markerExp": marker_exp,
            "val1": val1,
            "val2": val2,
            "val3": val3,
        }

    @staticmethod
    def set_exposure_range(
        center_x: int = 1024,
        center_y: int = 750,
        radius: int = 100,
    ) -> Dict[str, Any]:
        return {
            "cmd": "setExpRange",
            "centerX": center_x,
            "centerY": center_y,
            "radius": radius,
        }

    @staticmethod
    def set_background_mask(mask_enable: bool = False, mask_val: int = 30) -> Dict[str, Any]:
        return {
            "cmd": "setMaskBackGround",
            "maskEnable": mask_enable,
            "maskVal": mask_val,
        }

    @staticmethod
    def set_camera_gain(camera: int = 0, val: float = 0.1) -> Dict[str, Any]:
        return {
            "cmd": "setCamerGain",
            "camera": camera,
            "val": val,
        }

    @staticmethod
    def set_laser_switch(enable: bool, work_range: int = 0) -> Dict[str, Any]:
        return {
            "cmd": "setLaserSwitch",
            "enable": enable,
            "workRange": work_range,
        }

    @staticmethod
    def set_scan_params_bulk(
        device_pars: dict[str, object],
        scan_pars: dict[str, object],
    ) -> Dict[str, Any]:
        return {
            "cmd": "setScanParams",
            "devicePars": device_pars,
            "scanPars": scan_pars,
        }

    @staticmethod
    def set_scan_params(
        align_mod: int = 4,
        scan_markers: bool = True,
        scan_point_cloud: bool = False,
        add_global_markers: bool = True,
        monocular_scan: bool = False,
        resolution: int = 3,
        marker_radius: int = 7,
        scan_obj: int = 1,
    ) -> Dict[str, Any]:
        return {
            "cmd": "setScanParas",
            "alignMod": align_mod,
            "scanMarkers": scan_markers,
            "scanPointCloud": scan_point_cloud,
            "addGlobalMarkers": add_global_markers,
            "monocularScan": monocular_scan,
            "resolution": resolution,
            "markerRadius": marker_radius,
            "scanObj": scan_obj,
        }

    @staticmethod
    def start_scan() -> Dict[str, Any]:
        return {"cmd": "startScan"}

    @staticmethod
    def enter_calibration(
        big_range: int = 0,
        factory_mode: int = 0,
        read_xml_mode: int = 0,
    ) -> Dict[str, Any]:
        return {
            "cmd": "enterCalib",
            "bigRange": big_range,
            "factoryMode": factory_mode,
            "readXmlMode": read_xml_mode,
        }

    @staticmethod
    def capture_calibration() -> Dict[str, Any]:
        return {"cmd": "captureCali"}

    @staticmethod
    def prev_calibration() -> Dict[str, Any]:
        return {"cmd": "prevCali"}

    @staticmethod
    def exit_calibration() -> Dict[str, Any]:
        return {"cmd": "exitCali"}

    @staticmethod
    def global_optimization() -> Dict[str, Any]:
        return {"cmd": "globalOpt"}

    @staticmethod
    def mesh(
        mesh_type: int = 0,
        unwatertight_detail: int = 0,
        depth: int = 0,
        filter_level: int = 1,
        smooth_level: int = 1,
        remove_small: int = 1,
        max_face: bool = True,
        face_limit: int = 20000000,
        fill_small_hole: bool = True,
        small_hole_perimeter: int = 10,
        neighbourhood: int = 3,
        spike_sensitivity: bool = True,
        fill_marker_hole: bool = True,
        border_opt: bool = True,
        need_thin_obj_mesh: bool = False,
    ) -> Dict[str, Any]:
        return {
            "cmd": "mesh",
            "meshType": mesh_type,
            "unwatertightDetail": unwatertight_detail,
            "depth": depth,
            "filterLevel": filter_level,
            "smoothLevel": smooth_level,
            "removeSmall": remove_small,
            "maxFace": max_face,
            "faceLimit": face_limit,
            "fillSmallHole": fill_small_hole,
            "smallHolePerimeter": small_hole_perimeter,
            "neighbourhood": neighbourhood,
            "spikeSensitivity": spike_sensitivity,
            "fillMarkerHole": fill_marker_hole,
            "borderOpt": border_opt,
            "needThinObjMesh": need_thin_obj_mesh,
        }

    @staticmethod
    def save_data(
        save_type: str = "stl",
        save_path: str = r"C:\Users\Areatek\Desktop\scans\test.stl",
        name: str = "test.stl",
    ) -> Dict[str, Any]:
        return {
            "cmd": "saveData",
            "saveType": save_type,
            "savePath": save_path,
            "name": name,
        }


class Sn3dSdkClient:
    def __init__(self, transport: Transport, timeout_sec: float = 30.0) -> None:
        self._transport = transport
        self._timeout_sec = timeout_sec
        self._is_connected = False
        self._sdk_initialized = False
        self._command_in_progress: Optional[str] = None
        self._command_finished_event = threading.Event()
        self._last_begin_message: Optional[Dict[str, Any]] = None
        self._last_finish_message: Optional[Dict[str, Any]] = None
        self._state_lock = threading.Lock()
        self._transport.set_message_handler(self._handle_incoming_message)
        self._device_offline_callback: Optional[Callable[[], None]] = None
        self._transport_disconnect_callback: Optional[Callable[[], None]] = None

    @property
    def is_sdk_initialized(self) -> bool:
        with self._state_lock:
            return self._sdk_initialized

    def set_device_offline_callback(self, callback: Optional[Callable[[], None]]) -> None:
        self._device_offline_callback = callback

    def set_transport_disconnect_callback(
        self,
        callback: Optional[Callable[[], None]],
    ) -> None:
        self._transport_disconnect_callback = callback

        if callback is None:
            self._transport.set_transport_disconnect_callback(None)
            return

        def wrapped() -> None:
            self._is_connected = False
            with self._state_lock:
                self._sdk_initialized = False
                self._command_in_progress = None
                self._command_finished_event.set()

            user_callback = self._transport_disconnect_callback
            if user_callback is not None:
                user_callback()

        self._transport.set_transport_disconnect_callback(wrapped)

    def connect(self) -> None:
        self._transport.connect()
        self._is_connected = True

    def disconnect(self) -> None:
        self._transport.disconnect()
        self._is_connected = False
        with self._state_lock:
            self._sdk_initialized = False

    def reconnect(self) -> None:
        self.disconnect()
        self.connect()

    def reset_command_state(self) -> None:
        with self._state_lock:
            self._command_in_progress = None
            self._last_begin_message = None
            self._last_finish_message = None
            self._command_finished_event.set()

    def send_command(
        self,
        payload: Dict[str, Any],
        wait_for_finish: bool = True,
        *,
        timeout_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not self._is_connected:
            raise ConnectionError("SDK client is not connected")

        command_name = payload.get("cmd")
        if not command_name:
            raise ValueError("Payload must contain 'cmd'")

        with self._state_lock:
            if self._command_in_progress is not None:
                raise RuntimeError(
                    f"Команда '{self._command_in_progress}' еще выполняется"
                )
            self._command_in_progress = command_name
            self._command_finished_event.clear()
            self._last_begin_message = None
            self._last_finish_message = None

        _log_sdk_trace("command_sent", command=command_name, payload=payload)
        self._transport.send_json(payload)

        if not wait_for_finish:
            return {"sent": True, "cmd": command_name}

        command_timeout_sec = (
            self._timeout_sec if timeout_sec is None else timeout_sec
        )
        wait_timeout = (
            None if math.isinf(command_timeout_sec) else command_timeout_sec
        )
        finished = self._command_finished_event.wait(timeout=wait_timeout)
        if not finished:
            with self._state_lock:
                running_command = self._command_in_progress
                begin_message = self._last_begin_message
                self._command_in_progress = None
                self._command_finished_event.set()
            raise TimeoutError(
                f"Не дождались сообщения завершения для '{running_command}' за {command_timeout_sec} сек. "
                f"Последний begin: {json.dumps(begin_message, ensure_ascii=False) if begin_message else 'None'}"
            )

        with self._state_lock:
            result = {
                "cmd": command_name,
                "begin": self._last_begin_message,
                "finish": self._last_finish_message,
            }

        error_info = _sdk_finish_error(result.get("finish"), command=command_name)
        if error_info is not None:
            raise SdkCommandError(
                command_name,
                error_info.ret_code,
                error_info.detail,
                begin=result.get("begin"),
                finish=result.get("finish"),
                result=error_info.result,
                error_code_hex=error_info.error_code_hex,
            )

        if command_name == "init":
            finish = result.get("finish") or {}
            if _is_init_version_warning(finish, command="init"):
                _log_sdk_trace(
                    "init_version_warning",
                    detail="retCode/erroCode=1, continuing",
                )
            with self._state_lock:
                self._sdk_initialized = True

        return result

    def initialize_sdk(
        self,
        process_path: str = "C:/Program Files/Shining3D/OptimScan Q/Sn3DProcessManager.exe",
    ) -> Dict[str, Any]:
        if self.is_sdk_initialized:
            _log_sdk_trace("init_skipped", reason="already_initialized")
            return {"cmd": "init", "skipped": True}

        return self.send_command(Sn3dCommandFactory.init(process_path))

    def release_sdk(self, *, timeout_sec: Optional[float] = None) -> Dict[str, Any]:
        try:
            return self.send_command(
                Sn3dCommandFactory.release(),
                timeout_sec=timeout_sec,
            )
        finally:
            with self._state_lock:
                self._sdk_initialized = False

    def release_sdk_best_effort(
        self,
        *,
        timeout_sec: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        try:
            return self.release_sdk(timeout_sec=timeout_sec)
        except Exception as exc:
            _log_sdk_trace("release_best_effort_failed", error=str(exc))
            self.reset_command_state()
            with self._state_lock:
                self._sdk_initialized = False
            return None

    def is_command_in_progress(self) -> bool:
        with self._state_lock:
            return self._command_in_progress is not None

    def current_command(self) -> Optional[str]:
        with self._state_lock:
            return self._command_in_progress

    def wait_current_command_finished(self, timeout: Optional[float] = None) -> bool:
        return self._command_finished_event.wait(timeout=timeout)

    def _handle_incoming_message(self, message: Dict[str, Any]) -> None:
        cmd_value = message.get("cmd")
        if not isinstance(cmd_value, str):
            return

        if cmd_value == "deviceStatus" and message.get("offline") is True:
            if self._device_offline_callback is not None:
                self._device_offline_callback()
            return

        with self._state_lock:
            if self._command_in_progress is None:
                return

            expected_begin = f"{self._command_in_progress}Begin"
            expected_finish = f"{self._command_in_progress}Finish"

            if cmd_value == expected_begin:
                self._last_begin_message = message
                _log_sdk_trace("command_begin", cmd=expected_begin)
                return

            if cmd_value == expected_finish:
                self._last_finish_message = message
                finished_command = self._command_in_progress
                self._command_in_progress = None
                self._command_finished_event.set()
                _log_sdk_trace(
                    "command_finish",
                    cmd=expected_finish,
                    command=finished_command,
                )
                return

            if self._command_in_progress == "loadFramework" and cmd_value == "loadP3Finish":
                self._last_finish_message = message
                self._command_in_progress = None
                self._command_finished_event.set()
                _log_sdk_trace("command_finish", cmd="loadP3Finish", command="loadFramework")
                return

            if self._command_in_progress == "init" and cmd_value == "showMainView":
                self._last_finish_message = message
                self._command_in_progress = None
                self._command_finished_event.set()
                _log_sdk_trace("command_finish", cmd="showMainView", command="init")
                return

            if self._command_in_progress == "startScan" and cmd_value in (
                "scanFinish",
                "scanException",
            ):
                self._last_finish_message = message
                finished_command = self._command_in_progress
                self._command_in_progress = None
                self._command_finished_event.set()
                _log_sdk_trace(
                    "command_finish",
                    cmd=cmd_value,
                    command=finished_command,
                )
                return

    @staticmethod
    def command_menu() -> Dict[str, Dict[str, Any]]:
        return {
            CommandKey.INIT.value: {
                "title": "Initialize SDK",
                "payload": Sn3dCommandFactory.init(),
            },
            CommandKey.RELEASE.value: {
                "title": "Release SDK",
                "payload": Sn3dCommandFactory.release(),
            },
            CommandKey.CREATE_SOLUTION.value: {
                "title": "Create Solution",
                "payload": Sn3dCommandFactory.create_solution(),
            },
            CommandKey.SET_CAMERA_EXPOSURE.value: {
                "title": "Set Exposure Parameters",
                "payload": Sn3dCommandFactory.set_camera_exposure(),
            },
            CommandKey.SET_EXPOSURE_RANGE.value: {
                "title": "Set Auto Exposure Region",
                "payload": Sn3dCommandFactory.set_exposure_range(),
            },
            CommandKey.SET_BACKGROUND_MASK.value: {
                "title": "Configure Background Mask",
                "payload": Sn3dCommandFactory.set_background_mask(),
            },
            CommandKey.SET_CAMERA_GAIN.value: {
                "title": "Set Camera Gain",
                "payload": Sn3dCommandFactory.set_camera_gain(),
            },
            CommandKey.SET_SCAN_PARAMS.value: {
                "title": "Set Scan Parameters",
                "payload": Sn3dCommandFactory.set_scan_params(),
            },
            CommandKey.START_SCAN.value: {
                "title": "Scan",
                "payload": Sn3dCommandFactory.start_scan(),
            },
            CommandKey.GLOBAL_OPT.value: {
                "title": "Global Optimization",
                "payload": Sn3dCommandFactory.global_optimization(),
            },
            CommandKey.GENERATE_MESH.value: {
                "title": "Generate Mesh",
                "payload": Sn3dCommandFactory.mesh(),
            },
            CommandKey.SAVE_DATA.value: {
                "title": "Save Data",
                "payload": Sn3dCommandFactory.save_data(),
            },
            CommandKey.SHOW_COMMANDS.value: {
                "title": "Show command list",
                "payload": {},
            },
            CommandKey.EXIT.value: {
                "title": "Exit",
                "payload": {},
            },
        }

    @classmethod
    def run_console_demo(cls) -> None:
        config = SdkConfig(host="127.0.0.1", port=3001)
        transport = TcpJsonTransport(config)
        client = cls(transport, timeout_sec=config.timeout_sec)
        menu = cls.command_menu()

        try:
            client.connect()
            print(f"Connected to {config.host}:{config.port}")
            print("Фоновый приемник запущен: все входящие JSON будут печататься автоматически")
            cls._print_menu(menu)

            while True:
                if client.is_command_in_progress():
                    running = client.current_command()
                    print(f"\n[LOCK] Ожидание {running}Finish... ввод новых команд временно заблокирован")
                    client.wait_current_command_finished()
                    continue

                user_input = input("\nВведите номер команды: ").strip()

                if user_input == CommandKey.EXIT.value:
                    print("Выход из консольного клиента")
                    break

                if user_input == CommandKey.SHOW_COMMANDS.value:
                    cls._print_menu(menu)
                    continue

                command_info = menu.get(user_input)
                if command_info is None:
                    print("Неизвестная команда. Введите 13 для показа списка.")
                    continue

                print("\n>>> Отправка:")
                print(json.dumps(command_info["payload"], ensure_ascii=False, indent=2))

                try:
                    response = client.send_command(command_info["payload"])
                    print("\n[RESULT] Команда завершилась:")
                    print(json.dumps(response, ensure_ascii=False, indent=2))
                except Exception as exc:
                    print(f"Ошибка при отправке команды: {exc}")

        except Exception as exc:
            print(f"Ошибка подключения: {exc}")
        finally:
            try:
                if client._is_connected:
                    client.disconnect()
                    print("Соединение закрыто")
            except Exception as exc:
                print(f"Ошибка при закрытии соединения: {exc}")

    @staticmethod
    def _print_menu(menu: Dict[str, Dict[str, Any]]) -> None:
        print("\nСписок команд:")
        for key, value in menu.items():
            print(f"{key}. {value['title']}")


if __name__ == "__main__":
    Sn3dSdkClient.run_console_demo()
