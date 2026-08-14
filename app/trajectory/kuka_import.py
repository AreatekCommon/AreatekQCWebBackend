from __future__ import annotations

from pathlib import Path

from app.core.fixed_paths import KUKA_TRAJECTORIES_DIR, PARSED_TRAJECTORIES_DIR, is_under_directory
from app.core.runtime_settings_store import get_runtime_settings, update_runtime_settings
from app.models.paths import KukaTrajectoryImportResponse
from app.pipeline.service import pipeline_service
from app.trajectory.kuka_trajectory_parser import KukaTrajectoryParseError, parse_kuka_trajectory_file
from app.trajectory.path_store import PathStoreError, resolve_path, write_document
from app.trajectory.path_normalize import normalize_path_document
from app.trajectory.service import trajectory_service


class KukaImportError(Exception):
    pass


class KukaImportPipelineBusyError(KukaImportError):
    pass


def _ensure_pipeline_idle() -> None:
    status = pipeline_service.get_status()
    if status.state in {"running", "stopping"}:
        raise KukaImportPipelineBusyError("Cannot import trajectory while pipeline is running")


def import_kuka_to_trajectories(
    source_path: Path,
    output_filename: str,
    *,
    set_active: bool = False,
    overwrite: bool = False,
) -> KukaTrajectoryImportResponse:
    _ensure_pipeline_idle()

    if not source_path.is_file():
        raise KukaImportError("Source trajectory file not found")
    if not is_under_directory(source_path, KUKA_TRAJECTORIES_DIR):
        raise KukaImportError(f"Source file must be under {KUKA_TRAJECTORIES_DIR}")

    try:
        parsed = parse_kuka_trajectory_file(source_path)
    except KukaTrajectoryParseError as exc:
        raise KukaImportError(str(exc)) from exc

    output_folder = str(PARSED_TRAJECTORIES_DIR)
    try:
        target_path = resolve_path(output_folder, output_filename)
    except PathStoreError as exc:
        raise KukaImportError(str(exc)) from exc

    if target_path.exists() and not overwrite:
        raise KukaImportError(f"Target path file already exists: {output_filename}")

    try:
        write_document(target_path, parsed)
    except PathStoreError as exc:
        raise KukaImportError(str(exc)) from exc
    except Exception as exc:
        raise KukaImportError(str(exc)) from exc

    if set_active:
        settings = get_runtime_settings()
        updated = settings.model_copy(update={"active_path_file": target_path.name})
        update_runtime_settings(updated)
        trajectory_service.reload_active()
        pipeline_service.on_path_updated()

    source_point_count = len(parsed.get("nodes", [])) - 1
    return KukaTrajectoryImportResponse(
        output_path=str(target_path),
        source_point_count=max(source_point_count, 0),
        node_count=len(parsed.get("nodes", [])),
        point_count=len(parsed.get("points", [])),
        filename=target_path.name,
    )
