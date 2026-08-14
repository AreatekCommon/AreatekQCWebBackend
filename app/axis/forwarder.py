from __future__ import annotations

import socket
import time
from typing import Optional

from app.axis.models import AxisSample, ForwardSettings
from app.core.logger import get_logger


class CoreControlVisualForwarder:
    def __init__(self, settings: ForwardSettings) -> None:
        self._settings = settings
        self._socket: Optional[socket.socket] = None
        self._logger = get_logger(self.__class__.__name__)

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        if self._socket is not None:
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self._settings.connect_timeout_s)

        if self._settings.tcp_no_delay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self._logger.info(
            "Connecting to CoreControl_Visual %s:%s ...",
            self._settings.host,
            self._settings.port,
        )
        sock.connect((self._settings.host, self._settings.port))
        sock.settimeout(self._settings.send_timeout_s)
        self._socket = sock
        self._logger.info(
            "Connected to CoreControl_Visual %s:%s",
            self._settings.host,
            self._settings.port,
        )

    def close(self) -> None:
        if self._socket is None:
            return

        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            self._socket.close()
        finally:
            self._socket = None
            self._logger.info("CoreControl_Visual connection closed")

    def send_axis_sample(self, sample: AxisSample) -> None:
        if not self.is_connected:
            self.connect()

        if self._socket is None:
            raise ConnectionError("CoreControl_Visual socket is not connected")

        payload_text = sample.to_core_control_visual_message()
        self._socket.sendall(payload_text.encode("utf-8"))
        self._logger.debug(
            "Axis sample forwarded to CoreControl_Visual: %s",
            payload_text.rstrip("\n"),
        )

    def send_axis_sample_with_reconnect(self, sample: AxisSample) -> None:
        try:
            self.send_axis_sample(sample)
        except (ConnectionError, OSError) as exc:
            self._logger.warning("CoreControl_Visual forwarding error: %s", exc)
            self.close()
            time.sleep(self._settings.reconnect_delay_s)
            self.send_axis_sample(sample)
