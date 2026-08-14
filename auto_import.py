from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ScanFolderWatcherSettings:
    scans_root: str = r"C:\Users\Areatek\Desktop\scans"
    monitored_folder: str = ""
    successful_imports_dir_name: str = "Successful_imports"
    failed_imports_dir_name: str = "Failed_imports"
    reports_dir_name: str = "reports"
    poll_interval_s: float = 1.0
    stable_age_s: float = 2.0
    directory_copy_retry_s: float = 0.5
    open_pdf_after_move: bool = True
    log_level: int = logging.INFO


@dataclass
class ActiveScanJob:
    folder_name: str
    source_dir: Path
    source_stl: Path
    monitored_stl: Path
    started_at: float


class ScanFolderWatcher:
    def __init__(self, settings: ScanFolderWatcherSettings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_job: Optional[ActiveScanJob] = None
        self._last_scan_folder_name: Optional[str] = None
        self._last_scan_started_at: Optional[float] = None

        self._root = Path(settings.scans_root)
        self._monitored = Path(settings.monitored_folder) if settings.monitored_folder else None
        self._successful = self._root / settings.successful_imports_dir_name
        self._failed = self._root / settings.failed_imports_dir_name
        self._reports = self._root / settings.reports_dir_name

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._logger.debug("Watcher already running")
            return

        self._logger.setLevel(self._settings.log_level)
        self._ensure_directories()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="ScanFolderWatcher", daemon=True)
        self._thread.start()
        self._logger.info("ScanFolderWatcher started")

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self._logger.info("ScanFolderWatcher stopped")

    @property
    def active_job(self) -> Optional[ActiveScanJob]:
        return self._active_job

    def _ensure_directories(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._successful.mkdir(parents=True, exist_ok=True)
        self._failed.mkdir(parents=True, exist_ok=True)
        self._reports.mkdir(parents=True, exist_ok=True)
        if self._monitored is not None:
            self._monitored.mkdir(parents=True, exist_ok=True)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self._settings.monitored_folder.strip():
                    self._logger.debug("Monitored folder not configured; skipping scan pickup")
                elif self._active_job is not None:
                    self._await_outcome()
                else:
                    self._pick_and_start_next_scan()
                self._poll_pdf_reports()
            except Exception:
                self._logger.exception("Unexpected error in ScanFolderWatcher loop")
            self._stop_event.wait(self._settings.poll_interval_s)

    def _reserved_dir_names(self) -> set[str]:
        return {
            self._settings.successful_imports_dir_name,
            self._settings.failed_imports_dir_name,
            self._settings.reports_dir_name,
            "processed",
        }

    def _is_pending_scan_folder(self, path: Path) -> bool:
        if not path.is_dir():
            return False
        if path.name in self._reserved_dir_names():
            return False
        if path.parent != self._root:
            return False
        if self._has_failure_signal(path.name):
            return False

        stl_path = path / f"{path.name}.stl"
        return stl_path.is_file()

    def _pick_and_start_next_scan(self) -> None:
        if self._monitored is None:
            return

        scan_dirs = [
            item
            for item in self._root.iterdir()
            if self._is_pending_scan_folder(item)
        ]
        if not scan_dirs:
            return

        scan_dirs.sort(key=self._path_sort_key)
        source_dir = scan_dirs[0]
        source_stl = source_dir / f"{source_dir.name}.stl"

        self._wait_until_stable(source_stl)
        if not source_stl.exists():
            return

        destination_stl = self._monitored / source_stl.name
        self._logger.info("Copying STL %s -> %s", source_stl, destination_stl)
        shutil.copy2(source_stl, destination_stl)

        started_at = time.time()
        self._active_job = ActiveScanJob(
            folder_name=source_dir.name,
            source_dir=source_dir,
            source_stl=source_stl,
            monitored_stl=destination_stl,
            started_at=started_at,
        )
        self._last_scan_folder_name = source_dir.name
        self._last_scan_started_at = started_at
        self._logger.info("Started scan import job for %s", source_dir.name)

    def _await_outcome(self) -> None:
        job = self._active_job
        if job is None:
            return

        if self._has_failure_signal(job.folder_name):
            self._finalize_failure(job)
            return

        if job.monitored_stl.exists():
            return

        self._finalize_after_consumed(job)

    def _has_failure_signal(self, folder_name: str) -> bool:
        if not self._failed.exists():
            return False

        for item in self._failed.iterdir():
            if item.name == folder_name:
                return True
            if item.is_file() and item.name == f"{folder_name}.stl":
                return True
        return False

    def _report_folder_name(self) -> Optional[str]:
        if self._active_job is not None:
            return self._active_job.folder_name
        return self._last_scan_folder_name

    def _report_started_at(self) -> Optional[float]:
        if self._active_job is not None:
            return self._active_job.started_at
        return self._last_scan_started_at

    def _find_success_pdf(self, started_at: float) -> Optional[Path]:
        candidates: list[Path] = []
        for item in self._root.iterdir():
            if not item.is_file() or item.suffix.lower() != ".pdf":
                continue
            try:
                if item.stat().st_mtime >= started_at - 0.5:
                    candidates.append(item)
            except FileNotFoundError:
                continue

        if not candidates:
            return None

        candidates.sort(key=self._path_sort_key)
        return candidates[0]

    def _poll_pdf_reports(self) -> None:
        folder_name = self._report_folder_name()
        started_at = self._report_started_at()
        if folder_name is None or started_at is None:
            return

        pdf_path = self._find_success_pdf(started_at)
        if pdf_path is None:
            return

        self._wait_until_stable(pdf_path)
        if not pdf_path.exists():
            return

        target_path = self._build_report_target(folder_name)
        self._logger.info("Moving PDF report %s -> %s", pdf_path, target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pdf_path), str(target_path))

        if self._settings.open_pdf_after_move:
            self._open_pdf_with_default_app(target_path)

    def _finalize_after_consumed(self, job: ActiveScanJob) -> None:
        if job.source_dir.exists():
            shutil.rmtree(job.source_dir, ignore_errors=True)
            self._logger.info("Removed source scan directory: %s", job.source_dir)
        self._active_job = None
        self._logger.info("Completed scan import job for %s", job.folder_name)

    def _finalize_failure(self, job: ActiveScanJob) -> None:
        self._logger.warning(
            "Scan import failed for %s; continuing with next scan folder",
            job.folder_name,
        )
        if self._last_scan_folder_name == job.folder_name:
            self._last_scan_folder_name = None
            self._last_scan_started_at = None
        self._active_job = None

    def _build_report_target(self, scan_name: str) -> Path:
        target = self._reports / f"{scan_name}.pdf"
        if not target.exists():
            return target

        idx = 1
        while True:
            candidate = self._reports / f"{scan_name}_{idx}.pdf"
            if not candidate.exists():
                return candidate
            idx += 1

    def _wait_until_stable(self, path: Path) -> None:
        stable_for = self._settings.stable_age_s
        while not self._stop_event.is_set():
            try:
                stat1 = path.stat()
            except FileNotFoundError:
                return

            time.sleep(self._settings.directory_copy_retry_s)

            try:
                stat2 = path.stat()
            except FileNotFoundError:
                return

            unchanged = (
                stat1.st_size == stat2.st_size
                and int(stat1.st_mtime) == int(stat2.st_mtime)
            )
            age_ok = (time.time() - stat2.st_mtime) >= stable_for
            if unchanged and age_ok:
                return

    def _open_pdf_with_default_app(self, pdf_path: Path) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(pdf_path))
                self._logger.info("Opened PDF with default application: %s", pdf_path)
            else:
                self._logger.warning(
                    "os.startfile is unavailable on this platform, PDF was not opened: %s",
                    pdf_path,
                )
        except Exception:
            self._logger.exception("Failed to open PDF with default application: %s", pdf_path)

    @staticmethod
    def _path_sort_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, path.name.lower())
        except FileNotFoundError:
            return (float("inf"), path.name.lower())
