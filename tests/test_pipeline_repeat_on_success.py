from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.models.pipeline_settings import PipelineSettings
from app.models.runtime_settings import RuntimeSettings
from app.pipeline.cycle import CycleRunResult
from app.pipeline.service import PipelineService


class PipelineRepeatOnSuccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PipelineService()
        self.service._run_lock = MagicMock()
        self.service._run_lock.acquire.return_value = True
        self.service._project_name = "scan_test"
        self.service._robot = MagicMock()
        self.service._defer_project_creation = False
        self.service._cycle_requires_startup_travel = False
        self.service._resume_start_list_index = 1
        self.service._resume_initial_scan_count = 0

    def test_repeat_on_success_runs_two_laps_then_stops_on_abort(self) -> None:
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="repeat_on_success"))
        started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)
        self.service._started_at = started_at
        lap_counter = {"count": 0}

        def execute_lap(_settings: RuntimeSettings) -> CycleRunResult:
            lap_counter["count"] += 1
            if lap_counter["count"] >= 2:
                self.service._abort_event.set()
            return CycleRunResult(project_name=f"scan_test_{lap_counter['count']}")

        with patch(
            "app.pipeline.service.get_runtime_settings",
            return_value=settings,
        ), patch.object(
            self.service,
            "_execute_production_cycle_lap",
            side_effect=execute_lap,
        ), patch(
            "app.pipeline.service.append_cycle_history_entry",
        ), patch.object(
            self.service,
            "_prepare_next_repeat_lap",
        ) as prepare_next, patch(
            "app.pipeline.service.RESTART_DELAY_SEC",
            0.0,
        ):
            self.service._run_cycle_worker()

        self.assertEqual(lap_counter["count"], 2)
        prepare_next.assert_called_once()
        status = self.service.get_status()
        self.assertEqual(status.state, "idle")

    def test_repeat_on_success_does_not_loop_after_exception(self) -> None:
        settings = RuntimeSettings(pipeline=PipelineSettings(cycle_run_mode="repeat_on_success"))
        self.service._started_at = datetime(2026, 7, 31, 10, 0, 0, tzinfo=UTC)

        with patch(
            "app.pipeline.service.get_runtime_settings",
            return_value=settings,
        ), patch.object(
            self.service,
            "_execute_production_cycle_lap",
            side_effect=RuntimeError("Scanner failed"),
        ), patch.object(
            self.service,
            "_prepare_next_repeat_lap",
        ) as prepare_next:
            self.service._run_cycle_worker()

        prepare_next.assert_not_called()
        status = self.service.get_status()
        self.assertEqual(status.state, "error")
        self.assertEqual(status.last_error, "Scanner failed")


if __name__ == "__main__":
    unittest.main()
