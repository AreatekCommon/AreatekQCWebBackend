from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

MAX_CYCLE_HISTORY_ENTRIES = 500


class CycleHistoryEntry(BaseModel):
    started_at: datetime
    mesh_export_finished_at: Optional[datetime] = None
    duration_sec: Optional[float] = None
    project_name: str = Field(default="")


class CycleHistoryDocument(BaseModel):
    entries: list[CycleHistoryEntry] = Field(default_factory=list)


class CycleHistoryResponse(BaseModel):
    entries: list[CycleHistoryEntry]
