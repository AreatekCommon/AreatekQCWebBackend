from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.logger import get_logger
from app.core.runtime_settings_store import get_runtime_settings
from app.eki.messages import TrajectoryPoint
from app.eki.path_parser import merge_node_point, parse_path_document
from app.pipeline.cycle import is_end_point
from app.trajectory.path_store import (
    DEFAULT_ACTIVE_FILE,
    DEFAULT_PATHS_FOLDER,
    PathStoreError,
    read_document,
    resolve_path,
    write_document,
)


@dataclass(frozen=True)
class TrajectorySnapshot:
    source_path: str
    point_count: int
    load_error: str | None
    points: list[TrajectoryPoint]
    per_point_exposure: bool = False
    per_point_marker_exposure: bool = False


@dataclass(frozen=True)
class SavedActiveDocument:
    snapshot: TrajectorySnapshot
    normalized_document: dict[str, Any]


from app.trajectory.routing import SCAN_POSITION_TYPES


CALIBRATION_PATH_FILE = "calibration.json"


def validate_calibration_document(document: dict[str, Any]) -> None:
    points = parse_path_document(document)
    if not points:
        raise ValueError("Calibration trajectory is empty")
    if not any(is_end_point(point) for point in points):
        raise ValueError("Calibration trajectory has no end point")

    nodes = document.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("Calibration path document is missing 'nodes' array")

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type", "")).strip().lower()
        if node_type in SCAN_POSITION_TYPES and node_type != "basic_scan":
            raise ValueError(
                f"Calibration path must use basic_scan only, found '{node_type}'"
            )


class TrajectoryService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)
        self._snapshot = TrajectorySnapshot(
            source_path="",
            point_count=0,
            load_error=None,
            points=[],
        )

    def load_at_startup(self) -> None:
        self.reload_active()

    def reload_active(self) -> TrajectorySnapshot:
        settings = get_runtime_settings()
        folder = settings.paths_folder or str(DEFAULT_PATHS_FOLDER)
        filename = settings.active_path_file or DEFAULT_ACTIVE_FILE

        try:
            file_path = resolve_path(folder, filename)
        except PathStoreError as exc:
            snapshot = TrajectorySnapshot(
                source_path=str(Path(folder) / filename),
                point_count=0,
                load_error=str(exc),
                points=[],
            )
            with self._lock:
                self._snapshot = snapshot
            return snapshot

        return self._load_from_file(file_path)

    def _load_from_file(self, file_path: Path) -> TrajectorySnapshot:
        source_path = str(file_path)
        try:
            document = read_document(file_path)
            points = parse_path_document(document)
            snapshot = TrajectorySnapshot(
                source_path=source_path,
                point_count=len(points),
                load_error=None,
                points=points,
                per_point_exposure=bool(document.get("per_point_exposure", False)),
                per_point_marker_exposure=bool(document.get("per_point_marker_exposure", False)),
            )
            with self._lock:
                self._snapshot = snapshot
            self._logger.info("Loaded %d trajectory points from %s", len(points), source_path)
            return snapshot
        except Exception as exc:
            snapshot = TrajectorySnapshot(
                source_path=source_path,
                point_count=0,
                load_error=str(exc),
                points=[],
            )
            with self._lock:
                self._snapshot = snapshot
            self._logger.warning("Failed to load trajectory from %s: %s", source_path, exc)
            return snapshot

    def get_snapshot(self) -> TrajectorySnapshot:
        with self._lock:
            return self._snapshot

    def get_active_file_path(self) -> Path:
        settings = get_runtime_settings()
        folder = settings.paths_folder or str(DEFAULT_PATHS_FOLDER)
        filename = settings.active_path_file or DEFAULT_ACTIVE_FILE
        return resolve_path(folder, filename)

    def get_active_document(self) -> dict[str, Any]:
        return read_document(self.get_active_file_path())

    def save_active_document(self, data: dict[str, Any]) -> SavedActiveDocument:
        file_path = self.get_active_file_path()
        write_document(file_path, data)
        snapshot = self._load_from_file(file_path)
        normalized_document = read_document(file_path)
        return SavedActiveDocument(
            snapshot=snapshot,
            normalized_document=normalized_document,
        )

    def preview_document(self, data: dict[str, Any]) -> int:
        return len(parse_path_document(data))

    def read_named_document(self, filename: str) -> dict[str, Any]:
        settings = get_runtime_settings()
        folder = settings.paths_folder or str(DEFAULT_PATHS_FOLDER)
        file_path = resolve_path(folder, filename)
        return read_document(file_path)

    def load_named_file(self, filename: str) -> TrajectorySnapshot:
        settings = get_runtime_settings()
        folder = settings.paths_folder or str(DEFAULT_PATHS_FOLDER)
        file_path = resolve_path(folder, filename)
        return self._load_from_file(file_path)

    def is_calibration_trajectory_ready(self) -> bool:
        try:
            document = self.read_named_document(CALIBRATION_PATH_FILE)
            validate_calibration_document(document)
            return True
        except Exception:
            return False


trajectory_service = TrajectoryService()


def is_calibration_trajectory_ready() -> bool:
    return trajectory_service.is_calibration_trajectory_ready()
