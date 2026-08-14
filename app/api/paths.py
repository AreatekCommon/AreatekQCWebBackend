from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.runtime_settings_store import get_runtime_settings, update_runtime_settings
from app.models.paths import (
    ActivePathResponse,
    KukaTrajectoryImportRequest,
    KukaTrajectoryImportResponse,
    PathCopyRequest,
    PathCopyResponse,
    PathCreateRequest,
    PathCreateResponse,
    PathDeleteResponse,
    PathDocument,
    PathMoveToRequest,
    PathMoveToResponse,
    PathRenameRequest,
    PathRenameResponse,
    PathSaveRequest,
    PathSelectRequest,
    PathsListResponse,
)
from app.pipeline.service import pipeline_service
from app.trajectory.kuka_import import KukaImportError, KukaImportPipelineBusyError, import_kuka_to_trajectories
from app.trajectory.path_store import (
    PathStoreError,
    copy_path_file,
    create_path_file,
    delete_path_file,
    list_json_files,
    rename_path_file,
    resolve_path,
    write_document,
)
from app.trajectory.path_normalize import normalize_path_document
from app.trajectory.service import SavedActiveDocument, TrajectorySnapshot, trajectory_service

router = APIRouter(prefix="/paths", tags=["paths"])


def _ensure_pipeline_idle() -> None:
    status = pipeline_service.get_status()
    if status.state in {"running", "stopping"}:
        raise HTTPException(
            status_code=409,
            detail="Cannot modify paths while pipeline is running",
        )


def _document_to_dict(document: PathDocument) -> dict[str, Any]:
    return document.model_dump(exclude_none=True)


def _dict_to_document(data: dict[str, Any]) -> PathDocument:
    normalized = normalize_path_document(data)
    return PathDocument.model_validate(normalized)


def _build_active_path_response(
    snapshot: TrajectorySnapshot,
    *,
    normalized_document: dict[str, Any] | None = None,
) -> ActivePathResponse:
    settings = get_runtime_settings()

    try:
        raw_document = (
            normalized_document
            if normalized_document is not None
            else trajectory_service.get_active_document()
        )
        document = _dict_to_document(raw_document)
        source_count = len(document.nodes)
        load_error = snapshot.load_error
    except Exception as exc:
        document = PathDocument()
        source_count = 0
        load_error = str(exc)

    return ActivePathResponse(
        folder=settings.paths_folder,
        filename=settings.active_path_file,
        source_path=snapshot.source_path,
        source_position_count=source_count,
        expanded_point_count=snapshot.point_count,
        load_error=load_error,
        document=document,
    )


@router.get("", response_model=PathsListResponse)
def list_paths() -> PathsListResponse:
    settings = get_runtime_settings()
    files = list_json_files(settings.paths_folder)
    return PathsListResponse(
        folder=settings.paths_folder,
        active_file=settings.active_path_file,
        files=files,
    )


@router.post("/select")
def select_path(payload: PathSelectRequest) -> ActivePathResponse:
    _ensure_pipeline_idle()

    settings = get_runtime_settings()
    try:
        resolve_path(settings.paths_folder, payload.filename)
    except PathStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated = settings.model_copy(update={"active_path_file": payload.filename})
    update_runtime_settings(updated)
    trajectory_service.reload_active()
    pipeline_service.on_path_updated()
    return read_active_path()


@router.get("/active", response_model=ActivePathResponse)
def read_active_path() -> ActivePathResponse:
    try:
        snapshot = trajectory_service.get_snapshot()
        return _build_active_path_response(snapshot)
    except Exception as exc:
        settings = get_runtime_settings()
        return ActivePathResponse(
            folder=settings.paths_folder,
            filename=settings.active_path_file,
            source_path="",
            source_position_count=0,
            expanded_point_count=0,
            load_error=str(exc),
            document=PathDocument(),
        )


@router.put("/active", response_model=ActivePathResponse)
def save_active_path(payload: PathSaveRequest) -> ActivePathResponse:
    _ensure_pipeline_idle()

    saved: SavedActiveDocument | None = None
    try:
        data = _document_to_dict(payload.document)
        saved = trajectory_service.save_active_document(data)
        pipeline_service.on_path_updated()
    except PathStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if saved is not None:
        try:
            return _build_active_path_response(
                saved.snapshot,
                normalized_document=saved.normalized_document,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return read_active_path()


@router.post("/copy", response_model=PathCopyResponse)
def copy_path(payload: PathCopyRequest) -> PathCopyResponse:
    _ensure_pipeline_idle()

    settings = get_runtime_settings()
    try:
        copy_path_file(
            settings.paths_folder,
            payload.source_filename,
            payload.target_filename,
        )
    except PathStoreError as exc:
        message = str(exc)
        if "already exists" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    return PathCopyResponse(filename=payload.target_filename)


@router.post("/create", response_model=PathCreateResponse)
def create_path(payload: PathCreateRequest) -> PathCreateResponse:
    _ensure_pipeline_idle()

    settings = get_runtime_settings()
    try:
        create_path_file(settings.paths_folder, payload.filename)
    except PathStoreError as exc:
        message = str(exc)
        if "already exists" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    return PathCreateResponse(filename=payload.filename)


@router.delete("/{filename}", response_model=PathDeleteResponse)
def delete_path(filename: str) -> PathDeleteResponse:
    _ensure_pipeline_idle()

    settings = get_runtime_settings()
    try:
        delete_path_file(settings.paths_folder, filename)
    except PathStoreError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    active_file = settings.active_path_file
    if active_file == filename:
        remaining = sorted(
            (entry["name"] for entry in list_json_files(settings.paths_folder)),
            key=str.lower,
        )
        if remaining:
            active_file = remaining[0]
        else:
            active_file = "new_path.json"
            create_path_file(settings.paths_folder, active_file)

        updated = settings.model_copy(update={"active_path_file": active_file})
        update_runtime_settings(updated)
        trajectory_service.reload_active()
        pipeline_service.on_path_updated()

    return PathDeleteResponse(filename=filename, active_file=active_file)


@router.post("/rename", response_model=PathRenameResponse)
def rename_path(payload: PathRenameRequest) -> PathRenameResponse:
    _ensure_pipeline_idle()

    settings = get_runtime_settings()
    try:
        rename_path_file(
            settings.paths_folder,
            payload.source_filename,
            payload.target_filename,
        )
    except PathStoreError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        if "already exists" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc

    active_file = settings.active_path_file
    if active_file == payload.source_filename:
        active_file = payload.target_filename
        updated = settings.model_copy(update={"active_path_file": active_file})
        update_runtime_settings(updated)
        trajectory_service.reload_active()
        pipeline_service.on_path_updated()

    return PathRenameResponse(filename=payload.target_filename, active_file=active_file)


@router.post("/import-kuka", response_model=KukaTrajectoryImportResponse)
def import_kuka_trajectory(payload: KukaTrajectoryImportRequest) -> KukaTrajectoryImportResponse:
    source_path = Path(payload.source_path.strip())
    try:
        return import_kuka_to_trajectories(
            source_path,
            payload.output_filename,
            set_active=False,
            overwrite=False,
        )
    except KukaImportPipelineBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KukaImportError as exc:
        message = str(exc)
        if "already exists" in message:
            raise HTTPException(status_code=409, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.post("/active/move-to", response_model=PathMoveToResponse)
def move_to_path_position(payload: PathMoveToRequest) -> PathMoveToResponse:
    _ensure_pipeline_idle()

    document = (
        _document_to_dict(payload.document)
        if payload.document is not None
        else None
    )

    try:
        result = pipeline_service.move_to_path_position(
            payload.position_index,
            document,
            node_id=payload.node_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return PathMoveToResponse(
        route=result.get("route", []),
        hops_executed=int(result.get("hops_executed", 0)),
        travel_steps=result.get("travel_steps", []),
    )
