from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.api.pipeline import _cycle_start_http_exception, _start_cycle
from app.models.runtime_settings import RuntimeSettings
from app.pipeline.service import PipelineService


class CycleStartHttpExceptionTests(unittest.TestCase):
    def test_connection_error_maps_to_503(self) -> None:
        exc = _cycle_start_http_exception(ConnectionError("lost"))
        self.assertEqual(exc.status_code, 503)
        self.assertIn("connection lost", exc.detail.lower())

    def test_timeout_error_maps_to_503(self) -> None:
        exc = _cycle_start_http_exception(TimeoutError("slow"))
        self.assertEqual(exc.status_code, 503)
        self.assertIn("timed out", exc.detail.lower())

    def test_scanner_busy_maps_to_409(self) -> None:
        exc = _cycle_start_http_exception(
            RuntimeError("Команда 'createSln' еще выполняется")
        )
        self.assertEqual(exc.status_code, 409)
        self.assertIn("busy", exc.detail.lower())

    def test_initializing_maps_to_400(self) -> None:
        exc = _cycle_start_http_exception(
            RuntimeError("Pipeline is still initializing; wait and retry")
        )
        self.assertEqual(exc.status_code, 400)

    def test_unexpected_maps_to_503(self) -> None:
        exc = _cycle_start_http_exception(ValueError("boom"))
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(exc.detail, "boom")


class PipelineStartHandlerTests(unittest.TestCase):
    @patch("app.api.pipeline.pipeline_service.start_cycle")
    def test_start_cycle_propagates_http_exception_on_connection_error(
        self,
        start_cycle: MagicMock,
    ) -> None:
        start_cycle.side_effect = ConnectionError("SDK client is not connected")

        with self.assertRaises(Exception) as ctx:
            _start_cycle()

        self.assertEqual(ctx.exception.status_code, 503)


class PathSaveRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.paths_folder = Path(self.temp_dir.name)
        sample_path = (
            Path(__file__).resolve().parents[1] / "data" / "sample_movement_path.json"
        )
        self.active_path = self.paths_folder / "active_test.json"
        self.active_path.write_text(sample_path.read_text(encoding="utf-8"), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("app.core.runtime_settings_store.get_runtime_settings")
    def test_save_active_document_returns_normalized_document(
        self,
        get_runtime_settings: MagicMock,
    ) -> None:
        from app.trajectory.service import TrajectoryService

        get_runtime_settings.return_value = RuntimeSettings(
            paths_folder=str(self.paths_folder),
            active_path_file="active_test.json",
        )
        service = TrajectoryService()
        payload = json.loads(self.active_path.read_text(encoding="utf-8"))

        saved = service.save_active_document(payload)

        self.assertIsNone(saved.snapshot.load_error)
        self.assertGreater(saved.snapshot.point_count, 0)
        self.assertIn("nodes", saved.normalized_document)
        self.assertIn("points", saved.normalized_document)


class PipelineStartValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = PipelineService()

    @patch("app.pipeline.service.scanner_service")
    @patch("app.pipeline.service.app_state")
    def test_validate_rejects_while_initializing(
        self,
        app_state: MagicMock,
        scanner_service: MagicMock,
    ) -> None:
        self.pipeline._initializing = True
        scanner_service.is_connected = True
        scanner_service.is_connecting.return_value = False
        scanner_service.is_restarting.return_value = False
        app_state.current_position = {"connected": True}

        with patch.object(self.pipeline, "_is_robot_fully_connected", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "initializing"):
                self.pipeline._validate_ready_to_start()

    @patch("app.pipeline.service.scanner_service")
    def test_validate_rejects_while_scanner_connecting(
        self,
        scanner_service: MagicMock,
    ) -> None:
        self.pipeline._initializing = False
        scanner_service.is_connected = True
        scanner_service.is_connecting.return_value = True
        scanner_service.is_restarting.return_value = False

        with self.assertRaisesRegex(RuntimeError, "connecting"):
            self.pipeline._validate_ready_to_start()

    @patch("app.pipeline.service.threading.Thread")
    @patch("app.pipeline.service.prepare_next_project")
    @patch("app.pipeline.service.scanner_service")
    @patch("app.pipeline.service.trajectory_service")
    @patch("app.pipeline.service.app_state")
    def test_begin_cycle_defers_project_creation(
        self,
        app_state: MagicMock,
        trajectory_service: MagicMock,
        scanner_service: MagicMock,
        prepare_next_project: MagicMock,
        thread_cls: MagicMock,
    ) -> None:
        from app.eki.messages import TrajectoryPoint

        thread_instance = MagicMock()
        thread_cls.return_value = thread_instance
        scanner_service.is_connected = True
        scanner_service.is_connecting.return_value = False
        scanner_service.is_restarting.return_value = False
        app_state.current_position = {"connected": True}
        trajectory_service.get_snapshot.return_value = MagicMock(
            load_error=None,
            points=[
                TrajectoryPoint(
                    index=0,
                    guid="0",
                    point_type="scan",
                    comment="scan",
                    speed=50.0,
                    acceleration=50.0,
                    a7=0.0,
                    a7_speed=50.0,
                    a7_acceleration=50.0,
                    axes=[0.0] * 6,
                ),
                TrajectoryPoint(
                    index=1,
                    guid="1",
                    point_type="end",
                    comment="end",
                    speed=50.0,
                    acceleration=50.0,
                    a7=0.0,
                    a7_speed=50.0,
                    a7_acceleration=50.0,
                    axes=[0.0] * 6,
                ),
            ],
        )

        robot = MagicMock()
        robot.connected = True
        robot.turn_connected = True
        robot.STATUS_IDLE = 0
        robot.robot_status = 0
        robot.lock = __import__("threading").Lock()
        self.pipeline._robot = robot

        with patch.object(self.pipeline, "_preflight_startup_travel"):
            self.pipeline._begin_cycle(resume=False)

        prepare_next_project.assert_not_called()
        self.assertTrue(self.pipeline._defer_project_creation)
        self.assertIsNone(self.pipeline._project_name)
        thread_instance.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
