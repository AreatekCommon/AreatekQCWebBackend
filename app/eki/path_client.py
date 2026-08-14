from __future__ import annotations

import glob
import json
import os
import socket
import threading
import time
from typing import Optional

import xml.etree.ElementTree as ET

from app.core.logger import get_logger
from app.core.runtime_settings_store import get_runtime_settings
from app.eki.constants import (
    DEFAULT_CONNECT_TIMEOUT_S,
    DEFAULT_HEARTBEAT_PERIOD_S,
    DEFAULT_PATH_ROBOT_PORT,
    DEFAULT_RECV_TIMEOUT_S,
    DEFAULT_TURNTABLE_PORT,
    PATH_STATUS_IDLE,
    PATH_STATUS_MOVING,
    ROBOT_STATUS_ROOT,
)
from app.eki.messages import AxisAngleCommand, TrajectoryPoint, TurnCommandMessage
from app.eki.path_parser import parse_positions_json
from app.eki.turntable_units import turntable_wire_display_value
from app.eki.xml_codec import (
    build_axis_angle_xml,
    build_turn_command_xml,
    parse_path_robot_status,
)
from app.eki.xml_stream import drain_xml_packets


class KukaEkiPathClient:
    STATUS_IDLE = PATH_STATUS_IDLE
    STATUS_MOVING = PATH_STATUS_MOVING

    def __init__(
        self,
        robot_ip: str,
        robot_port: int = DEFAULT_PATH_ROBOT_PORT,
        turntable_port: int = DEFAULT_TURNTABLE_PORT,
        heartbeat_period: float = DEFAULT_HEARTBEAT_PERIOD_S,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT_S,
        json_path: Optional[str] = None,
        allowed_point_types: Optional[set[str] | list[str]] = None,
    ) -> None:
        self.robot_ip = robot_ip
        self.robot_port = robot_port
        self.turntable_port = turntable_port
        self.heartbeat_period = heartbeat_period
        self.recv_timeout = recv_timeout
        self.json_path = json_path
        self.allowed_point_types = set(allowed_point_types) if allowed_point_types else None

        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.turn_sock: Optional[socket.socket] = None
        self.turn_connected = False

        self.stop_event = threading.Event()
        self._motion_cancel_event = threading.Event()
        self.tx_thread: Optional[threading.Thread] = None
        self.rx_thread: Optional[threading.Thread] = None
        self.turn_tx_thread: Optional[threading.Thread] = None
        self.turn_rx_thread: Optional[threading.Thread] = None

        self.lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)

        self.robot_status: Optional[int] = None
        self.current_target = [0.0] * 7
        self.pending_execute = False
        self._last_logged_turn_wire: Optional[float] = None
        self._execute_sent_at: Optional[float] = None
        self._execute_awaiting_idle: bool = False
        self._turntable_ready_for_execute: bool = False
        self._dispatch_started_at: Optional[float] = None
        self._turntable_ready_at: Optional[float] = None
        self._robot_tx_wake = threading.Event()
        self._turn_tx_wake = threading.Event()
        self.points: list[TrajectoryPoint] = []
        self.current_point_idx = 0

    def load_points_from_json(self, json_path: Optional[str] = None) -> None:
        path = json_path or self.json_path
        if not path:
            raise ValueError("JSON path is not specified")

        with open(path, "r", encoding="utf-8-sig") as file:
            data = json.load(file)

        points = parse_positions_json(data, allowed_point_types=self.allowed_point_types)

        self.points = points
        self.current_point_idx = 0
        self.json_path = path

        if self.points:
            first_point = self.points[0]
            self.current_target = first_point.axes + [first_point.a7]
            self._logger.info(
                "Initial target set to idx=%s axes=%s A7=%s",
                first_point.index,
                first_point.axes,
                first_point.a7,
            )

        self._logger.info("Loaded %d points from %s", len(self.points), path)

    @staticmethod
    def find_latest_json(folder: str) -> str:
        pattern = os.path.join(folder, "*.json")
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"No JSON files found in {folder}")
        files.sort(key=os.path.getmtime, reverse=True)
        return files[0]

    def connect(self, max_attempts: int | None = None) -> None:
        if self.connected:
            return

        attempts = 0
        while not self.stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(DEFAULT_CONNECT_TIMEOUT_S)
                sock.connect((self.robot_ip, self.robot_port))
                sock.settimeout(self.recv_timeout)

                with self.lock:
                    self.sock = sock
                    self.connected = True
                    self.robot_status = None
                    self.pending_execute = False

                self._logger.info("Connected to %s:%d", self.robot_ip, self.robot_port)
                return
            except Exception as exc:
                attempts += 1
                self._logger.warning("Connect failed: %s", exc)
                self._safe_close()
                if max_attempts is not None and attempts >= max_attempts:
                    raise RuntimeError(
                        f"Robot path connect failed after {max_attempts} attempts: {exc}"
                    ) from exc
                time.sleep(1.0)

    def _connect_turntable(self, max_attempts: int | None = None) -> None:
        if self.turn_connected:
            return

        attempts = 0
        while not self.stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(DEFAULT_CONNECT_TIMEOUT_S)
                sock.connect((self.robot_ip, self.turntable_port))
                sock.settimeout(self.recv_timeout)

                with self.turn_lock:
                    self.turn_sock = sock
                    self.turn_connected = True

                self._logger.info("Turntable connected to %s:%d", self.robot_ip, self.turntable_port)
                return
            except Exception as exc:
                attempts += 1
                self._logger.warning("Turntable connect failed: %s", exc)
                self._safe_close_turn()
                if max_attempts is not None and attempts >= max_attempts:
                    raise RuntimeError(
                        f"Turntable connect failed after {max_attempts} attempts: {exc}"
                    ) from exc
                time.sleep(1.0)

    def _ensure_path_threads(self) -> None:
        if self.tx_thread is not None and self.tx_thread.is_alive():
            return

        self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True, name="EkiPathTx")
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name="EkiPathRx")
        self.tx_thread.start()
        self.rx_thread.start()

    def _ensure_turntable_threads(self) -> None:
        if self.turn_tx_thread is not None and self.turn_tx_thread.is_alive():
            return

        self.turn_tx_thread = threading.Thread(
            target=self._turn_tx_loop,
            daemon=True,
            name="EkiTurnTx",
        )
        self.turn_rx_thread = threading.Thread(
            target=self._turn_rx_loop,
            daemon=True,
            name="EkiTurnRx",
        )
        self.turn_tx_thread.start()
        self.turn_rx_thread.start()

    def start(self, max_attempts: int | None = None) -> None:
        self.stop_event.clear()
        self.connect(max_attempts=max_attempts)
        self._connect_turntable(max_attempts=max_attempts)
        self._ensure_path_threads()
        self._ensure_turntable_threads()

    def connect_path_service(self, max_attempts: int | None = None) -> None:
        self.stop_event.clear()
        self.connect(max_attempts=max_attempts)
        self._ensure_path_threads()

    def connect_turntable_service(self, max_attempts: int | None = None) -> None:
        self.stop_event.clear()
        self._connect_turntable(max_attempts=max_attempts)
        self._ensure_turntable_threads()

    def stop(self) -> None:
        self.stop_event.set()
        self._motion_cancel_event.set()
        self._safe_close()
        self._safe_close_turn()
        self.tx_thread = None
        self.rx_thread = None
        self.turn_tx_thread = None
        self.turn_rx_thread = None

    def cancel_motion(self) -> None:
        with self.lock:
            self.pending_execute = False
            self._turntable_ready_for_execute = False
            self._execute_sent_at = None
            self._execute_awaiting_idle = False
        self._motion_cancel_event.set()
        self._logger.info("Robot motion cancel requested")

    def clear_motion_cancel(self) -> None:
        self._motion_cancel_event.clear()

    def _abort_requested(self, abort_event: threading.Event | None = None) -> bool:
        if self.stop_event.is_set():
            return True
        if self._motion_cancel_event.is_set():
            return True
        return abort_event is not None and abort_event.is_set()

    def is_idle(self) -> bool:
        with self.lock:
            return self.robot_status == self.STATUS_IDLE

    def trigger_point_by_list_index(self, list_index: int) -> bool:
        with self.lock:
            if list_index < 0 or list_index >= len(self.points):
                raise IndexError(f"Point index out of range: {list_index}")

            point = self.points[list_index]
            self.current_target = point.axes + [point.a7]
            self.pending_execute = True
            self._execute_sent_at = None
            self._execute_awaiting_idle = False
            self._turntable_ready_for_execute = False
            self._dispatch_started_at = time.monotonic()
            self._turntable_ready_at = None
            self.current_point_idx = list_index
            self._logger.info("Triggered point idx=%s axes=%s A7=%s", point.index, point.axes, point.a7)
        self._turn_tx_wake.set()
        self._robot_tx_wake.set()
        return True

    def move_to_target(self, axes: list[float], turntable_angle: float) -> None:
        with self.lock:
            self.current_target = list(axes) + [turntable_angle]
            self.pending_execute = True
            self._execute_sent_at = None
            self._execute_awaiting_idle = False
            self._turntable_ready_for_execute = False
            self._dispatch_started_at = time.monotonic()
            self._turntable_ready_at = None
        self._logger.info("Jog target set axes=%s A7=%s", axes, turntable_angle)
        self._turn_tx_wake.set()
        self._robot_tx_wake.set()

    def jog_to_target(
        self,
        axes: list[float],
        turntable_angle: float,
        *,
        settle_sec: float = 0.5,
        abort_event: threading.Event | None = None,
    ) -> None:
        if self._abort_requested(abort_event):
            raise RuntimeError("Cycle aborted")

        if not self.is_idle():
            if not self.wait_until_status(self.STATUS_IDLE, abort_event=abort_event):
                if self._abort_requested(abort_event):
                    raise RuntimeError("Cycle aborted")
                raise RuntimeError("Robot is not IDLE before jog command")

        self.move_to_target(axes, turntable_angle)

        if not self.wait_motion_done(abort_event=abort_event):
            if self._abort_requested(abort_event):
                raise RuntimeError("Cycle aborted")
            raise RuntimeError("Robot jog motion failed")

        self._sleep_interruptible(settle_sec, abort_event=abort_event)

    def _sleep_interruptible(
        self,
        sec: float,
        *,
        abort_event: threading.Event | None = None,
    ) -> None:
        deadline = time.monotonic() + sec
        while True:
            if self._abort_requested(abort_event):
                raise RuntimeError("Cycle aborted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))

    def wait_until_status(
        self,
        expected_status: int,
        timeout_sec: float | None = None,
        *,
        abort_event: threading.Event | None = None,
    ) -> bool:
        deadline = time.monotonic() + timeout_sec if timeout_sec is not None else None
        while not self._abort_requested(abort_event):
            with self.lock:
                current_status = self.robot_status
            if current_status == expected_status:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return False

    def wait_motion_done(self, *, abort_event: threading.Event | None = None) -> bool:
        success, _elapsed = self.wait_motion_done_timed(abort_event=abort_event)
        return success

    def wait_motion_done_timed(
        self,
        *,
        abort_event: threading.Event | None = None,
    ) -> tuple[bool, float]:
        started = time.monotonic()
        if not self.wait_until_status(self.STATUS_MOVING, abort_event=abort_event):
            return False, time.monotonic() - started
        if not self.wait_until_status(self.STATUS_IDLE, abort_event=abort_event):
            return False, time.monotonic() - started
        return True, time.monotonic() - started

    def run_loaded_points(self, inter_point_delay: float = 0.05) -> None:
        if not self.points:
            raise RuntimeError("No points loaded")

        if not self.wait_until_status(self.STATUS_IDLE):
            raise RuntimeError("Execution stopped while waiting robot IDLE")

        for index, point in enumerate(self.points):
            while not self.stop_event.is_set():
                if self.trigger_point_by_list_index(index):
                    break
                time.sleep(inter_point_delay)

            if self.stop_event.is_set():
                raise RuntimeError("Execution stopped")

            if not self.wait_motion_done():
                raise RuntimeError(f"Execution stopped at point idx={point.index} (list index {index})")

        self._logger.info("Trajectory completed")

    def run_trajectory_from_latest_json(self, folder: str, inter_point_delay: float = 0.05) -> None:
        latest_json = self.find_latest_json(folder)
        self.load_points_from_json(latest_json)
        self.start()
        try:
            self.run_loaded_points(inter_point_delay=inter_point_delay)
        finally:
            self.stop()

    def _can_send_execute_locked(self) -> bool:
        return (
            self.pending_execute
            and self._turntable_ready_for_execute
            and self.robot_status != self.STATUS_MOVING
            and self.connected
            and self.turn_connected
        )

    def _can_send_execute(self) -> bool:
        with self.lock:
            return self._can_send_execute_locked()

    def _mark_turntable_ready_if_pending(self, wire_turn: float, wire_format: str) -> None:
        became_ready = False
        with self.lock:
            if not self.pending_execute:
                return
            expected = turntable_wire_display_value(self.current_target[6], wire_format)
            if wire_turn != expected or self._turntable_ready_for_execute:
                return
            self._turntable_ready_for_execute = True
            self._turntable_ready_at = time.monotonic()
            became_ready = True
        if became_ready:
            self._logger.debug("Turntable angle sent; robot execute allowed")
            self._robot_tx_wake.set()

    def _tx_loop(self) -> None:
        while not self.stop_event.is_set():
            if not self.connected:
                self.connect()
                time.sleep(0.1)
                continue

            try:
                with self.lock:
                    sock = self.sock
                    execute = self._can_send_execute_locked()
                    a1, a2, a3, a4, a5, a6, turn = self.current_target
                    xml_msg = build_axis_angle_xml(
                        AxisAngleCommand(
                            a1=a1,
                            a2=a2,
                            a3=a3,
                            a4=a4,
                            a5=a5,
                            a6=a6,
                            alive=True,
                            execute=execute,
                        )
                    )

                if sock is None:
                    time.sleep(0.1)
                    continue

                sock.sendall(xml_msg.encode("utf-8"))
                if execute:
                    with self.lock:
                        if self._execute_sent_at is None:
                            self._execute_sent_at = time.monotonic()
                            dispatch_started_at = self._dispatch_started_at
                            turntable_ready_at = self._turntable_ready_at
                            self._logger.info("Execute=1 sent")
                            if dispatch_started_at is not None:
                                turntable_ready_sec = (
                                    turntable_ready_at - dispatch_started_at
                                    if turntable_ready_at is not None
                                    else None
                                )
                                execute_sent_sec = self._execute_sent_at - dispatch_started_at
                                self._logger.debug(
                                    "Motion dispatch timing: turntable_ready=%.3fs execute_sent=%.3fs",
                                    turntable_ready_sec
                                    if turntable_ready_sec is not None
                                    else -1.0,
                                    execute_sent_sec,
                                )
                self._logger.debug("Robot TX: %s", xml_msg)
                self._robot_tx_wake.wait(timeout=self.heartbeat_period)
                self._robot_tx_wake.clear()
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._logger.warning("TX error: %s", exc)
                self._safe_close()
                time.sleep(1.0)

    def _turn_tx_loop(self) -> None:
        while not self.stop_event.is_set():
            if not self.turn_connected:
                self._connect_turntable()
                time.sleep(0.1)
                continue

            try:
                with self.lock:
                    turn = self.current_target[6]
                wire_format = get_runtime_settings().turntable_wire_format
                wire_turn = turntable_wire_display_value(turn, wire_format)
                with self.turn_lock:
                    turn_sock = self.turn_sock

                xml_msg = build_turn_command_xml(TurnCommandMessage(turn=turn, alive=True))

                if turn_sock is None:
                    time.sleep(0.1)
                    continue

                turn_sock.sendall(xml_msg.encode("utf-8"))
                self._mark_turntable_ready_if_pending(wire_turn, wire_format)
                if wire_turn != self._last_logged_turn_wire:
                    if wire_format == "integer":
                        self._logger.info("Turntable position sent: %.0f", wire_turn)
                    else:
                        self._logger.info("Turntable position sent: %.2f", wire_turn)
                    self._last_logged_turn_wire = wire_turn
                self._logger.debug("Turntable TX: %s", xml_msg)
                self._turn_tx_wake.wait(timeout=self.heartbeat_period)
                self._turn_tx_wake.clear()
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._logger.warning("Turntable TX error: %s", exc)
                self._safe_close_turn()
                time.sleep(1.0)

    def _rx_loop(self) -> None:
        buffer = ""
        while not self.stop_event.is_set():
            if not self.connected:
                time.sleep(0.2)
                continue

            try:
                with self.lock:
                    sock = self.sock
                if sock is None:
                    time.sleep(0.1)
                    continue

                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Socket closed by peer")

                buffer += chunk.decode("utf-8", errors="replace")
                buffer = drain_xml_packets(buffer, self._handle_incoming_xml)
            except socket.timeout:
                continue
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._logger.warning("RX error: %s", exc)
                self._safe_close()
                time.sleep(1.0)

    def _turn_rx_loop(self) -> None:
        buffer = ""
        while not self.stop_event.is_set():
            if not self.turn_connected:
                time.sleep(0.2)
                continue

            try:
                with self.turn_lock:
                    turn_sock = self.turn_sock
                if turn_sock is None:
                    time.sleep(0.1)
                    continue

                chunk = turn_sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Turntable socket closed by peer")

                buffer += chunk.decode("utf-8", errors="replace")

                def log_packet(packet: str) -> None:
                    self._logger.debug("Turntable RX: %s", packet)

                buffer = drain_xml_packets(buffer, log_packet)
            except socket.timeout:
                continue
            except Exception as exc:
                if not self.stop_event.is_set():
                    self._logger.warning("Turntable RX error: %s", exc)
                self._safe_close_turn()
                time.sleep(1.0)

    def _handle_incoming_xml(self, xml_packet: str) -> None:
        try:
            root = ET.fromstring(xml_packet)
        except ET.ParseError as exc:
            self._logger.warning("XML parse error: %s packet=%r", exc, xml_packet)
            return

        if root.tag == ROBOT_STATUS_ROOT:
            self._logger.debug("Robot RX: %s", xml_packet)
            self._handle_robot_status(parse_path_robot_status(xml_packet))
        else:
            self._logger.debug("Unhandled XML root: %s", root.tag)

    def _handle_robot_status(self, status_message) -> None:
        status = status_message.status
        log_in_position = False
        elapsed = 0.0
        with self.lock:
            changed = status != self.robot_status
            self.robot_status = status
            if status == self.STATUS_MOVING:
                self.pending_execute = False
                if self._execute_sent_at is not None:
                    self._execute_awaiting_idle = True
            if (
                status == self.STATUS_IDLE
                and self._execute_awaiting_idle
                and self._execute_sent_at is not None
            ):
                elapsed = time.monotonic() - self._execute_sent_at
                self._execute_sent_at = None
                self._execute_awaiting_idle = False
                log_in_position = True

        if log_in_position:
            self._logger.info("In-position response time: %.2f s", elapsed)

        if changed:
            if status == self.STATUS_IDLE:
                self._logger.debug("STATUS -> 1 (IDLE)")
            elif status == self.STATUS_MOVING:
                self._logger.debug("STATUS -> 2 (MOVING)")
            else:
                self._logger.debug("STATUS -> %s", status)

    def _safe_close(self) -> None:
        with self.lock:
            sock = self.sock
            self.sock = None
            self.connected = False
            self.pending_execute = False
            self._execute_sent_at = None
            self._execute_awaiting_idle = False
            self._dispatch_started_at = None
            self._turntable_ready_at = None

        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _safe_close_turn(self) -> None:
        with self.turn_lock:
            turn_sock = self.turn_sock
            self.turn_sock = None
            self.turn_connected = False

        self._last_logged_turn_wire = None
        with self.lock:
            self._turntable_ready_for_execute = False

        if turn_sock is not None:
            try:
                turn_sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                turn_sock.close()
            except OSError:
                pass
