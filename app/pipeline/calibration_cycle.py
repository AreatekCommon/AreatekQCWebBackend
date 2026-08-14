from __future__ import annotations

import threading
from typing import Optional, Protocol

from app.core.logger import get_logger
from app.eki.messages import TrajectoryPoint
from app.eki.path_client import KukaEkiPathClient
from app.pipeline.cycle import (
    CycleProgress,
    get_end_index,
    get_first_scan_list_index,
    is_home_point,
    move_robot_to_point,
)

logger = get_logger(__name__)

CALIBRATION_PROJECT_LABEL = "calibration"


class CalibrationScannerOperations(Protocol):
    def capture_calibration(
        self,
        capture_index: int,
        point_index: int,
        comment: str,
    ) -> None:
        ...


def run_calibration_cycle(
    robot: KukaEkiPathClient,
    scanner: CalibrationScannerOperations,
    *,
    abort_event: Optional[threading.Event] = None,
    progress: Optional[CycleProgress] = None,
    start_list_index: int = 0,
    initial_capture_count: int = 0,
) -> None:
    points = robot.points
    end_index = get_end_index(points)
    capture_index = initial_capture_count

    if start_list_index < 0 or start_list_index >= len(points):
        raise RuntimeError(f"Start list index out of range: {start_list_index}")

    last_executed_point: TrajectoryPoint | None = (
        points[start_list_index - 1] if start_list_index > 0 else None
    )

    for list_index in range(start_list_index, len(points)):
        point = points[list_index]
        if abort_event is not None and abort_event.is_set():
            raise RuntimeError("Cycle aborted")

        if progress is not None:
            progress.on_step(list_index, capture_index, CALIBRATION_PROJECT_LABEL)

        if is_home_point(point):
            logger.info(
                "Calibration point list=%s idx=%s type=%s comment=%s -> HOME skipped",
                list_index,
                point.index,
                point.point_type,
                point.comment,
            )
            last_executed_point = point
            continue

        if list_index == end_index:
            logger.info(
                "Starting calibration END move list=%s idx=%s comment=%s",
                list_index,
                point.index,
                point.comment,
            )

            if not robot.wait_until_status(robot.STATUS_IDLE, abort_event=abort_event):
                if abort_event is not None and abort_event.is_set():
                    raise RuntimeError("Cycle aborted")
                raise RuntimeError("Robot is not IDLE before END move")

            if not robot.trigger_point_by_list_index(list_index):
                raise RuntimeError("Failed to trigger END point")

            if not robot.wait_motion_done(abort_event=abort_event):
                if abort_event is not None and abort_event.is_set():
                    raise RuntimeError("Cycle aborted")
                raise RuntimeError("Robot did not finish END motion")

            logger.info("Calibration cycle completed successfully")
            return

        position_resent = move_robot_to_point(
            robot,
            list_index,
            point,
            abort_event=abort_event,
            previous_point=last_executed_point,
        )
        last_executed_point = point
        if position_resent and progress is not None:
            progress.on_position_resent(list_index)

        if point.point_type == "scan":
            capture_index += 1
            scanner.capture_calibration(capture_index, point.index, point.comment)

    raise RuntimeError("Calibration cycle ended without END execution")
