from __future__ import annotations

import queue
import threading
from typing import Any, Optional

from app.axis.forwarder import CoreControlVisualForwarder
from app.axis.models import AxisSample, ForwardSettings, ReceiverSettings
from app.axis.receiver import AxisReceiver
from app.core.app_state import app_state
from app.core.logger import get_logger
from app.core.runtime_settings_store import get_runtime_settings
from app.models.runtime_settings import RuntimeSettings

_UNSET = object()
_FORWARD_QUEUE_MAX = 8


def _axes_available_from_snapshot(snapshot: dict[str, Any]) -> bool:
    return all(snapshot.get(f"a{index}") is not None for index in range(1, 7))


class AxisReceiverService:
    def __init__(self) -> None:
        self._logger = get_logger(self.__class__.__name__)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._receiver: Optional[AxisReceiver] = None
        self._forwarder: Optional[CoreControlVisualForwarder] = None
        self._forward_queue: queue.Queue[AxisSample] = queue.Queue(maxsize=_FORWARD_QUEUE_MAX)
        self._forward_stop_event = threading.Event()
        self._forward_thread: Optional[threading.Thread] = None
        self._forward_connected = False
        self._forward_last_error: str | None = None

    def start(self, settings: Optional[RuntimeSettings] = None) -> None:
        runtime_settings = settings or get_runtime_settings()
        receiver_settings = self._to_receiver_settings(runtime_settings)
        forward_settings = self._to_forward_settings(runtime_settings)

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._logger.debug("AxisReceiverService already running")
                return

            self._stop_event = threading.Event()
            self._forward_stop_event = threading.Event()
            self._forward_queue = queue.Queue(maxsize=_FORWARD_QUEUE_MAX)
            self._forward_connected = False
            self._forward_last_error = None
            self._receiver = AxisReceiver(receiver_settings, sink=self)
            self._forwarder = self._create_forwarder(forward_settings)
            self._thread = threading.Thread(
                target=self._receiver.run_forever,
                args=(self._stop_event,),
                name="AxisReceiverService",
                daemon=True,
            )
            self._thread.start()
            if self._forwarder is not None:
                self._forward_thread = threading.Thread(
                    target=self._forward_worker_loop,
                    name="AxisForwardWorker",
                    daemon=True,
                )
                self._forward_thread.start()
            else:
                self._forward_thread = None
            self._logger.info(
                "Starting axis receiver connection to %s:%d",
                receiver_settings.host,
                receiver_settings.port,
            )
            if self._forwarder is not None:
                self._logger.info(
                    "Axis forward enabled to %s:%d",
                    forward_settings.host,
                    forward_settings.port,
                )

    def restart(self, settings: Optional[RuntimeSettings] = None) -> None:
        self.stop()
        self.start(settings)

    def stop(self, timeout_s: float = 5.0) -> None:
        with self._lock:
            self._stop_event.set()
            self._forward_stop_event.set()
            thread = self._thread
            forward_thread = self._forward_thread
            receiver = self._receiver
            forwarder = self._forwarder

        if receiver is not None:
            if receiver.is_connected:
                try:
                    receiver.send_ready(False)
                    self._logger.info("Sent axis Ready=false before shutdown")
                except Exception as exc:
                    self._logger.warning("Failed to send axis Ready=false: %s", exc)
            receiver.close()

        if forwarder is not None:
            forwarder.close()

        if thread is not None:
            thread.join(timeout=timeout_s)

        if forward_thread is not None:
            forward_thread.join(timeout=timeout_s)

        with self._lock:
            self._thread = None
            self._forward_thread = None
            self._receiver = None
            self._forwarder = None
            self._forward_connected = False
            self._forward_last_error = None

        self._update_snapshot(connected=False, last_error=_UNSET)
        self._logger.info("AxisReceiverService stopped")

    def publish(self, sample: AxisSample) -> None:
        receiver = self._receiver
        sample_count = receiver.state.sample_count if receiver is not None else 0
        self._update_snapshot(
            connected=True,
            sample=sample,
            sample_count=sample_count,
            last_error=None,
        )

        if self._forwarder is not None:
            self._enqueue_forward_sample(sample)

    def on_connected(self) -> None:
        self._update_snapshot(connected=True, last_error=None)

    def on_error(self, message: str) -> None:
        self._update_snapshot(connected=False, last_error=message)

    def _enqueue_forward_sample(self, sample: AxisSample) -> None:
        try:
            self._forward_queue.put_nowait(sample)
        except queue.Full:
            try:
                self._forward_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._forward_queue.put_nowait(sample)
            except queue.Full:
                self._logger.debug("Axis forward queue full; dropping sample")

    def _forward_worker_loop(self) -> None:
        while not self._forward_stop_event.is_set():
            try:
                sample = self._forward_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            forwarder = self._forwarder
            if forwarder is None:
                continue

            try:
                forwarder.send_axis_sample_with_reconnect(sample)
                with self._lock:
                    self._forward_connected = True
                    self._forward_last_error = None
            except (ConnectionError, OSError) as exc:
                with self._lock:
                    self._forward_connected = False
                    self._forward_last_error = str(exc)
                self._logger.warning("Failed to forward axis sample: %s", exc)

    @staticmethod
    def _to_receiver_settings(runtime_settings: RuntimeSettings) -> ReceiverSettings:
        return ReceiverSettings(
            host=runtime_settings.sender_host,
            port=runtime_settings.sender_port,
        )

    @staticmethod
    def _to_forward_settings(runtime_settings: RuntimeSettings) -> ForwardSettings:
        return ForwardSettings(
            host=runtime_settings.axis_forward_host,
            port=runtime_settings.axis_forward_port,
            enabled=runtime_settings.axis_forward_enabled,
        )

    @staticmethod
    def _create_forwarder(settings: ForwardSettings) -> Optional[CoreControlVisualForwarder]:
        if not settings.enabled:
            return None
        return CoreControlVisualForwarder(settings)

    def _update_snapshot(
        self,
        *,
        connected: bool,
        sample: Optional[AxisSample] = None,
        sample_count: Optional[int] = None,
        last_error: Any = _UNSET,
    ) -> None:
        with self._lock:
            previous = dict(app_state.current_position)

            if last_error is _UNSET:
                error_value = previous.get("last_error")
            else:
                error_value = last_error

            snapshot = {
                "connected": connected,
                "sample_count": sample_count if sample_count is not None else int(previous.get("sample_count", 0)),
                "timestamp_ms": sample.timestamp_ms if sample is not None else previous.get("timestamp_ms"),
                "a1": sample.a1 if sample is not None else previous.get("a1"),
                "a2": sample.a2 if sample is not None else previous.get("a2"),
                "a3": sample.a3 if sample is not None else previous.get("a3"),
                "a4": sample.a4 if sample is not None else previous.get("a4"),
                "a5": sample.a5 if sample is not None else previous.get("a5"),
                "a6": sample.a6 if sample is not None else previous.get("a6"),
                "external_axis": sample.external_axis if sample is not None else previous.get("external_axis"),
                "last_error": error_value,
                "forward_connected": self._forward_connected,
                "forward_last_error": self._forward_last_error,
            }
            snapshot["axes_available"] = _axes_available_from_snapshot(snapshot)
            app_state.current_position = snapshot

    def get_snapshot(self) -> dict:
        with self._lock:
            receiver = self._receiver
            snapshot = dict(app_state.current_position)
            snapshot["forward_connected"] = self._forward_connected
            snapshot["forward_last_error"] = self._forward_last_error
            if receiver is not None and receiver.is_connected:
                snapshot["connected"] = True
                snapshot["last_error"] = None
            snapshot["axes_available"] = _axes_available_from_snapshot(snapshot)
            return snapshot


axis_receiver_service = AxisReceiverService()
