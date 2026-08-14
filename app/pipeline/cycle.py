from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol

from app.core.logger import get_logger
from app.eki.messages import TrajectoryPoint
from app.eki.path_client import KukaEkiPathClient
from app.pipeline.config import (
    HEARTBEAT_PERIOD,
    POSITION_RESEND_MAX_ATTEMPTS,
    RECV_TIMEOUT,
    SETTLE_SEC,
    STARTUP_CONNECT_MAX_ATTEMPTS,
    STARTUP_STATUS_TIMEOUT_SEC,
)
from app.trajectory.routing import DEFAULT_MATCH_THRESHOLD_DEG, axes_match
from q12_client import SdkCommandError

logger = get_logger(__name__)


@dataclass(frozen=True)
class PendingGapTimer:
    kind: Literal["transition", "scan"]
    started_at: float
    from_list_index: int


_pending_gap_timer: PendingGapTimer | None = None


def _clear_pending_gap_timer() -> None:
    global _pending_gap_timer
    _pending_gap_timer = None


def _set_transition_gap_timer(from_list_index: int) -> None:
    global _pending_gap_timer
    _pending_gap_timer = PendingGapTimer(
        kind="transition",
        started_at=time.monotonic(),
        from_list_index=from_list_index,
    )


def _set_scan_gap_timer(from_list_index: int) -> None:
    global _pending_gap_timer
    _pending_gap_timer = PendingGapTimer(
        kind="scan",
        started_at=time.monotonic(),
        from_list_index=from_list_index,
    )


def _log_pending_gap_before_move(to_list_index: int) -> None:
    global _pending_gap_timer
    pending = _pending_gap_timer
    if pending is None:
        return

    elapsed_sec = max(0.0, time.monotonic() - pending.started_at)
    if pending.kind == "transition":
        logger.info(
            "Transition idle before next move: %.2fs (list %s → %s)",
            elapsed_sec,
            pending.from_list_index,
            to_list_index,
        )
    else:
        logger.info(
            "Post-scan idle before next move: %.2fs (list %s → %s)",
            elapsed_sec,
            pending.from_list_index,
            to_list_index,
        )
    _pending_gap_timer = None


class ScannerOperations(Protocol):
    def create_project(self, project_name: str) -> None:
        ...

    def run_scan(
        self,
        scan_index: int,
        point_index: int,
        point_type: str,
        comment: str,
        *,
        point: TrajectoryPoint | None = None,
        per_point_exposure: bool = False,
        per_point_marker_exposure: bool = False,
    ) -> None:
        ...

    def generate_mesh_and_save(self, project_name: str) -> None:
        ...


class CycleProgress(Protocol):
    def on_step(self, list_index: int, scan_count: int, project_name: str) -> None:
        ...

    def on_position_resent(self, list_index: int) -> None:
        ...


@dataclass(frozen=True)
class CycleRunResult:
    project_name: str
    mesh_export_finished_at: datetime | None = None
    last_position_reached_at: datetime | None = None


def _cycle_run_result(
    project_name: str,
    mesh_timing: dict[str, Any],
    *,
    last_position_reached_at: datetime | None = None,
) -> CycleRunResult:
    finished_at = mesh_timing.get("finished_at")
    mesh_export_finished_at = finished_at if isinstance(finished_at, datetime) else None
    return CycleRunResult(
        project_name=project_name,
        mesh_export_finished_at=mesh_export_finished_at,
        last_position_reached_at=last_position_reached_at,
    )


def is_home_point(point: TrajectoryPoint) -> bool:
    point_type = point.point_type.strip().lower()
    comment = point.comment.strip().lower()
    return point_type == "home" or comment == "home" or comment.startswith("home")


def get_first_scan_list_index(points: list[TrajectoryPoint]) -> int:
    for list_index, point in enumerate(points):
        if point.point_type.strip().lower() == "scan":
            return list_index
    raise RuntimeError("Trajectory has no scan point")


def get_last_scan_list_index(points: list[TrajectoryPoint]) -> int:
    last_scan_index = -1
    for list_index, point in enumerate(points):
        if point.point_type.strip().lower() == "scan":
            last_scan_index = list_index
    if last_scan_index < 0:
        raise RuntimeError("Trajectory has no scan point")
    return last_scan_index


def same_robot_pose(
    left: TrajectoryPoint,
    right: TrajectoryPoint,
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD_DEG,
) -> bool:
    if not axes_match(left.axes, right.axes, threshold=threshold):
        return False
    return abs(left.a7 - right.a7) <= threshold


def is_end_point(point: TrajectoryPoint) -> bool:
    point_type = point.point_type.strip().lower()
    comment = point.comment.strip().lower()
    return point_type == "end" or comment == "end" or comment.startswith("end")


def get_end_index(points: list[TrajectoryPoint]) -> int:
    end_indexes = [index for index, point in enumerate(points) if is_end_point(point)]
    if not end_indexes:
        raise RuntimeError("End point not found in trajectory")
    return end_indexes[-1]


def generate_project_name() -> str:
    from app.core.runtime_settings_store import get_runtime_settings
    from app.scanner.project_name import assemble_project_name

    return assemble_project_name(get_runtime_settings().scanner)


def prepare_next_project(scanner: ScannerOperations) -> str:
    from app.core.runtime_settings_store import get_runtime_settings, update_runtime_settings
    from app.scanner.project_name import advance_project_name_counter, assemble_project_name

    settings = get_runtime_settings()
    project_name = assemble_project_name(settings.scanner)
    scanner.create_project(project_name)
    updated_scanner = advance_project_name_counter(settings.scanner)
    if updated_scanner.project_name_counter != settings.scanner.project_name_counter:
        update_runtime_settings(
            settings.model_copy(update={"scanner": updated_scanner})
        )
    return project_name


def connect_robot(
    points: list[TrajectoryPoint],
    robot_ip: str,
    robot_port: int,
    turntable_port: int,
    *,
    max_attempts: int | None = None,
    status_timeout_sec: float | None = None,
) -> KukaEkiPathClient:
    if not points:
        raise RuntimeError("Trajectory is empty")

    robot = KukaEkiPathClient(
        robot_ip=robot_ip,
        robot_port=robot_port,
        turntable_port=turntable_port,
        heartbeat_period=HEARTBEAT_PERIOD,
        recv_timeout=RECV_TIMEOUT,
    )
    robot.points = list(points)
    robot.current_point_idx = 0
    first_point = robot.points[0]
    robot.current_target = first_point.axes + [first_point.a7]

    logger.info("Connecting to robot...")
    robot.start(max_attempts=max_attempts)

    idle_timeout = status_timeout_sec if status_timeout_sec is not None else None
    if not robot.wait_until_status(robot.STATUS_IDLE, timeout_sec=idle_timeout):
        raise RuntimeError("Robot did not become IDLE after connect")

    logger.info("Robot ready")
    return robot


def create_robot_client(
    points: list[TrajectoryPoint],
    robot_ip: str,
    robot_port: int,
    turntable_port: int,
) -> KukaEkiPathClient:
    if not points:
        raise RuntimeError("Trajectory is empty")

    robot = KukaEkiPathClient(
        robot_ip=robot_ip,
        robot_port=robot_port,
        turntable_port=turntable_port,
        heartbeat_period=HEARTBEAT_PERIOD,
        recv_timeout=RECV_TIMEOUT,
    )
    robot.points = list(points)
    robot.current_point_idx = 0
    first_point = robot.points[0]
    robot.current_target = first_point.axes + [first_point.a7]
    return robot


def try_connect_robot_path(
    robot: KukaEkiPathClient,
    *,
    max_attempts: int = STARTUP_CONNECT_MAX_ATTEMPTS,
    status_timeout_sec: float = STARTUP_STATUS_TIMEOUT_SEC,
) -> None:
    robot.connect_path_service(max_attempts=max_attempts)
    if not robot.wait_until_status(robot.STATUS_IDLE, timeout_sec=status_timeout_sec):
        raise RuntimeError("Robot path connected but did not become IDLE")


def try_connect_turntable(
    robot: KukaEkiPathClient,
    *,
    max_attempts: int = STARTUP_CONNECT_MAX_ATTEMPTS,
) -> None:
    robot.connect_turntable_service(max_attempts=max_attempts)


def _sleep_interruptible(sec: float, abort_event: Optional[threading.Event] = None) -> None:
    deadline = time.monotonic() + sec
    while True:
        if abort_event is not None and abort_event.is_set():
            raise RuntimeError("Cycle aborted")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))


def _raise_if_aborted(abort_event: Optional[threading.Event]) -> None:
    if abort_event is not None and abort_event.is_set():
        raise RuntimeError("Cycle aborted")


def _ensure_idle_before_trigger(
    robot: KukaEkiPathClient,
    *,
    abort_event: Optional[threading.Event] = None,
) -> None:
    if robot.is_idle():
        return
    if not robot.wait_until_status(robot.STATUS_IDLE, abort_event=abort_event):
        _raise_if_aborted(abort_event)
        raise RuntimeError("Robot is not IDLE before move command")


def _trigger_and_wait_motion(
    robot: KukaEkiPathClient,
    list_index: int,
    *,
    abort_event: Optional[threading.Event] = None,
) -> float:
    _ensure_idle_before_trigger(robot, abort_event=abort_event)

    if not robot.trigger_point_by_list_index(list_index):
        raise RuntimeError(f"Failed to trigger point {list_index}")

    motion_ok, elapsed_sec = robot.wait_motion_done_timed(abort_event=abort_event)
    if not motion_ok:
        _raise_if_aborted(abort_event)
        raise RuntimeError(f"Robot motion failed at point {list_index}")
    return elapsed_sec


def _start_mesh_worker(
    scanner: ScannerOperations,
    project_name: str,
    worker_error: dict[str, Exception],
    mesh_timing: dict[str, Any],
) -> threading.Thread:
    def mesh_worker() -> None:
        try:
            scanner.generate_mesh_and_save(project_name)
            mesh_timing["finished_at"] = datetime.now(UTC)
        except Exception as exc:
            worker_error["error"] = exc

    worker = threading.Thread(target=mesh_worker, daemon=False, name="PipelineMeshWorker")
    worker.start()
    return worker


def _finalize_mesh_worker(
    worker: threading.Thread | None,
    worker_error: dict[str, Exception],
    *,
    abort_event: Optional[threading.Event] = None,
) -> None:
    if worker is None:
        return

    while worker.is_alive():
        if abort_event is not None and abort_event.is_set():
            raise RuntimeError("Cycle aborted")
        worker.join(timeout=0.5)

    if "error" in worker_error:
        raise worker_error["error"]


def move_robot_to_point(
    robot: KukaEkiPathClient,
    list_index: int,
    point: TrajectoryPoint,
    *,
    abort_event: Optional[threading.Event] = None,
    previous_point: TrajectoryPoint | None = None,
) -> bool:
    if abort_event is not None and abort_event.is_set():
        raise RuntimeError("Cycle aborted")

    _log_pending_gap_before_move(list_index)

    logger.info(
        "Move to point list=%s idx=%s type=%s comment=%s",
        list_index,
        point.index,
        point.point_type,
        point.comment,
    )

    from app.core.runtime_settings_store import get_runtime_settings

    position_resent = False
    pipeline_settings = get_runtime_settings().pipeline
    delay_sec = pipeline_settings.error_turntable_delay_sec
    skip_delay_check = previous_point is not None and same_robot_pose(previous_point, point)

    if skip_delay_check:
        logger.info(
            "Point list=%s idx=%s has same pose as previous step; skipping delay retry",
            list_index,
            point.index,
        )
        _trigger_and_wait_motion(robot, list_index, abort_event=abort_event)
    else:
        for attempt in range(1, POSITION_RESEND_MAX_ATTEMPTS + 1):
            if abort_event is not None and abort_event.is_set():
                raise RuntimeError("Cycle aborted")

            elapsed_sec = _trigger_and_wait_motion(robot, list_index, abort_event=abort_event)

            if elapsed_sec > delay_sec:
                if position_resent:
                    logger.info(
                        "Point list=%s accepted after resend (attempt %d, %.3fs)",
                        list_index,
                        attempt,
                        elapsed_sec,
                    )
                break

            position_resent = True
            if attempt < POSITION_RESEND_MAX_ATTEMPTS:
                settle_wait_sec = max(0.0, delay_sec - elapsed_sec)
                logger.warning(
                    "Fast in-position at list=%s (%.3fs <= %.3fs); "
                    "waiting %.3fs before resend attempt %d/%d",
                    list_index,
                    elapsed_sec,
                    delay_sec,
                    settle_wait_sec,
                    attempt,
                    POSITION_RESEND_MAX_ATTEMPTS,
                )
                _sleep_interruptible(settle_wait_sec, abort_event)
            else:
                logger.warning(
                    "Fast in-position at list=%s after %d attempts (%.3fs); proceeding anyway",
                    list_index,
                    POSITION_RESEND_MAX_ATTEMPTS,
                    elapsed_sec,
                )

    logger.info("Reached point idx=%s", point.index)
    return position_resent


def _run_scan_until_aligned(
    scanner: ScannerOperations,
    scan_index: int,
    point: TrajectoryPoint,
    *,
    per_point_exposure: bool = False,
    per_point_marker_exposure: bool = False,
    abort_event: Optional[threading.Event] = None,
    retry_delay_sec: float = SETTLE_SEC,
    skip_failed_scans: bool = False,
) -> None:
    attempt = 0
    while True:
        _raise_if_aborted(abort_event)
        try:
            scanner.run_scan(
                scan_index,
                point.index,
                point.point_type,
                point.comment,
                point=point,
                per_point_exposure=per_point_exposure,
                per_point_marker_exposure=per_point_marker_exposure,
            )
            if attempt > 0:
                logger.info(
                    "Scan #%d succeeded at idx=%s after %d alignment retries",
                    scan_index,
                    point.index,
                    attempt,
                )
            return
        except SdkCommandError as exc:
            if not exc.is_alignment_retryable:
                raise
            if skip_failed_scans:
                logger.warning(
                    "Scan #%d skipped at idx=%s comment=%s (retCode=%s): alignment failure",
                    scan_index,
                    point.index,
                    point.comment,
                    exc.ret_code,
                )
                return
            attempt += 1
            logger.warning(
                "Scan alignment failed at idx=%s comment=%s (attempt %d, retCode=%s); "
                "retrying at same position",
                point.index,
                point.comment,
                attempt,
                exc.ret_code,
            )
            _sleep_interruptible(retry_delay_sec, abort_event)


def run_cycle(
    robot: KukaEkiPathClient,
    scanner: ScannerOperations,
    project_name: str,
    *,
    abort_event: Optional[threading.Event] = None,
    progress: Optional[CycleProgress] = None,
    start_list_index: int = 0,
    initial_scan_count: int = 0,
    per_point_exposure: bool = False,
    per_point_marker_exposure: bool = False,
    stop_after_last_scan: bool = False,
) -> CycleRunResult:
    points = robot.points
    end_index = get_end_index(points)
    last_scan_index = get_last_scan_list_index(points)
    scan_index = initial_scan_count
    mesh_worker: threading.Thread | None = None
    mesh_worker_error: dict[str, Exception] = {}
    mesh_timing: dict[str, Any] = {}
    last_executed_point: TrajectoryPoint | None = (
        points[start_list_index - 1] if start_list_index > 0 else None
    )

    if start_list_index < 0 or start_list_index >= len(points):
        raise RuntimeError(f"Start list index out of range: {start_list_index}")

    if start_list_index > last_scan_index:
        if stop_after_last_scan:
            logger.info("Resuming past last scan; stopping without export or END")
            return _cycle_run_result(project_name, mesh_timing)
        logger.info("Resuming past last scan; starting mesh export early")
        mesh_worker = _start_mesh_worker(
            scanner, project_name, mesh_worker_error, mesh_timing
        )

    from app.core.runtime_settings_store import get_runtime_settings

    skip_failed_scans = get_runtime_settings().pipeline.skip_failed_scans
    _clear_pending_gap_timer()

    for list_index in range(start_list_index, len(points)):
        point = points[list_index]
        if abort_event is not None and abort_event.is_set():
            raise RuntimeError("Cycle aborted")

        if progress is not None:
            progress.on_step(list_index, scan_index, project_name)

        if is_home_point(point):
            logger.info(
                "Point list=%s idx=%s type=%s comment=%s -> HOME skipped",
                list_index,
                point.index,
                point.point_type,
                point.comment,
            )
            last_executed_point = point
            continue

        if list_index == end_index:
            logger.info(
                "Starting END move list=%s idx=%s type=%s comment=%s",
                list_index,
                point.index,
                point.point_type,
                point.comment,
            )

            _log_pending_gap_before_move(list_index)

            if not robot.wait_until_status(robot.STATUS_IDLE, abort_event=abort_event):
                _raise_if_aborted(abort_event)
                raise RuntimeError("Robot is not IDLE before END move")

            if not robot.trigger_point_by_list_index(list_index):
                raise RuntimeError("Failed to trigger END point")

            if mesh_worker is None:
                logger.warning("Mesh export not started after last scan; starting at END")
                mesh_worker = _start_mesh_worker(
                    scanner, project_name, mesh_worker_error, mesh_timing
                )

            if not robot.wait_motion_done(abort_event=abort_event):
                _raise_if_aborted(abort_event)
                raise RuntimeError("Robot did not finish END motion")

            _finalize_mesh_worker(mesh_worker, mesh_worker_error, abort_event=abort_event)

            logger.info("Cycle completed successfully on END point: %s", project_name)
            return _cycle_run_result(project_name, mesh_timing)

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

        last_position_reached_at: datetime | None = None
        if stop_after_last_scan and list_index == last_scan_index:
            last_position_reached_at = datetime.now(UTC)

        if point.point_type == "scan":
            scan_index += 1
            _run_scan_until_aligned(
                scanner,
                scan_index,
                point,
                per_point_exposure=per_point_exposure,
                per_point_marker_exposure=per_point_marker_exposure,
                abort_event=abort_event,
                skip_failed_scans=skip_failed_scans,
            )
            _set_scan_gap_timer(list_index)
            if stop_after_last_scan and list_index == last_scan_index:
                logger.info(
                    "Last scan completed; stopping cycle without export or END (%s)",
                    project_name,
                )
                return _cycle_run_result(
                    project_name,
                    mesh_timing,
                    last_position_reached_at=last_position_reached_at,
                )
            if list_index == last_scan_index and mesh_worker is None:
                logger.info("Last scan completed; starting mesh export")
                mesh_worker = _start_mesh_worker(
                    scanner, project_name, mesh_worker_error, mesh_timing
                )
        else:
            logger.info("Point idx=%s type=%s, scan skipped", point.index, point.point_type)
            _set_transition_gap_timer(list_index)

    raise RuntimeError("Cycle ended without END execution")
