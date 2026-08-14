from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.logger import get_logger

if TYPE_CHECKING:
    from app.models.runtime_settings import RuntimeSettings

logger = get_logger(__name__)

POLL_INTERVAL_SEC = 1.0
MIRROR_FILENAME = "mirror.log"
SOURCES_FILENAME = "sources.json"


def resolve_native_log_dir(process_path: str, override: str = "") -> Path | None:
    if override.strip():
        candidate = Path(override.strip())
    else:
        candidate = Path(process_path).parent / "log"

    if candidate.is_dir():
        return candidate
    return None


def discover_native_log_dirs(process_path: str, override: str = "") -> list[Path]:
    dirs: list[Path] = []
    primary = resolve_native_log_dir(process_path, override)
    if primary is not None:
        dirs.append(primary)

    install_dir = Path(process_path).parent
    syncservice_log = install_dir / "syncservice" / "log"
    if syncservice_log.is_dir() and syncservice_log not in dirs:
        dirs.append(syncservice_log)

    return dirs


class SdkLogCollector:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._mirror_path: Path | None = None
        self._sources_path: Path | None = None
        self._file_offsets: dict[Path, int] = {}
        self._file_mtimes: dict[Path, int] = {}
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, settings: RuntimeSettings) -> None:
        if not settings.sdk_log_enabled:
            self.stop()
            return

        self.stop()

        base_dir = Path(settings.sdk_log_dir)
        native_dir = base_dir / "sdk_native"
        native_dir.mkdir(parents=True, exist_ok=True)

        session_stamp = datetime.now().strftime("%Y%m%d")
        self._mirror_path = native_dir / f"mirror_{session_stamp}.log"
        self._sources_path = native_dir / SOURCES_FILENAME

        source_dirs = discover_native_log_dirs(
            settings.scanner.process_path,
            settings.sdk_native_log_source,
        )
        if not source_dirs:
            logger.warning(
                "Native SDK log directory not found for process_path=%s override=%r",
                settings.scanner.process_path,
                settings.sdk_native_log_source or "",
            )
            self._write_sources_metadata(source_dirs)
            return

        self._file_offsets.clear()
        self._stop_event.clear()
        self._write_sources_metadata(source_dirs)
        self._thread = threading.Thread(
            target=self._tail_loop,
            args=(source_dirs,),
            name="SdkNativeLogCollector",
            daemon=True,
        )
        self._running = True
        self._thread.start()
        logger.info(
            "Native SDK log mirror started: sources=%s dest=%s",
            ", ".join(str(path) for path in source_dirs),
            self._mirror_path,
        )

    def stop(self) -> None:
        if not self._running and self._thread is None:
            return

        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

        self._thread = None
        self._file_offsets.clear()
        self._file_mtimes.clear()
        if self._running:
            logger.info("Native SDK log mirror stopped")
        self._running = False

    def _write_sources_metadata(self, source_dirs: list[Path]) -> None:
        if self._sources_path is None:
            return

        payload = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source_dirs": [str(path) for path in source_dirs],
        }
        with self._write_lock:
            self._sources_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _tail_loop(self, source_dirs: list[Path]) -> None:
        while not self._stop_event.is_set():
            for source_dir in source_dirs:
                for log_file in sorted(source_dir.glob("*.log")):
                    try:
                        self._tail_file(log_file)
                    except OSError as exc:
                        logger.warning("Failed tailing native log %s: %s", log_file, exc)
            self._stop_event.wait(POLL_INTERVAL_SEC)

    def _tail_file(self, log_file: Path) -> None:
        if self._mirror_path is None:
            return

        stat = log_file.stat()
        file_size = stat.st_size
        mtime_ns = stat.st_mtime_ns
        offset = self._file_offsets.get(log_file, 0)
        previous_mtime = self._file_mtimes.get(log_file)

        if previous_mtime is not None and mtime_ns != previous_mtime and file_size <= offset:
            offset = 0
        elif file_size < offset:
            offset = 0

        if file_size <= offset:
            self._file_offsets[log_file] = offset
            self._file_mtimes[log_file] = mtime_ns
            return

        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            chunk = handle.read()
            new_offset = handle.tell()

        if not chunk:
            self._file_offsets[log_file] = new_offset
            self._file_mtimes[log_file] = mtime_ns
            return

        prefix = f"[{log_file.name}] "
        lines = chunk.splitlines(keepends=True)
        stamped_lines = []
        for line in lines:
            if line.endswith("\n"):
                stamped_lines.append(f"{prefix}{line}")
            else:
                stamped_lines.append(f"{prefix}{line}\n")

        with self._write_lock:
            self._mirror_path.parent.mkdir(parents=True, exist_ok=True)
            with self._mirror_path.open("a", encoding="utf-8") as mirror:
                mirror.writelines(stamped_lines)

        self._file_offsets[log_file] = new_offset
        self._file_mtimes[log_file] = mtime_ns


sdk_log_collector = SdkLogCollector()
