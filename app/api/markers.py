from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.fixed_paths import MARKERS_DIR

router = APIRouter(prefix="/markers", tags=["markers"])


class MarkerFileEntry(BaseModel):
    name: str
    path: str


class MarkerListResponse(BaseModel):
    folder: str
    files: list[MarkerFileEntry] = Field(default_factory=list)


@router.get("", response_model=MarkerListResponse)
def list_marker_files() -> MarkerListResponse:
    folder = MARKERS_DIR
    if not folder.is_dir():
        return MarkerListResponse(folder=str(folder.resolve()), files=[])

    entries: list[MarkerFileEntry] = []
    for entry in sorted(folder.rglob("*.p3")):
        if entry.is_file():
            entries.append(
                MarkerFileEntry(
                    name=entry.name if entry.parent == folder else str(entry.relative_to(folder)),
                    path=str(entry.resolve()),
                )
            )

    return MarkerListResponse(folder=str(folder.resolve()), files=entries)
