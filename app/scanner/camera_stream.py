from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Optional

from app.core.camera_ws_manager import camera_ws_manager
from app.core.logger import get_logger
from app.core.runtime_settings_store import get_runtime_settings
from app.models.runtime_settings import RuntimeSettings

logger = get_logger(__name__)

CAPTURE_UNAVAILABLE_STATUS = "capture_unavailable"
CAPTURE_UNAVAILABLE_MESSAGE = (
    "Camera capture unavailable. Start OptimScanCameraHost.exe for live preview."
)
EMPTY_FRAME_CAPTURE_UNAVAILABLE_THRESHOLD = 5


class CameraStreamService:
    def __init__(self) -> None:
        self._relay_task: Optional[asyncio.Task[None]] = None
        self._host_stream_active = False
        self._relay_lock = asyncio.Lock()
        self._consecutive_empty_frames = 0
        self._capture_unavailable_notified = False

    async def on_subscriber_connected(self) -> None:
        await self._ensure_relay_running()

    async def on_subscriber_disconnected(self) -> None:
        if await camera_ws_manager.count() == 0:
            await self.stop_relay()

    async def notify_scanner_disconnected(self) -> None:
        await self._stop_host_stream()

    def notify_scanner_disconnected_sync(self) -> None:
        if not self._host_stream_active:
            return

        settings = get_runtime_settings()
        self._post_host_stream_stop(settings)
        self._host_stream_active = False

    async def stop_relay(self) -> None:
        async with self._relay_lock:
            task = self._relay_task
            self._relay_task = None

        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._stop_host_stream()

    async def _ensure_relay_running(self) -> None:
        async with self._relay_lock:
            if self._relay_task is not None and not self._relay_task.done():
                return
            self._relay_task = asyncio.create_task(self._relay_loop())

    async def _relay_loop(self) -> None:
        settings = get_runtime_settings()
        interval_sec = 1.0 / max(settings.camera_stream_fps, 1)

        try:
            if not settings.camera_stream_enabled:
                logger.info("Camera stream relay disabled in runtime settings")
                return

            while await camera_ws_manager.count() > 0:
                if not self._scanner_is_connected():
                    logger.info("Camera stream waiting for scanner connection")
                    self._host_stream_active = False
                    await asyncio.sleep(interval_sec)
                    continue

                if not self._host_stream_active:
                    started = await asyncio.to_thread(
                        self._post_host_stream_start,
                        settings,
                    )
                    self._host_stream_active = started
                    self._consecutive_empty_frames = 0
                    self._capture_unavailable_notified = False
                    if not started:
                        logger.info(
                            "Camera stream host start failed at %s",
                            self._base_url(settings),
                        )
                        await asyncio.sleep(interval_sec)
                        continue

                frame = await asyncio.to_thread(self._fetch_frame, settings)
                if frame:
                    self._consecutive_empty_frames = 0
                    self._capture_unavailable_notified = False
                    await camera_ws_manager.broadcast_bytes(frame)
                else:
                    self._consecutive_empty_frames += 1
                    if (
                        self._consecutive_empty_frames
                        >= EMPTY_FRAME_CAPTURE_UNAVAILABLE_THRESHOLD
                    ):
                        await self._notify_capture_unavailable()
                    else:
                        logger.debug("Camera stream poll returned no frame")

                await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            raise
        finally:
            await self._stop_host_stream()

    @staticmethod
    def _scanner_is_connected() -> bool:
        from app.scanner.service import scanner_service

        return scanner_service.is_connected

    @staticmethod
    def _base_url(settings: RuntimeSettings) -> str:
        return (
            f"http://{settings.camera_stream_host}:"
            f"{settings.camera_stream_port}"
        )

    def _post_host_stream_start(self, settings: RuntimeSettings) -> bool:
        request = urllib.request.Request(
            f"{self._base_url(settings)}/camera/stream/start",
            method="POST",
            data=b"",
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                if 200 <= response.status < 300:
                    logger.debug(
                        "Camera stream host started at %s",
                        self._base_url(settings),
                    )
                    return True
                logger.debug(
                    "Camera stream host start returned HTTP %s at %s",
                    response.status,
                    self._base_url(settings),
                )
                return False
        except urllib.error.URLError as exc:
            logger.debug("Camera stream start failed: %s", exc)
            return False

    def _post_host_stream_stop(self, settings: RuntimeSettings) -> None:
        request = urllib.request.Request(
            f"{self._base_url(settings)}/camera/stream/stop",
            method="POST",
            data=b"",
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0):
                logger.debug("Camera stream host stopped")
                return
        except urllib.error.URLError as exc:
            logger.debug("Camera stream stop failed: %s", exc)

    def _fetch_frame(self, settings: RuntimeSettings) -> bytes:
        request = urllib.request.Request(
            f"{self._base_url(settings)}/camera/frame",
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:
                if response.status == 204:
                    return b""
                return response.read()
        except urllib.error.URLError as exc:
            logger.debug("Camera frame fetch failed: %s", exc)
            return b""

    async def _notify_capture_unavailable(self) -> None:
        if self._capture_unavailable_notified:
            return

        self._capture_unavailable_notified = True
        logger.info(CAPTURE_UNAVAILABLE_MESSAGE)
        await camera_ws_manager.broadcast_text(
            json.dumps(
                {
                    "status": CAPTURE_UNAVAILABLE_STATUS,
                    "message": CAPTURE_UNAVAILABLE_MESSAGE,
                }
            )
        )

    async def _stop_host_stream(self) -> None:
        if not self._host_stream_active:
            return

        settings = get_runtime_settings()
        await asyncio.to_thread(self._post_host_stream_stop, settings)
        self._host_stream_active = False
        self._consecutive_empty_frames = 0
        self._capture_unavailable_notified = False


camera_stream_service = CameraStreamService()
