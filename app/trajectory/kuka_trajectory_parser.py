from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.trajectory.path_normalize import normalize_path_document

JOINT_KEYS = ("J1", "J2", "J3", "J4", "J5", "J6")
DEFAULT_TURNTABLE = {"angle": 0.0, "speed": 50.0, "acceleration": 50.0}
DEFAULT_MOTION = {"speed": 50.0, "acceleration": 50.0}


class KukaTrajectoryParseError(ValueError):
    pass


def _default_turntable() -> dict[str, float]:
    return dict(DEFAULT_TURNTABLE)


def _default_motion(entry: dict[str, Any]) -> dict[str, float]:
    motion = entry.get("arm_motion_paras")
    if not isinstance(motion, dict):
        return dict(DEFAULT_MOTION)
    return {
        "speed": float(motion.get("speed", DEFAULT_MOTION["speed"])),
        "acceleration": float(motion.get("acceleration", DEFAULT_MOTION["acceleration"])),
    }


def _joint_axes(entry: dict[str, Any]) -> dict[str, float]:
    joints = entry.get("arm_joint_angles")
    if not isinstance(joints, dict):
        raise KukaTrajectoryParseError("Path entry is missing arm_joint_angles")

    axes: dict[str, float] = {}
    for key in JOINT_KEYS:
        raw = joints.get(key, 0.0)
        try:
            axes[key] = round(float(raw), 2)
        except (TypeError, ValueError) as exc:
            raise KukaTrajectoryParseError(f"Invalid joint value for {key}") from exc
    return axes


def _default_point_name(number: int) -> str:
    return f"Point {number}"


def parse_kuka_trajectory_data(data: dict[str, Any]) -> dict[str, Any]:
    paths = data.get("paths")
    if not isinstance(paths, list) or not paths:
        raise KukaTrajectoryParseError("KUKA file must contain a non-empty 'paths' array")

    points: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    for index, entry in enumerate(paths):
        if not isinstance(entry, dict):
            raise KukaTrajectoryParseError(f"Path entry at index {index} must be an object")

        number = index + 1
        point_id = str(number)
        points.append(
            {
                "id": point_id,
                "name": _default_point_name(number),
                "axes": _joint_axes(entry),
            }
        )

        node_type = "home" if index == 0 else "basic_scan"
        nodes.append(
            {
                "id": point_id,
                "type": node_type,
                "point_id": point_id,
                "turntable": _default_turntable(),
                "motion": _default_motion(entry),
            }
        )

    end_node_id = str(len(paths) + 1)
    nodes.append(
        {
            "id": end_node_id,
            "type": "end",
            "point_id": "1",
            "turntable": _default_turntable(),
            "motion": _default_motion(paths[0] if isinstance(paths[0], dict) else {}),
        }
    )

    document = {
        "points": points,
        "nodes": nodes,
        "per_point_exposure": False,
        "per_point_marker_exposure": False,
    }
    return normalize_path_document(document)


def parse_kuka_trajectory_file(source_path: Path) -> dict[str, Any]:
    if not source_path.is_file():
        raise KukaTrajectoryParseError(f"Source file not found: {source_path}")

    if source_path.suffix.lower() != ".json":
        raise KukaTrajectoryParseError("Source file must have .json extension")

    try:
        raw = source_path.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KukaTrajectoryParseError(f"Invalid JSON in source file: {exc}") from exc
    except OSError as exc:
        raise KukaTrajectoryParseError(f"Cannot read source file: {exc}") from exc

    if not isinstance(data, dict):
        raise KukaTrajectoryParseError("KUKA file root must be a JSON object")

    return parse_kuka_trajectory_data(data)
