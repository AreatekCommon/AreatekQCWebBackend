import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.runtime_settings import RuntimeSettings
from app.scanner.camera_stream import CameraStreamService


class CameraStreamServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_relay_stops_host_stream(self) -> None:
        service = CameraStreamService()
        service._host_stream_active = True

        with patch.object(service, "_stop_host_stream", new=MagicMock()) as stop_host:
            stop_host.return_value = asyncio.sleep(0)
            await service.stop_relay()
            stop_host.assert_called_once()

        self.assertIsNone(service._relay_task)

    async def test_relay_loop_stops_when_no_subscribers(self) -> None:
        service = CameraStreamService()

        with patch(
            "app.scanner.camera_stream.camera_ws_manager.count",
            side_effect=[1, 0],
        ), patch(
            "app.scanner.camera_stream.get_runtime_settings",
            return_value=RuntimeSettings(camera_stream_enabled=False),
        ), patch.object(service, "_stop_host_stream") as stop_host:
            await service._relay_loop()
            stop_host.assert_awaited_once()

    def test_notify_scanner_disconnected_sync_clears_host_flag(self) -> None:
        service = CameraStreamService()
        service._host_stream_active = True

        with patch.object(service, "_post_host_stream_stop") as stop_host:
            service.notify_scanner_disconnected_sync()
            stop_host.assert_called_once()

        self.assertFalse(service._host_stream_active)

    async def test_on_subscriber_disconnected_stops_when_last_client(self) -> None:
        service = CameraStreamService()

        with patch(
            "app.scanner.camera_stream.camera_ws_manager.count",
            return_value=0,
        ), patch.object(service, "stop_relay", new=MagicMock()) as stop_relay:
            stop_relay.return_value = asyncio.sleep(0)
            await service.on_subscriber_disconnected()
            stop_relay.assert_called_once()

    async def test_notify_capture_unavailable_broadcasts_once(self) -> None:
        service = CameraStreamService()

        with patch(
            "app.scanner.camera_stream.camera_ws_manager.broadcast_text",
            new_callable=AsyncMock,
        ) as broadcast_text:
            await service._notify_capture_unavailable()
            await service._notify_capture_unavailable()
            broadcast_text.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
