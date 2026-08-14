from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.logger import get_logger
from app.core.runtime_settings_store import get_runtime_settings, update_runtime_settings
from app.models.paths import PathDocument
from app.models.runtime_settings import RuntimeSettings
from app.pipeline.service import pipeline_service
from app.trajectory.path_normalize import normalize_path_document
from app.trajectory.path_store import PathStoreError
from app.trajectory.service import trajectory_service

router = APIRouter(prefix="/projects", tags=["projects"])
_logger = get_logger(__name__)

PROJECTS_ROOT = Path("data/projects")
ACTIVE_PROJECT_PATH = PROJECTS_ROOT / ".active.json"
_FORBIDDEN_NAME_CHARS_RE = re.compile(r'[<>:"|?*]')
_SAFE_NAME_RE = re.compile(r"^[\w][\w .\-]{0,120}$", re.UNICODE)


class ProjectSaveRequest(BaseModel):
    name: str
    overwrite: bool = False
    settings: RuntimeSettings


class ProjectSaveResponse(BaseModel):
    name: str
    path: str


class ProjectListResponse(BaseModel):
    projects: list[str] = Field(default_factory=list)


class ProjectExistsResponse(BaseModel):
    name: str
    exists: bool


class ActiveProjectResponse(BaseModel):
    name: str | None = None


class ActiveProjectRequest(BaseModel):
    name: str | None = None


class ProjectLoadResponse(BaseModel):
    name: str
    settings: RuntimeSettings
    path_document: PathDocument


def _sanitize_project_name(raw: str) -> str:
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid project name")
    if _FORBIDDEN_NAME_CHARS_RE.search(name):
        raise HTTPException(status_code=400, detail="Invalid project name")
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail="Project name may only contain letters, digits, spaces, and _.-",
        )
    return name


def _project_dir(name: str) -> Path:
    return PROJECTS_ROOT / name


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid project snapshot") from exc


def _try_read_legacy_path(project_dir: Path) -> dict[str, Any] | None:
    legacy_path = project_dir / "path.json"
    if not legacy_path.is_file():
        return None
    try:
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _get_active_project_name() -> str | None:
    if not ACTIVE_PROJECT_PATH.is_file():
        return None
    try:
        data = json.loads(ACTIVE_PROJECT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    raw_name = data.get("name")
    if raw_name is None:
        return None
    if not isinstance(raw_name, str):
        return None
    stripped = raw_name.strip()
    return stripped or None


def _set_active_project_name(name: str | None) -> None:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json(ACTIVE_PROJECT_PATH, {"name": name})


def _ensure_pipeline_idle(action: str) -> None:
    status = pipeline_service.get_status()
    if status.state in {"running", "stopping"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} project while pipeline is running",
        )


@router.get("", response_model=ProjectListResponse)
def list_projects() -> ProjectListResponse:
    if not PROJECTS_ROOT.exists():
        return ProjectListResponse(projects=[])
    names = sorted(
        entry.name
        for entry in PROJECTS_ROOT.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )
    return ProjectListResponse(projects=names)


@router.get("/active", response_model=ActiveProjectResponse)
def read_active_project() -> ActiveProjectResponse:
    return ActiveProjectResponse(name=_get_active_project_name())


@router.post("/active", response_model=ActiveProjectResponse)
def write_active_project(payload: ActiveProjectRequest) -> ActiveProjectResponse:
    if payload.name is None:
        _set_active_project_name(None)
        return ActiveProjectResponse(name=None)

    safe_name = _sanitize_project_name(payload.name)
    if not _project_dir(safe_name).is_dir():
        raise HTTPException(status_code=404, detail="Project not found")
    _set_active_project_name(safe_name)
    return ActiveProjectResponse(name=safe_name)


@router.post("/save", response_model=ProjectSaveResponse)
def save_project(payload: ProjectSaveRequest) -> ProjectSaveResponse:
    safe_name = _sanitize_project_name(payload.name)
    target = _project_dir(safe_name)

    if target.exists() and not payload.overwrite:
        raise HTTPException(status_code=409, detail="Project already exists")

    _ensure_pipeline_idle("save")

    previous = get_runtime_settings()
    settings_to_save = payload.settings.model_copy(
        update={"active_path_file": previous.active_path_file},
    )
    saved_settings = update_runtime_settings(settings_to_save)
    apply_result = pipeline_service.apply_settings_section(
        saved_settings,
        previous,
        None,
    )

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    _write_json(target / "settings.json", saved_settings.model_dump())
    _write_json(
        target / "meta.json",
        {
            "name": safe_name,
            "active_path_file": saved_settings.active_path_file,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "apply_error": apply_result.apply_error,
        },
    )
    _set_active_project_name(safe_name)

    return ProjectSaveResponse(name=safe_name, path=str(target.resolve()))


@router.post("/{name}/load", response_model=ProjectLoadResponse)
def load_project(name: str) -> ProjectLoadResponse:
    safe_name = _sanitize_project_name(name)
    target = _project_dir(safe_name)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")

    _ensure_pipeline_idle("load")

    settings_data = _read_json(target / "settings.json")

    try:
        loaded_settings = RuntimeSettings.model_validate(settings_data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid project settings") from exc

    previous = get_runtime_settings()
    saved_settings = update_runtime_settings(loaded_settings)
    pipeline_service.apply_settings_section(saved_settings, previous, None)

    snapshot = trajectory_service.reload_active()
    if snapshot.load_error:
        legacy_path_data = _try_read_legacy_path(target)
        if legacy_path_data is not None:
            _logger.info(
                "Migrating legacy project path.json into active trajectory file for %s",
                safe_name,
            )
            try:
                normalized_path = normalize_path_document(legacy_path_data)
                trajectory_service.save_active_document(normalized_path)
                snapshot = trajectory_service.reload_active()
            except PathStoreError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    if snapshot.load_error:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to load project trajectory: {snapshot.load_error}",
        )

    pipeline_service.on_path_updated()

    try:
        path_document = PathDocument.model_validate(trajectory_service.get_active_document())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid active trajectory document") from exc

    _set_active_project_name(safe_name)

    return ProjectLoadResponse(
        name=safe_name,
        settings=saved_settings,
        path_document=path_document,
    )


@router.get("/{name}", response_model=ProjectExistsResponse)
def project_exists(name: str) -> ProjectExistsResponse:
    safe_name = _sanitize_project_name(name)
    return ProjectExistsResponse(name=safe_name, exists=_project_dir(safe_name).is_dir())
