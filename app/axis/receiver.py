from __future__ import annotations

import socket
import threading
import xml.etree.ElementTree as ET
from typing import Optional, Protocol

from app.axis.models import AxisSample, AxisState, ReceiverSettings
from app.core.app_state import app_state
from app.core.logger import get_logger


class AxisSampleSink(Protocol):
    def publish(self, sample: AxisSample) -> None:
        ...


class AxisReceiver:
    def __init__(
        self,
        settings: ReceiverSettings,
        sink: Optional[AxisSampleSink] = None,
        external_axis: float = 30.0,
    ) -> None:
        self._settings = settings
        self._sink = sink
        self._external_axis = external_axis
        self._socket: Optional[socket.socket] = None
        self._buffer = ""
        self._state = AxisState()
        self._logger = get_logger(self.__class__.__name__)

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    @property
    def state(self) -> AxisState:
        return self._state

    def connect(self) -> None:
        if self.is_connected:
            self._logger.debug("connect() skipped: already connected")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self._settings.connect_timeout_s)
            if self._settings.tcp_no_delay:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._logger.info("Connecting to EKI server %s:%d", self._settings.host, self._settings.port)
            sock.connect((self._settings.host, self._settings.port))
            sock.settimeout(self._settings.receive_timeout_s)
            self._socket = sock
            self._buffer = ""
            self._logger.info("Connected to EKI server %s:%d", self._settings.host, self._settings.port)
            if self._settings.send_ready_on_connect:
                self.send_ready(self._settings.ready_value)
            if self._sink is not None:
                on_connected = getattr(self._sink, "on_connected", None)
                if callable(on_connected):
                    on_connected()
        except Exception:
            sock.close()
            raise

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        self._buffer = ""
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        finally:
            sock.close()
        self._logger.info("EKI connection closed")

    def send_ready(self, ready: bool = True) -> None:
        value = "true" if ready else "false"
        self._send_text(f"<Signal><Ready>{value}</Ready></Signal>")
        self._logger.debug("Ready signal sent: %s", ready)

    def receive_once(self) -> AxisSample:
        if not self.is_connected:
            self.connect()
        xml_text = self._receive_next_xml("Axes")
        sample = AxisSample.from_xml(xml_text, external_axis=self._external_axis)
        self._state.update(sample)
        self._logger.debug("Axes received #%d: %s", self._state.sample_count, sample.joint_values())
        if self._sink is not None:
            self._logger.debug("Publishing sample to sink")
            self._sink.publish(sample)
        return sample

    def run_forever(self, stop_event: threading.Event) -> None:
        self._logger.info("AxisReceiver run loop started")
        try:
            while not stop_event.is_set():
                try:
                    self.receive_once()
                except (socket.timeout, TimeoutError):
                    self._logger.debug("Receive timeout: waiting for next packet")
                    continue
                except (ConnectionError, OSError, ET.ParseError, UnicodeDecodeError, ValueError) as exc:
                    self._logger.warning("Receiver communication error: %s", exc)
                    if self._sink is not None:
                        on_error = getattr(self._sink, "on_error", None)
                        if callable(on_error):
                            on_error(str(exc))
                    self.close()
                    if stop_event.is_set() or app_state.is_shutting_down:
                        break
                    if not stop_event.is_set():
                        self._logger.info("Reconnect after %.3fs", self._settings.reconnect_delay_s)
                        stop_event.wait(timeout=self._settings.reconnect_delay_s)
        finally:
            self.close()
            self._logger.info("AxisReceiver run loop stopped")

    def run_demo_forever(self) -> None:
        self._logger.info("AxisReceiver demo lifecycle started")
        stop_event = threading.Event()
        try:
            self.run_forever(stop_event)
        except KeyboardInterrupt:
            self._logger.info("KeyboardInterrupt received in demo lifecycle")
            stop_event.set()
        finally:
            self.close()
            self._logger.info("AxisReceiver demo lifecycle finished")

    def _send_text(self, text: str) -> None:
        if self._socket is None:
            raise ConnectionError("EKI receiver is not connected")
        self._logger.debug("Sending XML: %s", text)
        self._socket.sendall(text.encode("utf-8"))

    def _receive_next_xml(self, root_tag: str) -> str:
        while True:
            xml_text = self._try_extract_xml(root_tag)
            if xml_text is not None:
                self._logger.debug("Complete XML extracted: %s", xml_text)
                return xml_text
            if self._socket is None:
                raise ConnectionError("EKI receiver is not connected")
            chunk = self._socket.recv(self._settings.receive_buffer_size)
            if not chunk:
                raise ConnectionError("EKI remote side closed TCP connection")
            decoded = chunk.decode("utf-8", errors="strict")
            self._logger.debug("Received chunk: %r", decoded)
            self._buffer += decoded

    def _try_extract_xml(self, root_tag: str) -> Optional[str]:
        start_tag = f"<{root_tag}>"
        end_tag = f"</{root_tag}>"
        start_index = self._buffer.find(start_tag)
        if start_index < 0:
            self._trim_buffer()
            return None
        end_index = self._buffer.find(end_tag, start_index)
        if end_index < 0:
            if start_index > 0:
                self._buffer = self._buffer[start_index:]
            return None
        end_index += len(end_tag)
        xml_text = self._buffer[start_index:end_index]
        self._buffer = self._buffer[end_index:]
        return xml_text

    def _trim_buffer(self) -> None:
        max_tail_length = len("<Axes>") - 1
        if len(self._buffer) > max_tail_length:
            self._buffer = self._buffer[-max_tail_length:]
