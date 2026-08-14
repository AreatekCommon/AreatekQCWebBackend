from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.app_state import app_state
from app.core.fixed_paths import KUKA_TRAJECTORIES_DIR
from app.core.messages import auto_parsed_trajectory_filename
from app.trajectory.kuka_import import (
    KukaImportError,
    KukaImportPipelineBusyError,
    import_kuka_to_trajectories,
)


@dataclass(frozen=True)
class KukaFolderWatcherSettings:
    source_dir: Path = KUKA_TRAJECTORIES_DIR
    poll_interval_s: float = 1.0
    stable_age_s: float = 2.0
    stable_check_interval_s: float = 0.5


class KukaFolderWatcher:
    def __init__(self, settings: KukaFolderWatcherSettings | None = None) -> None:
        self._settings = settings or KukaFolderWatcherSettings()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._processed_mtimes: dict[str, float] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="KukaFolderWatcher", daemon=True)
        self._thread.start()
        self._logger.info("KukaFolderWatcher started")

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        self._logger.info("KukaFolderWatcher stopped")

    def process_once(self) -> None:
        self._scan_source_dir()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._scan_source_dir()
            except Exception:
                self._logger.exception("Unexpected error in KukaFolderWatcher loop")
            self._stop_event.wait(self._settings.poll_interval_s)

    def _scan_source_dir(self) -> None:
        source_dir = self._settings.source_dir
        if not source_dir.is_dir():
            return

        for entry in sorted(source_dir.iterdir()):
            if not entry.is_file() or entry.suffix.lower() != ".json":
                continue
            self._maybe_import(entry)

    def _maybe_import(self, source_path: Path) -> None:
        try:
            mtime = source_path.stat().st_mtime
        except FileNotFoundError:
            return

        key = str(source_path.resolve())
        last_processed = self._processed_mtimes.get(key)
        if last_processed is not None and mtime <= last_processed:
            return

        if not self._is_stable(source_path):
            return

        output_filename = auto_parsed_trajectory_filename(app_state.ui_locale)
        try:
            result = import_kuka_to_trajectories(
                source_path,
                output_filename,
                set_active=False,
                overwrite=True,
            )
        except KukaImportPipelineBusyError:
            self._logger.debug("Skipping KUKA import while pipeline is busy: %s", source_path.name)
            return
        except KukaImportError as exc:
            self._logger.warning("Failed to auto-import KUKA trajectory %s: %s", source_path.name, exc)
            return

        self._logger.info(
            "Auto-imported KUKA trajectory %s -> %s",
            source_path.name,
            result.output_path,
        )

        try:
            source_path.unlink(missing_ok=True)
            self._processed_mtimes.pop(key, None)
            self._logger.info("Deleted parsed KUKA source file %s", source_path.name)
        except OSError as exc:
            self._logger.warning(
                "Failed to delete parsed KUKA source file %s: %s",
                source_path.name,
                exc,
            )
            try:
                self._processed_mtimes[key] = source_path.stat().st_mtime
            except FileNotFoundError:
                self._processed_mtimes.pop(key, None)

    def _is_stable(self, path: Path) -> bool:
        stable_for = self._settings.stable_age_s
        try:
            stat1 = path.stat()
        except FileNotFoundError:
            return False

        time.sleep(self._settings.stable_check_interval_s)

        try:
            stat2 = path.stat()
        except FileNotFoundError:
            return False

        unchanged = (
            stat1.st_size == stat2.st_size
            and int(stat1.st_mtime) == int(stat2.st_mtime)
        )
        age_ok = (time.time() - stat2.st_mtime) >= stable_for
        return unchanged and age_ok


kuka_folder_watcher = KukaFolderWatcher()
