from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.models.runtime_settings import RuntimeSettings
from app.pipeline.service import PipelineService
from app.settings_sections import SETTINGS_SECTION_DEVICE_PARAMS


class PipelineScannerSettingsApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = PipelineService()

    @patch("app.pipeline.service.scanner_service")
    def test_apply_scanner_settings_section_fails_when_disconnected(
        self,
        scanner_service: MagicMock,
    ) -> None:
        scanner_service.ensure_connected.return_value = False
        settings = RuntimeSettings()
        previous = RuntimeSettings()

        with patch.object(self.pipeline, "_init_wake_event") as wake_event:
            result = self.pipeline._apply_scanner_settings_section(
                SETTINGS_SECTION_DEVICE_PARAMS,
                settings,
                previous,
            )

        self.assertFalse(result.applied)
        self.assertIn("saved to file only", result.apply_error or "")
        wake_event.set.assert_called_once()
        scanner_service.apply_section.assert_not_called()

    @patch("app.pipeline.service.scanner_service")
    def test_apply_scanner_settings_section_applies_when_connected(
        self,
        scanner_service: MagicMock,
    ) -> None:
        scanner_service.ensure_connected.return_value = True
        settings = RuntimeSettings()
        previous = RuntimeSettings()

        result = self.pipeline._apply_scanner_settings_section(
            SETTINGS_SECTION_DEVICE_PARAMS,
            settings,
            previous,
        )

        self.assertTrue(result.applied)
        scanner_service.apply_section.assert_called_once()

    @patch("app.pipeline.service.get_runtime_settings")
    @patch("app.pipeline.service.scanner_service")
    def test_reload_scanner_starts_when_disconnected(
        self,
        scanner_service: MagicMock,
        get_runtime_settings: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        scanner_service.is_connected = False

        self.pipeline.reload_scanner()

        scanner_service.start.assert_called_once()
        scanner_service.restart.assert_not_called()

    @patch("app.pipeline.service.get_runtime_settings")
    @patch("app.pipeline.service.scanner_service")
    def test_reload_scanner_restarts_when_connected(
        self,
        scanner_service: MagicMock,
        get_runtime_settings: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        scanner_service.is_connected = True

        self.pipeline.reload_scanner()

        scanner_service.restart.assert_called_once()
        scanner_service.start.assert_not_called()

    @patch("app.pipeline.service.get_runtime_settings")
    @patch("app.pipeline.service.scanner_service")
    def test_reload_scanner_stops_running_cycle_before_restart(
        self,
        scanner_service: MagicMock,
        get_runtime_settings: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        scanner_service.is_connected = True
        self.pipeline._state = "running"

        with patch.object(self.pipeline, "stop_cycle") as stop_cycle:
            self.pipeline.reload_scanner()

        stop_cycle.assert_called_once()
        scanner_service.restart.assert_called_once()

    @patch("app.pipeline.service.get_runtime_settings")
    @patch("app.pipeline.service.scanner_service")
    def test_reconnect_scanner_calls_force_reconnect(
        self,
        scanner_service: MagicMock,
        get_runtime_settings: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        scanner_service.is_connected = False

        with patch.object(self.pipeline, "_init_wake_event") as wake_event:
            self.pipeline.reconnect_scanner()

        scanner_service.force_reconnect.assert_called_once()
        scanner_service.start.assert_not_called()
        scanner_service.restart.assert_not_called()
        wake_event.set.assert_called_once()

    @patch("app.pipeline.service.get_runtime_settings")
    @patch("app.pipeline.service.scanner_service")
    def test_reconnect_scanner_stops_running_cycle_before_force_reconnect(
        self,
        scanner_service: MagicMock,
        get_runtime_settings: MagicMock,
    ) -> None:
        get_runtime_settings.return_value = RuntimeSettings()
        self.pipeline._state = "running"

        with patch.object(self.pipeline, "stop_cycle") as stop_cycle:
            self.pipeline.reconnect_scanner()

        stop_cycle.assert_called_once()
        scanner_service.force_reconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
