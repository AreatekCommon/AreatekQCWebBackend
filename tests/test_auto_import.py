from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from auto_import import ScanFolderWatcher, ScanFolderWatcherSettings


def make_settings(
    scans_root: Path,
    monitored_folder: Path,
    *,
    stable_age_s: float = 0.0,
    open_pdf_after_move: bool = False,
) -> ScanFolderWatcherSettings:
    return ScanFolderWatcherSettings(
        scans_root=str(scans_root),
        monitored_folder=str(monitored_folder),
        poll_interval_s=0.01,
        stable_age_s=stable_age_s,
        directory_copy_retry_s=0.01,
        open_pdf_after_move=open_pdf_after_move,
    )


def create_scan_folder(export_root: Path, name: str) -> Path:
    scan_dir = export_root / name
    scan_dir.mkdir(parents=True, exist_ok=True)
    stl_path = scan_dir / f"{name}.stl"
    stl_path.write_bytes(b"solid test")
    return scan_dir


class ScanFolderWatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.export_root = Path(self.temp_dir.name) / "export"
        self.monitored_folder = Path(self.temp_dir.name) / "monitored"
        self.export_root.mkdir(parents=True, exist_ok=True)
        self.monitored_folder.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def make_watcher(self, *, open_pdf_after_move: bool = False) -> ScanFolderWatcher:
        return ScanFolderWatcher(
            make_settings(
                self.export_root,
                self.monitored_folder,
                open_pdf_after_move=open_pdf_after_move,
            )
        )

    def test_picks_scan_folder_and_copies_stl_with_same_name(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()

        copied = self.monitored_folder / "Brake_20260804_120000.stl"
        self.assertTrue(copied.is_file())
        self.assertIsNotNone(watcher.active_job)
        self.assertEqual(watcher.active_job.folder_name, "Brake_20260804_120000")

    def test_does_not_pick_second_scan_while_job_active(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")
        create_scan_folder(self.export_root, "Brake_20260804_130000")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            watcher._pick_and_start_next_scan()

        self.assertFalse((self.monitored_folder / "Brake_20260804_130000.stl").exists())

    def test_success_moves_pdf_to_reports_and_removes_empty_source_folder(self) -> None:
        scan_dir = create_scan_folder(self.export_root, "Brake_20260804_120000")
        pdf_path = self.export_root / "report.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            monitored_stl = self.monitored_folder / "Brake_20260804_120000.stl"
            monitored_stl.unlink()
            watcher._await_outcome()
            watcher._poll_pdf_reports()

        report_path = self.export_root / "reports" / "Brake_20260804_120000.pdf"
        self.assertTrue(report_path.is_file())
        self.assertFalse(pdf_path.exists())
        self.assertFalse(scan_dir.exists())
        self.assertIsNone(watcher.active_job)

    def test_late_pdf_after_stl_consume_moves_to_reports(self) -> None:
        scan_dir = create_scan_folder(self.export_root, "Brake_20260804_120000")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            monitored_stl = self.monitored_folder / "Brake_20260804_120000.stl"
            monitored_stl.unlink()
            watcher._await_outcome()

            self.assertFalse(scan_dir.exists())
            self.assertIsNone(watcher.active_job)

            pdf_path = self.export_root / "late_report.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            watcher._poll_pdf_reports()

        report_path = self.export_root / "reports" / "Brake_20260804_120000.pdf"
        self.assertTrue(report_path.is_file())
        self.assertFalse(pdf_path.exists())

    def test_pdf_while_job_active_uses_active_folder_name(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")
        pdf_path = self.export_root / "report.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            watcher._poll_pdf_reports()

        report_path = self.export_root / "reports" / "Brake_20260804_120000.pdf"
        self.assertTrue(report_path.is_file())
        self.assertFalse(pdf_path.exists())
        self.assertIsNotNone(watcher.active_job)

    def test_opens_pdf_after_move_when_enabled(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")
        pdf_path = self.export_root / "report.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")

        watcher = self.make_watcher(open_pdf_after_move=True)
        with patch.object(watcher, "_wait_until_stable"), patch(
            "auto_import.os.startfile"
        ) as startfile:
            watcher._pick_and_start_next_scan()
            watcher._poll_pdf_reports()

        report_path = self.export_root / "reports" / "Brake_20260804_120000.pdf"
        startfile.assert_called_once_with(str(report_path))

    def test_leaves_pdf_when_no_folder_name_known(self) -> None:
        pdf_path = self.export_root / "orphan.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._poll_pdf_reports()

        self.assertTrue(pdf_path.exists())
        self.assertFalse((self.export_root / "reports" / "orphan.pdf").exists())

    def test_failure_clears_last_name_so_pdf_is_not_claimed(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")
        failed_dir = self.export_root / "Failed_imports" / "Brake_20260804_120000"
        failed_dir.mkdir(parents=True, exist_ok=True)

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            watcher._await_outcome()

            pdf_path = self.export_root / "report.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            watcher._poll_pdf_reports()

        self.assertIsNone(watcher.active_job)
        self.assertTrue(pdf_path.exists())
        self.assertFalse(
            (self.export_root / "reports" / "Brake_20260804_120000.pdf").exists()
        )

    def test_completes_when_monitored_stl_removed_even_without_pdf(self) -> None:
        scan_dir = create_scan_folder(self.export_root, "Brake_20260804_120000")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            monitored_stl = self.monitored_folder / "Brake_20260804_120000.stl"
            monitored_stl.unlink()
            watcher._await_outcome()

        self.assertFalse(scan_dir.exists())
        self.assertIsNone(watcher.active_job)

    def test_does_not_complete_while_monitored_stl_present(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            watcher._await_outcome()

        self.assertIsNotNone(watcher.active_job)
        self.assertEqual(watcher.active_job.folder_name, "Brake_20260804_120000")

    def test_failure_clears_active_job(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")
        failed_dir = self.export_root / "Failed_imports" / "Brake_20260804_120000"
        failed_dir.mkdir(parents=True, exist_ok=True)

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            watcher._await_outcome()

        self.assertIsNone(watcher.active_job)

    def test_failure_allows_next_scan_on_following_pick(self) -> None:
        create_scan_folder(self.export_root, "Brake_20260804_120000")
        create_scan_folder(self.export_root, "Brake_20260804_130000")
        failed_dir = self.export_root / "Failed_imports" / "Brake_20260804_120000"
        failed_dir.mkdir(parents=True, exist_ok=True)

        watcher = self.make_watcher()
        with patch.object(watcher, "_wait_until_stable"):
            watcher._pick_and_start_next_scan()
            watcher._await_outcome()
            watcher._pick_and_start_next_scan()

        self.assertTrue((self.monitored_folder / "Brake_20260804_130000.stl").exists())
        self.assertEqual(watcher.active_job.folder_name, "Brake_20260804_130000")

    def test_ignores_reserved_and_non_matching_folders(self) -> None:
        (self.export_root / "Successful_imports").mkdir()
        (self.export_root / "Failed_imports").mkdir()
        (self.export_root / "reports").mkdir()
        (self.export_root / "empty_folder").mkdir()
        create_scan_folder(self.export_root, "Brake_20260804_120000")

        watcher = self.make_watcher()
        pending = [
            item.name
            for item in self.export_root.iterdir()
            if watcher._is_pending_scan_folder(item)
        ]
        self.assertEqual(pending, ["Brake_20260804_120000"])


if __name__ == "__main__":
    unittest.main()
