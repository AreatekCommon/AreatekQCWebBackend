from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.cycle_history_repository import (
    append_cycle_history_entry,
    build_cycle_history_entry,
    load_cycle_history,
)
from app.models.cycle_history import MAX_CYCLE_HISTORY_ENTRIES


class CycleHistoryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "cycle_history.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_append_and_load_entry_with_duration(self) -> None:
        started_at = datetime(2026, 8, 4, 10, 0, 0, tzinfo=UTC)
        export_at = started_at + timedelta(seconds=155.3)
        entry = build_cycle_history_entry(
            started_at=started_at,
            project_name="scan_20260804_100000",
            mesh_export_finished_at=export_at,
        )

        append_cycle_history_entry(entry, path=self.path)
        document = load_cycle_history(path=self.path)

        self.assertEqual(len(document.entries), 1)
        self.assertEqual(document.entries[0].project_name, "scan_20260804_100000")
        self.assertAlmostEqual(document.entries[0].duration_sec, 155.3, places=1)

    def test_entry_without_export_has_null_duration(self) -> None:
        started_at = datetime(2026, 8, 4, 10, 0, 0, tzinfo=UTC)
        entry = build_cycle_history_entry(
            started_at=started_at,
            project_name="scan_last_only",
            mesh_export_finished_at=None,
        )

        append_cycle_history_entry(entry, path=self.path)
        document = load_cycle_history(path=self.path)

        self.assertEqual(len(document.entries), 1)
        self.assertIsNone(document.entries[0].mesh_export_finished_at)
        self.assertIsNone(document.entries[0].duration_sec)

    def test_entry_uses_timing_end_at_when_export_missing(self) -> None:
        started_at = datetime(2026, 8, 4, 10, 0, 0, tzinfo=UTC)
        timing_end_at = started_at + timedelta(seconds=92.5)
        entry = build_cycle_history_entry(
            started_at=started_at,
            project_name="scan_last_only",
            mesh_export_finished_at=None,
            timing_end_at=timing_end_at,
        )

        self.assertAlmostEqual(entry.duration_sec, 92.5, places=1)

    def test_history_is_capped_at_max_entries(self) -> None:
        started_at = datetime(2026, 8, 4, 10, 0, 0, tzinfo=UTC)

        for index in range(MAX_CYCLE_HISTORY_ENTRIES + 5):
            append_cycle_history_entry(
                build_cycle_history_entry(
                    started_at=started_at + timedelta(seconds=index),
                    project_name=f"scan_{index}",
                    mesh_export_finished_at=None,
                ),
                path=self.path,
            )

        document = load_cycle_history(path=self.path)
        self.assertEqual(len(document.entries), MAX_CYCLE_HISTORY_ENTRIES)
        self.assertEqual(document.entries[0].project_name, "scan_5")
        self.assertEqual(document.entries[-1].project_name, f"scan_{MAX_CYCLE_HISTORY_ENTRIES + 4}")


if __name__ == "__main__":
    unittest.main()
