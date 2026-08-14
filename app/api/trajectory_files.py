from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.fixed_paths import KUKA_TRAJECTORIES_DIR

router = APIRouter(prefix="/trajectory-files", tags=["trajectory-files"])


class TrajectorySourceFile(BaseModel):
    name: str
    path: str


class TrajectorySourceListResponse(BaseModel):
    folder: str
    files: list[TrajectorySourceFile] = Field(default_factory=list)


@router.get("/source", response_model=TrajectorySourceListResponse)
def list_source_trajectory_files() -> TrajectorySourceListResponse:
    folder = KUKA_TRAJECTORIES_DIR
    if not folder.is_dir():
        return TrajectorySourceListResponse(folder=str(folder.resolve()), files=[])

    files = sorted(
        TrajectorySourceFile(name=entry.name, path=str(entry.resolve()))
        for entry in folder.iterdir()
        if entry.is_file() and entry.suffix.lower() == ".json"
    )
    return TrajectorySourceListResponse(folder=str(folder.resolve()), files=files)
