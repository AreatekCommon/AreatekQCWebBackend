from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from app.models.cycle_history import (
    MAX_CYCLE_HISTORY_ENTRIES,
    CycleHistoryDocument,
    CycleHistoryEntry,
)

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = Path("data/cycle_history.json")


def load_cycle_history(path: Path = DEFAULT_HISTORY_PATH) -> CycleHistoryDocument:
    if not path.exists():
        return CycleHistoryDocument()

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return CycleHistoryDocument.model_validate(data)
    except Exception as exc:
        logger.warning("Failed to load cycle history from %s: %s", path, exc)
        return CycleHistoryDocument()


def append_cycle_history_entry(
    entry: CycleHistoryEntry,
    path: Path = DEFAULT_HISTORY_PATH,
) -> CycleHistoryDocument:
    document = load_cycle_history(path)
    entries = [*document.entries, entry]
    if len(entries) > MAX_CYCLE_HISTORY_ENTRIES:
        entries = entries[-MAX_CYCLE_HISTORY_ENTRIES:]
    updated = CycleHistoryDocument(entries=entries)
    save_cycle_history(updated, path)
    return updated


def save_cycle_history(
    document: CycleHistoryDocument,
    path: Path = DEFAULT_HISTORY_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")

    try:
        temp_path.write_text(
            json.dumps(document.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def build_cycle_history_entry(
    *,
    started_at: datetime,
    project_name: str,
    mesh_export_finished_at: datetime | None,
    timing_end_at: datetime | None = None,
) -> CycleHistoryEntry:
    duration_end = mesh_export_finished_at or timing_end_at
    duration_sec: float | None = None
    if duration_end is not None:
        duration_sec = max(0.0, (duration_end - started_at).total_seconds())

    return CycleHistoryEntry(
        started_at=started_at,
        mesh_export_finished_at=mesh_export_finished_at,
        duration_sec=duration_sec,
        project_name=project_name,
    )
