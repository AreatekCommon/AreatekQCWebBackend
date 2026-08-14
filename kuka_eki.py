from __future__ import annotations

import socket
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Optional

from app.core.logger import get_logger

ROBOT_IP = "192.168.0.5"
ROBOT_PORT = 54601
RECONNECT_DELAY = 1.0
BUFFER_SIZE = 4096
ENCODING = "utf-8"
CONNECT_TIMEOUT_SEC = 5.0
SOCKET_TIMEOUT_SEC = 1.0
HEARTBEAT_INTERVAL_SEC = 0.5

STATUS_ROOT = "RobotStatus"
STATUS_FIELD = "Status"
CURRENT_SCAN_FIELD = "CurrentScan"
TOTAL_SCANS_FIELD = "TotalScans"
COMMAND_ROOT = "ClientCommand"
COMMAND_CMD_FIELD = "Cmd"
COMMAND_VALUE_FIELD = "Value"
COMMAND_ACK_STATUS_FIELD = "AckStatus"
COMMAND_ACK_SCAN_FIELD = "AckScan"
COMMAND_ALIVE_FIELD = "Alive"

STATUS_READY_TO_START = 0
STATUS_NEXT_POSITION = 1
STATUS_IN_POSITION = 2
CMD_NONE = 0
CMD_NEXT = 1


@dataclass(frozen=True)
class ClientCommandMessage:
    cmd: int = 0
    value: int = 0
    ack_status: int = 0
    ack_scan: int = 0
    alive: bool = True


@dataclass(frozen=True)
class ScanRobotStatus:
    raw_status: int
    current_scan: int = 0
    total_scans: int = 0

    @property
    def ready_to_start(self) -> bool:
        return self.raw_status == STATUS_READY_TO_START

    @property
    def next_position(self) -> bool:
        return self.raw_status == STATUS_NEXT_POSITION

    @property
    def in_position(self) -> bool:
        return self.raw_status == STATUS_IN_POSITION


def _bool_to_text(value: bool) -> str:
    return "true" if value else "false"


def build_client_command_xml(message: ClientCommandMessage) -> str:
    return (
        f"<{COMMAND_ROOT}>"
        f"<{COMMAND_CMD_FIELD}>{message.cmd}</{COMMAND_CMD_FIELD}>"
        f"<{COMMAND_VALUE_FIELD}>{message.value}</{COMMAND_VALUE_FIELD}>"
        f"<{COMMAND_ACK_STATUS_FIELD}>{message.ack_status}</{COMMAND_ACK_STATUS_FIELD}>"
        f"<{COMMAND_ACK_SCAN_FIELD}>{message.ack_scan}</{COMMAND_ACK_SCAN_FIELD}>"
        f"<{COMMAND_ALIVE_FIELD}>{_bool_to_text(message.alive)}</{COMMAND_ALIVE_FIELD}>"
        f"</{COMMAND_ROOT}>"
    )


def _require_int_field(root: ET.Element, field_name: str) -> int:
    elem = root.find(field_name)
    if elem is None or elem.text is None or not elem.text.strip():
        raise ValueError(f"Missing XML field: {field_name}")
    return int(elem.text.strip())


def _optional_int_field(root: ET.Element, field_name: str, default: int = 0) -> int:
    elem = root.find(field_name)
    if elem is None or elem.text is None or not elem.text.strip():
        return default
    return int(elem.text.strip())


def parse_scan_robot_status(xml_packet: str) -> ScanRobotStatus:
    root = ET.fromstring(xml_packet)
    if root.tag != STATUS_ROOT:
        raise ValueError(f"Expected <{STATUS_ROOT}>, received <{root.tag}>")

    return ScanRobotStatus(
        raw_status=_require_int_field(root, STATUS_FIELD),
        current_scan=_optional_int_field(root, CURRENT_SCAN_FIELD, default=0),
        total_scans=_optional_int_field(root, TOTAL_SCANS_FIELD, default=0),
    )


def extract_first_complete_xml(text: str) -> tuple[Optional[str], str]:
    if not text:
        return None, text

    start = text.find("<")
    if start == -1:
        return None, ""

    if start > 0:
        text = text[start:]

    gt = text.find(">")
    if gt == -1:
        return None, text

    open_tag = text[1:gt].strip()
    if not open_tag or open_tag.startswith("?") or open_tag.startswith("!"):
        next_lt = text.find("<", gt + 1)
        if next_lt == -1:
            return None, text
        return extract_first_complete_xml(text[next_lt:])

    root_name = open_tag.split()[0]
    closing_tag = f"</{root_name}>"
    end_idx = text.find(closing_tag)
    if end_idx == -1:
        return None, text

    end_idx += len(closing_tag)
    return text[:end_idx], text[end_idx:]


class KukaEkiClient:
    STATUS_READY_TO_START = STATUS_READY_TO_START
    STATUS_NEXT_POSITION = STATUS_NEXT_POSITION
    STATUS_IN_POSITION = STATUS_IN_POSITION
    CMD_NONE = CMD_NONE
    CMD_NEXT = CMD_NEXT

    def __init__(
        self,
        robot_ip: str,
        robot_port: int = ROBOT_PORT,
        reconnect_delay: float = RECONNECT_DELAY,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SEC,
        connect_timeout_s: float = CONNECT_TIMEOUT_SEC,
        recv_timeout_s: float = SOCKET_TIMEOUT_SEC,
    ) -> None:
        self.robot_ip = robot_ip
        self.robot_port = robot_port
        self.reconnect_delay = reconnect_delay
        self.heartbeat_interval = heartbeat_interval
        self.connect_timeout_s = connect_timeout_s
        self.recv_timeout_s = recv_timeout_s

        self.sock: Optional[socket.socket] = None
        self._rx_buffer = ""
        self._connected = False
        self._running = False

        self._io_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._status_event = threading.Event()
        self._logger = get_logger(self.__class__.__name__)

        self._rx_thread: Optional[threading.Thread] = None
        self._tx_thread: Optional[threading.Thread] = None

        self._last_status_message: dict[str, Any] = {
            "raw_status": -1,
            "ready_to_start": False,
            "next_position": False,
            "in_position": False,
            "current_scan": 0,
            "total_scans": 0,
        }

        self._command = ClientCommandMessage()
        self._ack_status_value = 0
        self._ack_scan_value = 0

    def connect(self) -> None:
        self.close_socket_only()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout_s)
        sock.connect((self.robot_ip, self.robot_port))
        sock.settimeout(self.recv_timeout_s)

        with self._io_lock:
            self.sock = sock
            self._connected = True
            self._rx_buffer = ""

        self._logger.info("Connected to %s:%d", self.robot_ip, self.robot_port)

    def reconnect(self) -> None:
        while self._running:
            try:
                self.connect()
                return
            except OSError as exc:
                self._logger.warning("Reconnect failed: %s", exc)
                time.sleep(self.reconnect_delay)

    def ensure_connected(self) -> None:
        if not self.is_connected:
            self.reconnect()

    @property
    def is_connected(self) -> bool:
        with self._io_lock:
            return self._connected and self.sock is not None

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self.reconnect()

        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name="EkiScanRx")
        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True, name="EkiScanTx")
        self._rx_thread.start()
        self._tx_thread.start()
        self._logger.info("Scan client started")

    def stop(self) -> None:
        self._running = False
        if self._rx_thread is not None:
            self._rx_thread.join(timeout=2.0)
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=2.0)
        self.close_socket_only()
        self._logger.info("Scan client stopped")

    def close(self) -> None:
        self.stop()

    def close_socket_only(self) -> None:
        with self._io_lock:
            if self.sock is not None:
                try:
                    self.sock.close()
                except OSError:
                    pass
            self.sock = None
            self._connected = False
            self._rx_buffer = ""

    def set_command(self, cmd: int = CMD_NONE, value: int = 0) -> None:
        with self._state_lock:
            self._command = ClientCommandMessage(
                cmd=int(cmd),
                value=int(value),
                ack_status=self._ack_status_value,
                ack_scan=self._ack_scan_value,
                alive=self._command.alive,
            )

    def clear_command(self) -> None:
        self.set_command(CMD_NONE, 0)

    def set_alive(self, alive: bool) -> None:
        with self._state_lock:
            self._command = ClientCommandMessage(
                cmd=self._command.cmd,
                value=self._command.value,
                ack_status=self._ack_status_value,
                ack_scan=self._ack_scan_value,
                alive=bool(alive),
            )

    def set_ack(self, ack_status: Optional[int] = None, ack_scan: Optional[int] = None) -> None:
        with self._state_lock:
            if ack_status is not None:
                self._ack_status_value = int(ack_status)
            if ack_scan is not None:
                self._ack_scan_value = int(ack_scan)
            self._command = ClientCommandMessage(
                cmd=self._command.cmd,
                value=self._command.value,
                ack_status=self._ack_status_value,
                ack_scan=self._ack_scan_value,
                alive=self._command.alive,
            )

    def clear_ack(self) -> None:
        self.set_ack(ack_status=0, ack_scan=0)

    def sync_ack_with_last_status(self) -> None:
        message = self.get_last_status_message()
        self.set_ack(
            ack_status=int(message.get("raw_status", 0)),
            ack_scan=int(message.get("current_scan", 0)),
        )

    def get_last_status_message(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._last_status_message)

    def read_status_message(self, timeout: Optional[float] = None) -> dict[str, Any]:
        if not self._status_event.wait(timeout=timeout):
            raise TimeoutError("Timeout waiting for RobotStatus")
        return self.get_last_status_message()

    def wait_for_status_message(
        self,
        expected_status: int,
        poll_delay: float = 0.05,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        while True:
            message = self.get_last_status_message()
            if int(message["raw_status"]) == int(expected_status):
                return message
            if timeout is not None and (time.monotonic() - started) >= timeout:
                raise TimeoutError(f"Timeout waiting for status {expected_status}")
            time.sleep(poll_delay)

    def _build_client_command_xml(self) -> str:
        with self._state_lock:
            return build_client_command_xml(self._command)

    def _send_xml(self, xml_data: str) -> None:
        payload = xml_data.encode(ENCODING)
        while self._running:
            try:
                self.ensure_connected()
                with self._io_lock:
                    assert self.sock is not None
                    self.sock.sendall(payload)
                self._logger.debug("TX %s", xml_data)
                return
            except (OSError, ConnectionError) as exc:
                self._logger.warning("TX failed: %s", exc)
                self.close_socket_only()
                time.sleep(self.reconnect_delay)

    def _recv_chunk(self) -> str:
        while self._running:
            try:
                self.ensure_connected()
                with self._io_lock:
                    assert self.sock is not None
                    chunk = self.sock.recv(BUFFER_SIZE)
                if not chunk:
                    self.close_socket_only()
                    raise ConnectionError("Robot closed the connection")
                chunk_text = chunk.decode(ENCODING, errors="replace")
                self._logger.debug("RX %s", chunk_text)
                return chunk_text
            except socket.timeout:
                return ""
            except (OSError, ConnectionError) as exc:
                self._logger.warning("RX failed: %s", exc)
                self.close_socket_only()
                time.sleep(self.reconnect_delay)
        return ""

    def _rx_loop(self) -> None:
        while self._running:
            try:
                chunk_text = self._recv_chunk()
                if not chunk_text:
                    continue
                self._rx_buffer += chunk_text

                while True:
                    packet, self._rx_buffer = extract_first_complete_xml(self._rx_buffer)
                    if packet is None:
                        break
                    if not packet.startswith(f"<{STATUS_ROOT}>"):
                        continue
                    parsed = self._parse_status_message(parse_scan_robot_status(packet))
                    with self._state_lock:
                        self._last_status_message = parsed
                    self._status_event.set()
            except ET.ParseError as exc:
                self._logger.warning("XML parse error: %s", exc)
                self._rx_buffer = ""
            except Exception as exc:
                self._logger.warning("RX loop exception: %s", exc)
                time.sleep(self.reconnect_delay)

    def _tx_loop(self) -> None:
        while self._running:
            try:
                self._send_xml(self._build_client_command_xml())
            except Exception as exc:
                self._logger.warning("TX loop exception: %s", exc)
            time.sleep(self.heartbeat_interval)

    @staticmethod
    def _parse_status_message(status: ScanRobotStatus) -> dict[str, Any]:
        return {
            "raw_status": status.raw_status,
            "ready_to_start": status.ready_to_start,
            "next_position": status.next_position,
            "in_position": status.in_position,
            "current_scan": status.current_scan,
            "total_scans": status.total_scans,
        }


if __name__ == "__main__":
    client = KukaEkiClient(robot_ip=ROBOT_IP, robot_port=ROBOT_PORT)
    client.start()
    try:
        while True:
            time.sleep(0.2)
    finally:
        client.stop()
