from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.core.cycle_history_repository import build_cycle_history_entry
from app.eki.messages import TrajectoryPoint
from app.models.pipeline_settings import PipelineSettings
from app.models.runtime_settings import RuntimeSettings
from app.pipeline.cycle import CycleRunResult
from app.pipeline.service import PipelineService


def make_point(index: int, point_type: str) -> TrajectoryPoint:
    return TrajectoryPoint(
        index=index,
        guid=str(index),
        point_type=point_type,
        comment=point_type,
        speed=50.0,
        acceleration=50.0,
        a7=0.0,
        a7_speed=50.0,
        a7_acceleration=50.0,
        axes=[float(index)] * 6,
    )


class PipelineCycleTimerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PipelineService()
        self.service._run_lock = MagicMock()
        self.service._run_lock.acquire.return_value = True

    def test_successful_production_cycle_records_last_scan_mode(self) -> None:
        started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)
        position_reached_at = started_at + timedelta(seconds=80.0)
        finished_at = started_at + timedelta(seconds=125.4)
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="single_last_scan"))
        cycle_result = CycleRunResult(
            project_name="scan_test",
            last_position_reached_at=position_reached_at,
        )

        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False
        self.service._resume_start_list_index = 1
        self.service._resume_initial_scan_count = 0

        with patch(
            "app.pipeline.service.get_runtime_settings",
            return_value=settings,
        ), patch.object(
            self.service,
            "_execute_production_cycle_lap",
            return_value=cycle_result,
        ), patch(
            "app.pipeline.service.append_cycle_history_entry",
        ), patch(
            "app.pipeline.service.datetime",
        ) as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            mock_datetime.now.side_effect = [started_at, finished_at]
            self.service._run_cycle_worker()

        status = self.service.get_status()
        self.assertAlmostEqual(status.last_cycle_duration_sec, 80.0, places=1)
        self.assertEqual(status.last_cycle_timing_mode, "last_scan")

    def test_successful_production_cycle_records_full_cycle_mode(self) -> None:
        started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)
        finished_at = started_at + timedelta(seconds=300.0)
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="single_full"))
        cycle_result = CycleRunResult(project_name="scan_test")

        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False
        self.service._resume_start_list_index = 1
        self.service._resume_initial_scan_count = 0

        with patch(
            "app.pipeline.service.get_runtime_settings",
            return_value=settings,
        ), patch.object(
            self.service,
            "_execute_production_cycle_lap",
            return_value=cycle_result,
        ), patch(
            "app.pipeline.service.append_cycle_history_entry",
        ), patch(
            "app.pipeline.service.datetime",
        ) as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            mock_datetime.now.side_effect = [started_at, finished_at]
            self.service._run_cycle_worker()

        status = self.service.get_status()
        self.assertAlmostEqual(status.last_cycle_duration_sec, 300.0, places=1)
        self.assertEqual(status.last_cycle_timing_mode, "full_cycle")

    def test_single_last_scan_lap_travels_home(self) -> None:
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="single_last_scan"))
        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False
        self.service._resume_start_list_index = 1
        self.service._resume_initial_scan_count = 0

        with patch(
            "app.pipeline.service.run_cycle",
            return_value=CycleRunResult(project_name="scan_test"),
        ), patch.object(
            self.service,
            "_travel_to_home",
        ) as travel_to_home, patch(
            "app.pipeline.service.trajectory_service.get_snapshot",
            return_value=MagicMock(per_point_exposure=False, per_point_marker_exposure=False),
        ):
            result = self.service._execute_production_cycle_lap(settings)

        self.assertEqual(result.project_name, "scan_test")
        travel_to_home.assert_called_once()

    def test_abort_does_not_record_cycle_timer(self) -> None:
        started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)
        self.service._started_at = started_at
        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False

        with patch.object(
            self.service,
            "_execute_production_cycle_lap",
            side_effect=RuntimeError("Cycle aborted"),
        ):
            self.service._run_cycle_worker()

        status = self.service.get_status()
        self.assertIsNone(status.last_cycle_duration_sec)
        self.assertIsNone(status.last_cycle_timing_mode)

    def test_successful_lap_appends_cycle_history_entry(self) -> None:
        started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)
        export_at = started_at + timedelta(seconds=90.0)
        finished_at = started_at + timedelta(seconds=125.0)
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="single_full"))
        cycle_result = CycleRunResult(
            project_name="scan_test",
            mesh_export_finished_at=export_at,
        )

        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False
        self.service._resume_start_list_index = 1
        self.service._resume_initial_scan_count = 0

        with patch(
            "app.pipeline.service.get_runtime_settings",
            return_value=settings,
        ), patch.object(
            self.service,
            "_execute_production_cycle_lap",
            return_value=cycle_result,
        ), patch(
            "app.pipeline.service.append_cycle_history_entry",
        ) as append_mock, patch(
            "app.pipeline.service.build_cycle_history_entry",
            wraps=build_cycle_history_entry,
        ), patch(
            "app.pipeline.service.datetime",
        ) as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            mock_datetime.now.side_effect = [started_at, finished_at]
            self.service._run_cycle_worker()

        append_mock.assert_called_once()
        entry = append_mock.call_args[0][0]
        self.assertEqual(entry.project_name, "scan_test")
        self.assertEqual(entry.mesh_export_finished_at, export_at)
        self.assertAlmostEqual(entry.duration_sec, 90.0, places=1)

    def test_repeat_on_success_history_uses_lap_completion_fallback(self) -> None:
        started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)
        finished_at = started_at + timedelta(seconds=225.0)
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="repeat_on_success"))

        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False
        self.service._resume_start_list_index = 1
        self.service._resume_initial_scan_count = 0

        def execute_lap(_settings: RuntimeSettings) -> CycleRunResult:
            self.service._abort_event.set()
            return CycleRunResult(project_name="scan_test")

        with patch(
            "app.pipeline.service.get_runtime_settings",
            return_value=settings,
        ), patch.object(
            self.service,
            "_execute_production_cycle_lap",
            side_effect=execute_lap,
        ), patch(
            "app.pipeline.service.append_cycle_history_entry",
        ) as append_mock, patch(
            "app.pipeline.service.build_cycle_history_entry",
            wraps=build_cycle_history_entry,
        ), patch.object(
            self.service,
            "_prepare_next_repeat_lap",
        ), patch(
            "app.pipeline.service.RESTART_DELAY_SEC",
            0.0,
        ), patch(
            "app.pipeline.service.datetime",
        ) as mock_datetime:
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            mock_datetime.now.side_effect = [started_at, finished_at, finished_at]
            self.service._run_cycle_worker()

        append_mock.assert_called_once()
        entry = append_mock.call_args[0][0]
        self.assertEqual(entry.project_name, "scan_test")
        self.assertIsNone(entry.mesh_export_finished_at)
        self.assertAlmostEqual(entry.duration_sec, 225.0, places=1)

    def test_new_cycle_start_clears_previous_timer(self) -> None:
        self.service._last_cycle_duration_sec = 42.0
        self.service._last_cycle_timing_mode = "full_cycle"

        scan_point = make_point(0, "scan")
        end_point = make_point(1, "end")
        snapshot = MagicMock()
        snapshot.points = [scan_point, end_point]

        with patch.object(self.service, "_validate_ready_to_start"), patch.object(
            self.service,
            "_preflight_startup_travel",
        ), patch.object(
            self.service,
            "_create_project",
        ), patch.object(self.service, "_set_state"), patch(
            "app.pipeline.service.trajectory_service.get_snapshot",
            return_value=snapshot,
        ), patch(
            "app.pipeline.service.threading.Thread",
        ) as thread_cls:
            thread_cls.return_value = MagicMock()
            self.service.start_cycle()

        status = self.service.get_status()
        self.assertIsNone(status.last_cycle_duration_sec)
        self.assertIsNone(status.last_cycle_timing_mode)


if __name__ == "__main__":
    unittest.main()
