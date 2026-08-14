from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.eki.path_parser import parse_path_document
from app.trajectory.path_normalize import normalize_path_document

DEFAULT_PATHS_FOLDER = Path("data")
DEFAULT_ACTIVE_FILE = "sample_movement_path.json"


class PathStoreError(ValueError):
    pass


def _has_path_content(data: dict[str, Any]) -> bool:
    if isinstance(data.get("points"), list) and isinstance(data.get("nodes"), list):
        return True
    if isinstance(data.get("positions"), list):
        return True
    return False


def resolve_path(folder: str | Path, filename: str) -> Path:
    if not filename or filename != Path(filename).name:
        raise PathStoreError("Invalid filename")

    if not filename.lower().endswith(".json"):
        raise PathStoreError("Path file must have .json extension")

    base = Path(folder).resolve()
    target = (base / filename).resolve()

    if base not in target.parents and target != base:
        raise PathStoreError("Path escapes configured folder")

    return target


def list_json_files(folder: str | Path) -> list[dict[str, Any]]:
    base = Path(folder)
    if not base.exists() or not base.is_dir():
        return []

    files: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.json"), key=lambda item: item.name.lower()):
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
        source_count: int | None = None
        try:
            document = read_document(path)
            source_count = len(document.get("nodes", []))
        except Exception:
            source_count = None

        files.append(
            {
                "name": path.name,
                "modified_at": modified_at,
                "source_position_count": source_count,
            }
        )

    return files


def read_document(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    raw = file_path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise PathStoreError("Path document must be a JSON object")
    if not _has_path_content(data):
        raise PathStoreError("Path document must contain 'points'/'nodes' or legacy 'positions'")
    return normalize_path_document(data)


def write_document(path: str | Path, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise PathStoreError("Path document must be a JSON object")

    if not _has_path_content(data):
        raise PathStoreError("Path document must contain 'points'/'nodes' or legacy 'positions'")

    normalized = normalize_path_document(data)
    parse_path_document(normalized)

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(f"{file_path.suffix}.tmp")

    try:
        temp_path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(file_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def create_path_file(
    folder: str | Path,
    filename: str,
) -> Path:
    target_path = resolve_path(folder, filename)

    if target_path.exists():
        raise PathStoreError(f"Target path file already exists: {filename}")

    write_document(
        target_path,
        {
            "points": [],
            "nodes": [],
            "safe_route_ids": [],
            "safe_routes": [],
            "per_point_exposure": False,
            "per_point_marker_exposure": False,
        },
    )
    return target_path


def copy_path_file(
    folder: str | Path,
    source_filename: str,
    target_filename: str,
) -> Path:
    source_path = resolve_path(folder, source_filename)
    target_path = resolve_path(folder, target_filename)

    if not source_path.is_file():
        raise PathStoreError(f"Source path file not found: {source_filename}")

    if target_path.exists():
        raise PathStoreError(f"Target path file already exists: {target_filename}")

    shutil.copy2(source_path, target_path)
    return target_path


def delete_path_file(folder: str | Path, filename: str) -> Path:
    target_path = resolve_path(folder, filename)

    if not target_path.is_file():
        raise PathStoreError(f"Path file not found: {filename}")

    target_path.unlink()
    return target_path


def rename_path_file(
    folder: str | Path,
    source_filename: str,
    target_filename: str,
) -> Path:
    source_path = resolve_path(folder, source_filename)
    target_path = resolve_path(folder, target_filename)

    if not source_path.is_file():
        raise PathStoreError(f"Source path file not found: {source_filename}")

    if target_path.exists():
        raise PathStoreError(f"Target path file already exists: {target_filename}")

    source_path.rename(target_path)
    return target_path
