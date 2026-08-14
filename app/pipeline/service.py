from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Optional

from app.axis.service import axis_receiver_service
from app.core.cycle_history_repository import (
    append_cycle_history_entry,
    build_cycle_history_entry,
    load_cycle_history,
)
from app.core.app_state import app_state
from app.core.logger import apply_runtime_logging_settings, get_logger
from app.core.runtime_settings_store import get_runtime_settings
from app.eki.path_client import KukaEkiPathClient
from app.models.cycle_history import CycleHistoryEntry
from app.models.runtime_settings import RuntimeSettings
from app.models.settings_update import SettingsApplyResult
from app.pipeline.config import (
    HEARTBEAT_PERIOD,
    INIT_RETRY_INTERVAL_SEC,
    RECV_TIMEOUT,
    RESTART_DELAY_SEC,
    SETTLE_SEC,
    STARTUP_CONNECT_MAX_ATTEMPTS,
    STARTUP_STATUS_TIMEOUT_SEC,
)
from app.pipeline.calibration_cycle import run_calibration_cycle
from app.pipeline.cycle import (
    CycleRunResult,
    create_robot_client,
    get_first_scan_list_index,
    is_end_point,
    prepare_next_project,
    run_cycle,
    try_connect_robot_path,
    try_connect_turntable,
)
from app.models.scanner_settings import ScannerSettings
from app.scanner.sdk_logging import apply_sdk_logging
from app.scanner.service import scanner_service
from app.settings_sections import (
    SAVE_ONLY_SCANNER_SECTIONS,
    SCANNER_SETTINGS_SECTIONS,
    SETTINGS_SECTION_AXIS_TELEMETRY,
    SETTINGS_SECTION_LOGGING,
    SETTINGS_SECTION_PATHS,
    SETTINGS_SECTION_PIPELINE,
    SETTINGS_SECTION_ROBOT_PATH,
    SETTINGS_SECTION_SCANNER_CONNECTION,
    SETTINGS_SECTION_SDK_PATHS,
)
from app.trajectory.routing import (
    axes_match,
    build_travel_plan_by_id,
    find_first_scan_node,
    find_first_scan_position_id,
    find_home_position_id,
    plan_id_route_to_goal,
    read_current_axes_from_snapshot,
)
from app.trajectory.path_normalize import normalize_path_document
from app.trajectory.service import (
    CALIBRATION_PATH_FILE,
    trajectory_service,
    validate_calibration_document,
)
from auto_import import ScanFolderWatcher, ScanFolderWatcherSettings
from q12_client import SdkCommandError

PipelineState = Literal["idle", "running", "stopping", "error"]
CycleMode = Literal["production", "calibration"]
CycleTimingMode = Literal["last_scan", "full_cycle"]

SCAN_WATCHER_DEFAULTS = ScanFolderWatcherSettings(
    scans_root=ScannerSettings().export_root,
    successful_imports_dir_name="Successful_imports",
    failed_imports_dir_name="Failed_imports",
    reports_dir_name="reports",
    poll_interval_s=1.0,
    stable_age_s=2.0,
    directory_copy_retry_s=0.5,
    open_pdf_after_move=True,
)


def build_scan_watcher_settings(settings: RuntimeSettings) -> ScanFolderWatcherSettings:
    return ScanFolderWatcherSettings(
        scans_root=settings.scanner.export_root,
        monitored_folder=settings.pipeline.scan_import_monitored_folder.strip(),
        successful_imports_dir_name=SCAN_WATCHER_DEFAULTS.successful_imports_dir_name,
        failed_imports_dir_name=SCAN_WATCHER_DEFAULTS.failed_imports_dir_name,
        reports_dir_name=SCAN_WATCHER_DEFAULTS.reports_dir_name,
        poll_interval_s=SCAN_WATCHER_DEFAULTS.poll_interval_s,
        stable_age_s=SCAN_WATCHER_DEFAULTS.stable_age_s,
        directory_copy_retry_s=SCAN_WATCHER_DEFAULTS.directory_copy_retry_s,
        open_pdf_after_move=SCAN_WATCHER_DEFAULTS.open_pdf_after_move,
    )


@dataclass(frozen=True)
class PipelineStatusSnapshot:
    state: PipelineState
    current_step_index: Optional[int]
    scan_count: int
    project_name: Optional[str]
    last_error: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    scanner_connected: bool
    robot_path_connected: bool
    turntable_connected: bool
    project_ready: bool
    trajectory_ready: bool
    initializing: bool
    can_resume: bool
    position_resend_step_indices: list[int]
    cycle_mode: CycleMode | None
    calibration_trajectory_ready: bool
    last_cycle_duration_sec: float | None
    last_cycle_timing_mode: CycleTimingMode | None


class PipelineService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._logger = get_logger(self.__class__.__name__)
        self._watcher: Optional[ScanFolderWatcher] = None
        self._watcher_config_key: Optional[tuple[str, str]] = None
        self._abort_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._init_thread: Optional[threading.Thread] = None
        self._init_stop_event = threading.Event()
        self._init_wake_event = threading.Event()
        self._robot: Optional[KukaEkiPathClient] = None

        self._state: PipelineState = "idle"
        self._current_step_index: Optional[int] = None
        self._scan_count = 0
        self._project_name: Optional[str] = None
        self._last_error: Optional[str] = None
        self._started_at: Optional[datetime] = None
        self._finished_at: Optional[datetime] = None
        self._initializing = False
        self._resume_start_list_index = 0
        self._resume_initial_scan_count = 0
        self._cycle_requires_startup_travel = False
        self._defer_project_creation = False
        self._position_resend_step_indices: set[int] = set()
        self._cycle_mode: CycleMode | None = None
        self._calibration_document: dict[str, Any] | None = None
        self._last_cycle_duration_sec: float | None = None
        self._last_cycle_timing_mode: CycleTimingMode | None = None

    def initialize(self) -> None:
        scanner_service.set_disconnect_callback(self.on_scanner_disconnected)
        self._init_stop_event.clear()
        self._init_wake_event.set()
        self._init_thread = threading.Thread(
            target=self._init_worker_loop,
            name="PipelineInitWorker",
            daemon=True,
        )
        self._init_thread.start()
        self._logger.info("Pipeline background initialization started")

    def shutdown(self) -> None:
        self._init_stop_event.set()
        self._init_wake_event.set()

        init_thread = self._init_thread
        self._init_thread = None
        if init_thread is not None and init_thread.is_alive():
            init_thread.join(timeout=5.0)

        if self._worker_thread is not None and self._worker_thread.is_alive():
            self.stop_cycle()

        self._stop_scan_watcher()

        self._close_robot_connection()

        try:
            scanner_service.stop()
        except Exception as exc:
            self._logger.warning("Scanner shutdown warning: %s", exc)

    def start_cycle(self) -> None:
        self._begin_cycle(resume=False)

    def start_calibration_cycle(self) -> None:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Pipeline cycle is already running")

        try:
            self._validate_ready_for_calibration()
            calibration_document = trajectory_service.read_named_document(CALIBRATION_PATH_FILE)
            validate_calibration_document(calibration_document)

            trajectory_service.load_named_file(CALIBRATION_PATH_FILE)
            snapshot = trajectory_service.get_snapshot()
            if snapshot.load_error:
                raise RuntimeError(f"Calibration trajectory load error: {snapshot.load_error}")

            with self._lock:
                robot = self._robot
            if robot is not None and snapshot.points:
                robot.points = list(snapshot.points)
                robot.current_point_idx = 0
                first_point = robot.points[0]
                robot.current_target = first_point.axes + [first_point.a7]

            first_scan_index = get_first_scan_list_index(snapshot.points)
            self._calibration_document = calibration_document
            self._cycle_mode = "calibration"
            self._cycle_requires_startup_travel = True
            self._resume_start_list_index = first_scan_index
            self._resume_initial_scan_count = 0
            self._position_resend_step_indices.clear()
            self._abort_event.clear()
            self._clear_cycle_timer()

            with self._lock:
                robot = self._robot
            if robot is not None:
                robot.clear_motion_cancel()

            self._set_state(
                state="running",
                current_step_index=None,
                scan_count=0,
                project_name=None,
                last_error=None,
                started_at=datetime.now(UTC),
                finished_at=None,
            )

            self._worker_thread = threading.Thread(
                target=self._run_calibration_worker,
                name="PipelineCalibrationWorker",
                daemon=True,
            )
            self._worker_thread.start()
            self._logger.info("Calibration cycle started")
        except Exception:
            self._cycle_mode = None
            self._calibration_document = None
            self._run_lock.release()
            raise

    def continue_cycle(self) -> None:
        if not self._can_resume():
            raise RuntimeError("Pipeline cannot be continued from the current state")
        self._begin_cycle(resume=True)

    def reload_scanner(self) -> None:
        with self._lock:
            was_running = self._state in {"running", "stopping"}

        if was_running:
            self._logger.info("Reloading scanner SDK; stopping active pipeline cycle first")
            self.stop_cycle()

        settings = get_runtime_settings()
        self._logger.info("Reloading scanner SDK...")
        if scanner_service.is_connected:
            scanner_service.restart(settings)
        else:
            scanner_service.start(settings)
        self._clear_resume_state()
        self._init_wake_event.set()
        self._logger.info("Scanner SDK reloaded")

    def reconnect_scanner(self) -> None:
        with self._lock:
            was_running = self._state in {"running", "stopping"}

        if was_running:
            self._logger.info("Reconnecting scanner; stopping active pipeline cycle first")
            self.stop_cycle()

        settings = get_runtime_settings()
        self._logger.info("Force reconnecting scanner to C++ host...")
        scanner_service.force_reconnect(settings)
        self._clear_resume_state()
        self._init_wake_event.set()
        self._logger.info("Scanner reconnected")

    def _begin_cycle(self, *, resume: bool) -> None:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Pipeline cycle is already running")

        try:
            self._validate_ready_to_start(resume=resume)
            if not resume:
                self._preflight_startup_travel()
            self._cycle_mode = "production"
            if resume:
                with self._lock:
                    project_name = self._project_name
                    start_list_index = self._current_step_index
                    initial_scan_count = self._scan_count

                if project_name is None or start_list_index is None:
                    raise RuntimeError("Pipeline resume state is incomplete")

                scanner_service.ensure_project(project_name, for_resume=True)
                self._resume_start_list_index = start_list_index
                self._resume_initial_scan_count = initial_scan_count
                self._logger.info(
                    "Continuing pipeline from step %d (scan count %d, project %s)",
                    start_list_index + 1,
                    initial_scan_count,
                    project_name,
                )
                running_step_index = start_list_index
                running_scan_count = initial_scan_count
            else:
                self._defer_project_creation = True
                project_name = None
                trajectory = trajectory_service.get_snapshot()
                first_scan_index = get_first_scan_list_index(trajectory.points)
                self._resume_start_list_index = first_scan_index
                self._resume_initial_scan_count = 0
                self._position_resend_step_indices.clear()
                running_step_index = None
                running_scan_count = 0

            self._cycle_requires_startup_travel = not resume
            if resume:
                self._defer_project_creation = False
            self._abort_event.clear()
            self._clear_cycle_timer()
            with self._lock:
                robot = self._robot
            if robot is not None:
                robot.clear_motion_cancel()
            self._set_state(
                state="running",
                current_step_index=running_step_index,
                scan_count=running_scan_count,
                project_name=project_name,
                last_error=None,
                started_at=datetime.now(UTC),
                finished_at=None,
            )

            self._worker_thread = threading.Thread(
                target=self._run_cycle_worker,
                name="PipelineCycleWorker",
                daemon=True,
            )
            self._worker_thread.start()
            if resume:
                self._logger.info("Pipeline cycle continued")
            else:
                self._logger.info("Pipeline cycle started")
        except SdkCommandError as exc:
            message = exc.user_message()
            self._set_last_error(message)
            self._cycle_mode = None
            raise RuntimeError(message) from exc
        except Exception:
            self._cycle_mode = None
            self._run_lock.release()
            raise

    def stop_cycle(self) -> None:
        with self._lock:
            if self._state not in {"running", "stopping"}:
                return
            self._state = "stopping"

        self._logger.info("Pipeline stop requested")
        self._abort_event.set()
        with self._lock:
            robot = self._robot
        if robot is not None:
            robot.cancel_motion()

        worker = self._worker_thread
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=5.0)

    def move_to_path_position(
        self,
        position_index: int,
        document: dict[str, Any] | None = None,
        *,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._state in {"running", "stopping"}:
                raise RuntimeError("Cannot move robot while pipeline is running")

        settings = get_runtime_settings()
        raw_document = document if document is not None else trajectory_service.get_active_document()
        if not isinstance(raw_document, dict):
            raise RuntimeError("Path document must be a JSON object")

        normalized_document = normalize_path_document(raw_document)
        points = normalized_document.get("points", [])
        nodes = normalized_document.get("nodes", [])
        if not isinstance(points, list):
            raise RuntimeError("Path document is missing 'points' array")
        if not isinstance(nodes, list):
            raise RuntimeError("Path document is missing 'nodes' array")
        if not nodes:
            raise RuntimeError("Path document has no nodes")

        goal_node: dict[str, Any] | None = None
        if node_id:
            for node in nodes:
                if isinstance(node, dict) and str(node.get("id", "")) == node_id:
                    goal_node = node
                    break
            if goal_node is None:
                raise RuntimeError(f"Node id not found: {node_id}")
        else:
            if position_index < 0 or position_index >= len(nodes):
                raise RuntimeError(f"Position index out of range: {position_index}")
            candidate = nodes[position_index]
            if not isinstance(candidate, dict):
                raise RuntimeError(f"Node #{position_index} must be an object")
            goal_node = candidate

        goal_id = str(goal_node.get("point_id", ""))
        if not goal_id:
            raise RuntimeError("Target node is missing point_id")

        safe_route_ids = normalized_document.get("safe_route_ids", [])
        safe_routes = normalized_document.get("safe_routes", [])

        snapshot = axis_receiver_service.get_snapshot()
        if snapshot.get("axes_available"):
            app_state.current_position = snapshot
        current_axes = read_current_axes_from_snapshot(app_state.current_position)
        start_ids, id_route = plan_id_route_to_goal(
            current_axes,
            points,
            safe_routes,
            safe_route_ids,
            goal_id,
        )

        robot = self._ensure_jog_robot_client(settings)

        if not robot.connected:
            try_connect_robot_path(
                robot,
                max_attempts=STARTUP_CONNECT_MAX_ATTEMPTS,
                status_timeout_sec=STARTUP_STATUS_TIMEOUT_SEC,
            )

        if not robot.turn_connected:
            try_connect_turntable(robot, max_attempts=STARTUP_CONNECT_MAX_ATTEMPTS)

        if not robot.connected or not robot.turn_connected:
            raise RuntimeError("Robot path or turntable is not connected")

        robot.clear_motion_cancel()

        goal_type = str(goal_node.get("type", "")).strip().lower()
        force_travel = goal_type == "basic_scan"
        goal_node_id = str(goal_node.get("id", "")).strip() or None
        turntable_angle_override = None if goal_type == "basic_scan" else 0.0

        return self._travel_by_id_route(
            robot,
            points,
            start_ids,
            goal_id,
            id_route,
            nodes=nodes,
            turntable_angle_override=turntable_angle_override,
            force_travel=force_travel,
            goal_node_id=goal_node_id,
            current_axes=current_axes,
        )

    def _plan_first_scan_travel(
        self,
        document: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str, list[str], list[str]]:
        normalized_document = normalize_path_document(
            document if document is not None else trajectory_service.get_active_document()
        )
        points = normalized_document.get("points", [])
        nodes = normalized_document.get("nodes", [])
        if not isinstance(points, list):
            raise RuntimeError("Path document is missing 'points' array")
        if not isinstance(nodes, list):
            raise RuntimeError("Path document is missing 'nodes' array")

        safe_route_ids = normalized_document.get("safe_route_ids", [])
        safe_routes = normalized_document.get("safe_routes", [])

        try:
            scan_id = find_first_scan_position_id(nodes)
        except ValueError as exc:
            raise RuntimeError("Path has no scan position") from exc

        current_axes = read_current_axes_from_snapshot(app_state.current_position)
        start_ids, id_route = plan_id_route_to_goal(
            current_axes,
            points,
            safe_routes,
            safe_route_ids,
            scan_id,
            no_route_message="No safe route to first scan position",
        )
        return normalized_document, scan_id, start_ids, id_route

    def _preflight_startup_travel(self, document: dict[str, Any] | None = None) -> None:
        _normalized, scan_id, start_ids, id_route = self._plan_first_scan_travel(document=document)
        self._logger.info(
            "Startup travel preflight OK: start_ids=%s scan_id=%s route=%s",
            start_ids,
            scan_id,
            id_route,
        )

    def _execute_startup_travel(
        self,
        robot: KukaEkiPathClient,
        abort_event: threading.Event,
        *,
        document: dict[str, Any] | None = None,
    ) -> None:
        normalized_document, scan_id, start_ids, id_route = self._plan_first_scan_travel(
            document=document
        )
        points = normalized_document.get("points", [])
        nodes = normalized_document.get("nodes", [])
        route_label = " → ".join(id_route)
        self._logger.info("Safe startup travel via route: %s", route_label)
        scan_node: dict[str, Any] = {}
        force_travel = False
        goal_node_id: str | None = None
        if isinstance(nodes, list) and nodes:
            try:
                scan_node = find_first_scan_node(nodes)
                force_travel = str(scan_node.get("type", "")).strip().lower() == "basic_scan"
                goal_node_id = str(scan_node.get("id", "")).strip() or None
            except ValueError:
                pass
        result = self._travel_by_id_route(
            robot,
            points if isinstance(points, list) else [],
            start_ids,
            scan_id,
            id_route,
            abort_event=abort_event,
            nodes=nodes if isinstance(nodes, list) else None,
            force_travel=force_travel,
            goal_node_id=goal_node_id,
        )
        if result["hops_executed"] > 0:
            self._logger.info("Safe startup travel complete to id=%s", scan_id)

    def _strip_matching_prefix_hops(
        self,
        hops: list[tuple[str, list[float], float]],
        current_axes: list[float],
    ) -> list[tuple[str, list[float], float]]:
        stripped = list(hops)
        while stripped:
            _route_id, target_axes, _angle = stripped[0]
            if axes_match(current_axes, target_axes):
                stripped = stripped[1:]
                continue
            break
        return stripped

    def _build_travel_steps(
        self,
        travel_plan: list[tuple[str, list[float], float]],
        executed_hops: list[tuple[str, list[float], float]],
        points: list[dict[str, Any]],
        nodes: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        point_by_id = {
            str(point.get("id", "")): point
            for point in points
            if isinstance(point, dict) and str(point.get("id", ""))
        }
        node_by_point_id: dict[str, dict[str, Any]] = {}
        if nodes:
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                point_id = str(node.get("point_id", "")).strip()
                if point_id:
                    node_by_point_id[point_id] = node

        executed_keys = {(route_id, tuple(axes), angle) for route_id, axes, angle in executed_hops}

        steps: list[dict[str, Any]] = []
        hop_index = 0
        for route_id, axes, turntable_angle in travel_plan:
            point = point_by_id.get(route_id, {})
            node = node_by_point_id.get(route_id, {})
            name = str(point.get("name") or point.get("comment") or route_id).strip()
            node_type = str(node.get("type", "transition")).strip() or "transition"
            skipped = True
            if hop_index < len(executed_hops):
                exec_id, exec_axes, exec_angle = executed_hops[hop_index]
                if exec_id == route_id and axes_match(list(exec_axes), list(axes)) and exec_angle == turntable_angle:
                    skipped = False
                    hop_index += 1
            steps.append(
                {
                    "point_id": route_id,
                    "name": name,
                    "node_type": node_type,
                    "turntable_angle": float(turntable_angle),
                    "skipped": skipped,
                }
            )
        return steps

    def _travel_by_id_route(
        self,
        robot: KukaEkiPathClient,
        points: list[dict[str, Any]],
        start_ids: list[str],
        goal_id: str,
        id_route: list[str],
        *,
        abort_event: threading.Event | None = None,
        nodes: list[dict[str, Any]] | None = None,
        turntable_angle_override: float | None = None,
        force_travel: bool = False,
        goal_node_id: str | None = None,
        current_axes: list[float] | None = None,
    ) -> dict[str, Any]:
        if abort_event is not None and abort_event.is_set():
            raise RuntimeError("Cycle aborted")

        if not force_travel and id_route[0] in start_ids and goal_id in start_ids:
            self._logger.info("Robot already at id=%s; travel skipped", goal_id)
            return {"route": id_route, "hops_executed": 0}

        travel_plan = build_travel_plan_by_id(
            points,
            id_route,
            nodes=nodes,
            goal_point_id=goal_id,
            goal_node_id=goal_node_id,
        )
        if force_travel and goal_id in start_ids:
            hops = [travel_plan[-1]] if travel_plan else []
        elif id_route[0] in start_ids:
            hops = travel_plan[1:]
        else:
            hops = travel_plan

        if current_axes is not None and not force_travel:
            hops = self._strip_matching_prefix_hops(hops, current_axes)

        travel_steps = self._build_travel_steps(travel_plan, hops, points, nodes)

        for hop_index, (route_id, axes, turntable_angle) in enumerate(hops, start=1):
            if abort_event is not None and abort_event.is_set():
                raise RuntimeError("Cycle aborted")
            angle = turntable_angle_override if turntable_angle_override is not None else turntable_angle
            self._logger.info(
                "Travel hop %d/%d to id=%s (A7=%s)",
                hop_index,
                len(hops),
                route_id,
                angle,
            )
            robot.jog_to_target(axes, angle, settle_sec=SETTLE_SEC, abort_event=abort_event)

        self._logger.info("Travel complete to id=%s via route %s", goal_id, id_route)
        return {"route": id_route, "hops_executed": len(hops), "travel_steps": travel_steps}

    def _travel_to_home(
        self,
        robot: KukaEkiPathClient,
        *,
        abort_event: threading.Event | None = None,
        document: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if abort_event is not None and abort_event.is_set():
            raise RuntimeError("Cycle aborted")

        raw_document = document if document is not None else trajectory_service.get_active_document()
        if not isinstance(raw_document, dict):
            raise RuntimeError("Path document must be a JSON object")

        normalized_document = normalize_path_document(raw_document)
        points = normalized_document.get("points", [])
        nodes = normalized_document.get("nodes", [])
        if not isinstance(points, list) or not isinstance(nodes, list) or not nodes:
            raise RuntimeError("Path document has no nodes")

        home_id = find_home_position_id(nodes)
        home_node_id: str | None = None
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("type", "")).strip().lower() == "home":
                home_node_id = str(node.get("id", "")).strip() or None
                break

        safe_route_ids = normalized_document.get("safe_route_ids", [])
        safe_routes = normalized_document.get("safe_routes", [])

        current_axes = read_current_axes_from_snapshot(app_state.current_position)
        start_ids, id_route = plan_id_route_to_goal(
            current_axes,
            points,
            safe_routes,
            safe_route_ids,
            home_id,
            no_route_message="No safe route to home position",
        )

        self._logger.info("Returning to home via safe route: %s", " → ".join(id_route))
        return self._travel_by_id_route(
            robot,
            points,
            start_ids,
            home_id,
            id_route,
            abort_event=abort_event,
            nodes=nodes,
            turntable_angle_override=0.0,
            goal_node_id=home_node_id,
        )

    def get_status(self) -> PipelineStatusSnapshot:
        with self._lock:
            trajectory = trajectory_service.get_snapshot()
            trajectory_ready = (
                trajectory.load_error is None
                and len(trajectory.points) > 0
                and any(is_end_point(point) for point in trajectory.points)
            )
            scanner_connected = scanner_service.is_connected
            robot_path_connected = self._is_robot_path_connected()
            turntable_connected = self._is_turntable_connected()
            project_ready = bool(self._project_name)
            can_resume = self._can_resume_locked()
            return PipelineStatusSnapshot(
                state=self._state,
                current_step_index=self._current_step_index,
                scan_count=self._scan_count,
                project_name=self._project_name,
                last_error=self._last_error,
                started_at=self._started_at.isoformat() if self._started_at else None,
                finished_at=self._finished_at.isoformat() if self._finished_at else None,
                scanner_connected=scanner_connected,
                robot_path_connected=robot_path_connected,
                turntable_connected=turntable_connected,
                project_ready=project_ready,
                trajectory_ready=trajectory_ready,
                initializing=self._initializing,
                can_resume=can_resume,
                position_resend_step_indices=sorted(self._position_resend_step_indices),
                cycle_mode=self._cycle_mode,
                calibration_trajectory_ready=trajectory_service.is_calibration_trajectory_ready(),
                last_cycle_duration_sec=self._last_cycle_duration_sec,
                last_cycle_timing_mode=self._last_cycle_timing_mode,
            )

    def apply_settings_section(
        self,
        settings: RuntimeSettings,
        previous: RuntimeSettings,
        section: str | None,
    ) -> SettingsApplyResult:
        if section is None:
            return self._apply_global_settings(settings, previous)

        try:
            if section == SETTINGS_SECTION_AXIS_TELEMETRY:
                apply_runtime_logging_settings(
                    log_level=settings.log_level,
                    log_to_file=settings.log_to_file,
                    log_file_path=settings.log_file_path,
                )
                axis_receiver_service.restart(settings)
                return SettingsApplyResult.success()

            if section == SETTINGS_SECTION_LOGGING:
                apply_runtime_logging_settings(
                    log_level=settings.log_level,
                    log_to_file=settings.log_to_file,
                    log_file_path=settings.log_file_path,
                )
                apply_sdk_logging(settings, restart_native_mirror=scanner_service.is_connected)
                return SettingsApplyResult.success()

            if section == SETTINGS_SECTION_PATHS:
                trajectory_service.reload_active()
                return SettingsApplyResult.success()

            if section == SETTINGS_SECTION_PIPELINE:
                self._apply_pipeline_watcher_settings(settings)
                return SettingsApplyResult.success()

            if section == SETTINGS_SECTION_ROBOT_PATH:
                return self._apply_robot_path_settings(settings)

            if section == SETTINGS_SECTION_SCANNER_CONNECTION:
                return self._apply_scanner_connection_settings(settings, previous)

            if section in SCANNER_SETTINGS_SECTIONS:
                return self._apply_scanner_settings_section(section, settings, previous)

            return SettingsApplyResult.failure(f"Unknown settings section: {section}")
        except SdkCommandError as exc:
            self._logger.warning("Settings section %s apply failed: %s", section, exc)
            self._set_last_error(f"Scanner: {exc}")
            return SettingsApplyResult.from_sdk_error(exc)
        except Exception as exc:
            self._logger.warning("Settings section %s apply failed: %s", section, exc)
            return SettingsApplyResult.from_sdk_error(exc)

    def _apply_global_settings(
        self,
        settings: RuntimeSettings,
        previous: RuntimeSettings,
    ) -> SettingsApplyResult:
        apply_runtime_logging_settings(
            log_level=settings.log_level,
            log_to_file=settings.log_to_file,
            log_file_path=settings.log_file_path,
        )
        apply_sdk_logging(settings, restart_native_mirror=scanner_service.is_connected)
        axis_receiver_service.restart(settings)
        trajectory_service.reload_active()

        try:
            self._apply_pipeline_watcher_settings(settings)
            self._apply_scanner_after_settings_save(settings, previous)
            self._schedule_robot_reconnect()
            return SettingsApplyResult.success()
        except SdkCommandError as exc:
            self._logger.warning("Global settings apply failed: %s", exc)
            self._set_last_error(f"Scanner: {exc}")
            return SettingsApplyResult.from_sdk_error(exc)
        except Exception as exc:
            self._logger.warning("Global settings apply failed: %s", exc)
            return SettingsApplyResult.from_sdk_error(exc)

    def _apply_pipeline_watcher_settings(self, settings: RuntimeSettings) -> None:
        if not settings.pipeline.scan_folder_watcher_enabled:
            self._stop_scan_watcher()
        elif self._is_robot_fully_connected():
            self._maybe_start_scan_watcher(settings)

    def _apply_robot_path_settings(self, settings: RuntimeSettings) -> SettingsApplyResult:
        with self._lock:
            is_running = self._state in {"running", "stopping"}

        if is_running:
            return SettingsApplyResult.failure("Apply deferred: pipeline is running")

        self._schedule_robot_reconnect()
        return SettingsApplyResult.success()

    def _apply_scanner_connection_settings(
        self,
        settings: RuntimeSettings,
        previous: RuntimeSettings,
    ) -> SettingsApplyResult:
        with self._lock:
            is_running = self._state in {"running", "stopping"}

        if is_running:
            return SettingsApplyResult.failure("Apply deferred: pipeline is running")

        if not scanner_service.is_connected:
            return SettingsApplyResult.success()

        if scanner_service.needs_connection_restart(previous, settings):
            scanner_service.restart(settings)
            self._clear_scanner_project()
            self._logger.info("Scanner restarted with updated connection settings")

        return SettingsApplyResult.success()

    def _apply_scanner_settings_section(
        self,
        section: str,
        settings: RuntimeSettings,
        previous: RuntimeSettings,
    ) -> SettingsApplyResult:
        if section in SAVE_ONLY_SCANNER_SECTIONS:
            return SettingsApplyResult.success()

        with self._lock:
            is_running = self._state in {"running", "stopping"}

        if is_running:
            return SettingsApplyResult.failure("Apply deferred: pipeline is running")

        if not scanner_service.ensure_connected(settings):
            self._init_wake_event.set()
            return SettingsApplyResult.failure(
                "Scanner not connected; settings saved to file only"
            )

        if (
            section == SETTINGS_SECTION_SDK_PATHS
            and previous.scanner.process_path != settings.scanner.process_path
        ):
            scanner_service.restart(settings)
            self._clear_scanner_project()
            self._logger.info("Scanner restarted after SDK process path change")
            return SettingsApplyResult.success()

        scanner_service.apply_section(section, settings, previous=previous)
        self._logger.info("Scanner section %s applied", section)
        return SettingsApplyResult.success()

    def _apply_scanner_after_settings_save(
        self,
        settings: RuntimeSettings,
        previous: RuntimeSettings,
    ) -> None:
        with self._lock:
            is_running = self._state in {"running", "stopping"}

        if is_running:
            self._logger.info("Settings saved during pipeline run; reconnect skipped")
            return

        if not scanner_service.is_connected:
            return

        if scanner_service.needs_connection_restart(previous, settings):
            scanner_service.restart(settings)
            self._clear_scanner_project()
            self._logger.info("Scanner restarted with updated connection settings")
        else:
            scanner_service.apply_parameters(settings)
            self._logger.info("Scanner parameters updated without reconnect")

    def _schedule_robot_reconnect(self) -> None:
        self._close_robot_connection()
        self._init_wake_event.set()
        self._logger.info("Settings saved; pipeline background reconnect scheduled")

    def on_settings_updated(
        self,
        settings: RuntimeSettings,
        previous: RuntimeSettings,
    ) -> None:
        result = self.apply_settings_section(settings, previous, None)
        if not result.applied and result.apply_error:
            self._logger.warning("Settings update apply failed: %s", result.apply_error)

    def on_scanner_disconnected(self) -> None:
        from app.scanner.camera_stream import camera_stream_service

        camera_stream_service.notify_scanner_disconnected_sync()
        self._clear_scanner_project()
        self._set_last_error("Scanner device offline")
        self._init_wake_event.set()
        self._logger.info("Scanner disconnected; pipeline reconnect scheduled")

    def _clear_scanner_project(self) -> None:
        self._clear_resume_state()

    def _clear_resume_state(self) -> None:
        with self._lock:
            self._project_name = None
            self._current_step_index = None
            self._scan_count = 0

    def _can_resume(self) -> bool:
        with self._lock:
            return self._can_resume_locked()

    def _can_resume_locked(self) -> bool:
        return (
            self._state == "idle"
            and self._project_name is not None
            and self._current_step_index is not None
            and not self._initializing
        )

    def on_path_updated(self) -> None:
        with self._lock:
            is_running = self._state in {"running", "stopping"}

        if is_running:
            self._logger.info("Path updated during pipeline run; reload skipped")
            return

        with self._lock:
            robot = self._robot

        trajectory = trajectory_service.get_snapshot()
        if robot is not None and trajectory.points:
            robot.points = list(trajectory.points)
            robot.current_point_idx = 0
            first_point = robot.points[0]
            robot.current_target = first_point.axes + [first_point.a7]
            self._logger.info("Updated robot trajectory points from active path")

        self._init_wake_event.set()
        self._logger.info("Path updated; pipeline background reconnect scheduled")

    def _init_worker_loop(self) -> None:
        while not self._init_stop_event.is_set():
            self._init_wake_event.wait(timeout=INIT_RETRY_INTERVAL_SEC)
            self._init_wake_event.clear()

            if self._init_stop_event.is_set() or app_state.is_shutting_down:
                break

            with self._lock:
                if self._state in {"running", "stopping"}:
                    continue

            self._set_initializing(True)
            try:
                self._run_init_pass()
            except Exception as exc:
                self._logger.warning("Pipeline init pass failed: %s", exc)
                self._set_last_error(str(exc))
            finally:
                self._set_initializing(False)

    def _run_init_pass(self) -> None:
        if app_state.is_shutting_down:
            return

        settings = get_runtime_settings()

        if not scanner_service.is_connected:
            if scanner_service.is_connecting() or scanner_service.is_restarting():
                self._logger.debug(
                    "Scanner connect/restart in progress; skipping background start"
                )
            else:
                try:
                    scanner_service.start(settings)
                    self._clear_scanner_project()
                    self._logger.info("Scanner connected")
                except Exception as exc:
                    self._logger.warning("Scanner connect failed: %s", exc)
                    self._set_last_error(f"Scanner: {exc}")

        robot = self._ensure_robot_client(settings)
        if robot is None:
            return

        if not robot.connected:
            try:
                try_connect_robot_path(
                    robot,
                    max_attempts=STARTUP_CONNECT_MAX_ATTEMPTS,
                    status_timeout_sec=STARTUP_STATUS_TIMEOUT_SEC,
                )
                self._logger.info("Robot path connected")
            except Exception as exc:
                self._logger.warning("Robot path connect failed: %s", exc)
                self._set_last_error(f"Robot path: {exc}")

        if not robot.turn_connected:
            try:
                try_connect_turntable(robot, max_attempts=STARTUP_CONNECT_MAX_ATTEMPTS)
                self._logger.info("Turntable connected")
            except Exception as exc:
                self._logger.warning("Turntable connect failed: %s", exc)
                self._set_last_error(f"Turntable: {exc}")

        if not self._is_robot_fully_connected():
            return

        self._maybe_start_scan_watcher(settings)

        if scanner_service.is_connected and self._is_robot_fully_connected():
            self._set_last_error(None)

    def _stop_scan_watcher(self) -> None:
        watcher = self._watcher
        self._watcher = None
        self._watcher_config_key = None
        if watcher is None:
            return
        try:
            watcher.stop()
            self._logger.info("Background scan watcher stopped")
        except Exception as exc:
            self._logger.warning("Watcher stop warning: %s", exc)

    def _maybe_start_scan_watcher(self, settings: RuntimeSettings) -> None:
        if not settings.pipeline.scan_folder_watcher_enabled:
            return
        if not self._is_robot_fully_connected():
            return

        monitored_folder = settings.pipeline.scan_import_monitored_folder.strip()
        if not monitored_folder:
            self._logger.warning(
                "Scan folder watcher enabled but import monitored folder is not configured"
            )
            return

        config_key = (settings.scanner.export_root, monitored_folder)
        if self._watcher is not None and self._watcher_config_key == config_key:
            return

        self._stop_scan_watcher()
        try:
            self._watcher = ScanFolderWatcher(build_scan_watcher_settings(settings))
            self._watcher.start()
            self._watcher_config_key = config_key
            self._logger.info("Background scan watcher started")
        except Exception as exc:
            self._logger.warning("Scan watcher initialization failed: %s", exc)

    def _ensure_robot_client(self, settings: RuntimeSettings) -> Optional[KukaEkiPathClient]:
        trajectory = trajectory_service.get_snapshot()
        if trajectory.load_error:
            self._set_last_error(f"Trajectory: {trajectory.load_error}")
            return None
        if not trajectory.points:
            self._set_last_error("Trajectory is empty")
            return None

        with self._lock:
            if self._robot is not None:
                return self._robot

        robot = create_robot_client(
            list(trajectory.points),
            settings.robot_host,
            settings.robot_port,
            settings.turntable_port,
        )
        with self._lock:
            self._robot = robot
        return robot

    def _ensure_jog_robot_client(self, settings: RuntimeSettings) -> KukaEkiPathClient:
        with self._lock:
            if self._robot is not None:
                return self._robot

        robot = KukaEkiPathClient(
            robot_ip=settings.robot_host,
            robot_port=settings.robot_port,
            turntable_port=settings.turntable_port,
            heartbeat_period=HEARTBEAT_PERIOD,
            recv_timeout=RECV_TIMEOUT,
        )
        with self._lock:
            self._robot = robot
        return robot

    def _validate_ready_to_start(self, *, resume: bool = False) -> None:
        with self._lock:
            initializing = self._initializing

        if initializing:
            raise RuntimeError("Pipeline is still initializing; wait and retry")

        if scanner_service.is_connecting() or scanner_service.is_restarting():
            raise RuntimeError("Scanner is connecting; wait and retry")

        if not scanner_service.is_connected:
            raise RuntimeError("Scanner SDK is not connected")

        if not self._is_robot_fully_connected():
            raise RuntimeError("Robot path or turntable is not connected")

        with self._lock:
            robot = self._robot
        if robot is not None and robot.connected:
            with robot.lock:
                robot_status = robot.robot_status
            if (
                robot_status is not None
                and robot_status != robot.STATUS_IDLE
            ):
                raise RuntimeError(
                    "Robot is not IDLE; wait for motion to finish"
                )

        if not resume and not app_state.current_position.get("connected"):
            raise RuntimeError("Axis telemetry is not connected")

        trajectory = trajectory_service.get_snapshot()
        if trajectory.load_error:
            raise RuntimeError(f"Trajectory load error: {trajectory.load_error}")
        if not trajectory.points:
            raise RuntimeError("Trajectory is empty")
        if not any(is_end_point(point) for point in trajectory.points):
            raise RuntimeError("Trajectory has no end point")

    def _validate_ready_for_calibration(self) -> None:
        with self._lock:
            initializing = self._initializing

        if initializing:
            raise RuntimeError("Pipeline is still initializing; wait and retry")

        if scanner_service.is_connecting() or scanner_service.is_restarting():
            raise RuntimeError("Scanner is connecting; wait and retry")

        if not scanner_service.is_connected:
            raise RuntimeError("Scanner SDK is not connected")

        if not self._is_robot_fully_connected():
            raise RuntimeError("Robot path or turntable is not connected")

        with self._lock:
            robot = self._robot
        if robot is not None and robot.connected:
            with robot.lock:
                robot_status = robot.robot_status
            if (
                robot_status is not None
                and robot_status != robot.STATUS_IDLE
            ):
                raise RuntimeError(
                    "Robot is not IDLE; wait for motion to finish"
                )

        if not app_state.current_position.get("connected"):
            raise RuntimeError("Axis telemetry is not connected")

        if not trajectory_service.is_calibration_trajectory_ready():
            raise RuntimeError(
                "Calibration trajectory is not ready; ensure calibration.json has "
                "home, basic_scan nodes only, and an end point"
            )

        self._preflight_startup_travel(
            document=trajectory_service.read_named_document(CALIBRATION_PATH_FILE)
        )

    def _run_cycle_worker(self) -> None:
        try:
            cycle_settings = get_runtime_settings()
            cycle_run_mode = cycle_settings.pipeline.cycle_run_mode

            while True:
                if self._abort_event.is_set():
                    raise RuntimeError("Cycle aborted")

                lap_started_at = datetime.now(UTC)
                with self._lock:
                    self._started_at = lap_started_at

                cycle_result = self._execute_production_cycle_lap(cycle_settings)

                finished_at = datetime.now(UTC)
                timing_mode = self._timing_mode_for_pipeline(cycle_settings.pipeline)
                timing_end = finished_at
                if (
                    timing_mode == "last_scan"
                    and cycle_result.last_position_reached_at is not None
                ):
                    timing_end = cycle_result.last_position_reached_at
                with self._lock:
                    self._project_name = cycle_result.project_name
                    self._finished_at = finished_at
                    self._last_error = None
                    self._record_cycle_timer(timing_end, timing_mode)
                append_cycle_history_entry(
                    build_cycle_history_entry(
                        started_at=lap_started_at,
                        project_name=cycle_result.project_name,
                        mesh_export_finished_at=cycle_result.mesh_export_finished_at,
                        timing_end_at=timing_end,
                    )
                )
                self._logger.info("Pipeline cycle finished: %s", cycle_result.project_name)

                if cycle_run_mode != "repeat_on_success":
                    with self._lock:
                        self._state = "idle"
                        self._current_step_index = None
                        self._scan_count = 0
                    break

                if self._abort_event.is_set():
                    raise RuntimeError("Cycle aborted")

                self._prepare_next_repeat_lap()
                self._logger.info(
                    "Repeat-on-success: starting next cycle in %.1fs",
                    RESTART_DELAY_SEC,
                )
                time.sleep(RESTART_DELAY_SEC)

            with self._lock:
                if cycle_run_mode == "repeat_on_success":
                    self._state = "idle"
                    self._current_step_index = None
                    self._scan_count = 0
        except SdkCommandError as exc:
            message = exc.user_message()
            with self._lock:
                self._state = "error"
                self._last_error = message
                self._finished_at = datetime.now(UTC)
            self._logger.error("Pipeline cycle failed: %s", exc)
        except Exception as exc:
            message = str(exc)
            with self._lock:
                self._state = "error" if message != "Cycle aborted" else "idle"
                self._last_error = None if message == "Cycle aborted" else message
                self._finished_at = datetime.now(UTC)
            if message == "Cycle aborted":
                self._logger.info("Pipeline cycle aborted")
            else:
                self._logger.error("Pipeline cycle failed: %s", exc)
        finally:
            self._abort_event.clear()
            with self._lock:
                robot = self._robot
            if robot is not None:
                robot.clear_motion_cancel()
            self._run_lock.release()

    @staticmethod
    def _timing_mode_for_pipeline(pipeline_settings) -> CycleTimingMode:
        if pipeline_settings.cycle_run_mode == "single_last_scan":
            return "last_scan"
        return "full_cycle"

    def get_cycle_history(self) -> list[CycleHistoryEntry]:
        document = load_cycle_history()
        return list(reversed(document.entries))

    def _execute_production_cycle_lap(self, cycle_settings: RuntimeSettings) -> CycleRunResult:
        if self._defer_project_creation:
            self._create_project()
            self._defer_project_creation = False

        with self._lock:
            robot = self._robot
            project_name = self._project_name

        if robot is None:
            raise RuntimeError("Robot is not connected")
        if not project_name:
            raise RuntimeError("Scanner project is not ready")

        if self._cycle_requires_startup_travel:
            self._execute_startup_travel(robot, self._abort_event)

        class Progress:
            def on_step(self, list_index: int, scan_count: int, active_project: str) -> None:
                with self_outer._lock:
                    self_outer._current_step_index = list_index
                    self_outer._scan_count = scan_count
                    self_outer._project_name = active_project

            def on_position_resent(self, list_index: int) -> None:
                with self_outer._lock:
                    self_outer._position_resend_step_indices.add(list_index)

        self_outer = self
        progress = Progress()

        stop_after_last_scan = cycle_settings.pipeline.cycle_run_mode == "single_last_scan"

        cycle_result = run_cycle(
            robot,
            scanner_service,
            project_name,
            abort_event=self._abort_event,
            progress=progress,
            start_list_index=self._resume_start_list_index,
            initial_scan_count=self._resume_initial_scan_count,
            per_point_exposure=trajectory_service.get_snapshot().per_point_exposure,
            per_point_marker_exposure=trajectory_service.get_snapshot().per_point_marker_exposure,
            stop_after_last_scan=stop_after_last_scan,
        )

        if stop_after_last_scan:
            self._travel_to_home(robot, abort_event=self._abort_event)

        return cycle_result

    def _prepare_next_repeat_lap(self) -> None:
        trajectory = trajectory_service.get_snapshot()
        first_scan_index = get_first_scan_list_index(trajectory.points)

        self._create_project()
        self._resume_start_list_index = first_scan_index
        self._resume_initial_scan_count = 0
        self._cycle_requires_startup_travel = True
        self._position_resend_step_indices.clear()

        with self._lock:
            robot = self._robot
        if robot is not None and trajectory.points:
            robot.points = list(trajectory.points)
            robot.current_point_idx = 0
            first_point = robot.points[0]
            robot.current_target = first_point.axes + [first_point.a7]
            robot.clear_motion_cancel()

    def _run_calibration_worker(self) -> None:
        calibration_document = self._calibration_document
        try:
            with self._lock:
                robot = self._robot

            if robot is None:
                raise RuntimeError("Robot is not connected")

            settings = get_runtime_settings()
            scanner_service.enter_calibration(settings.pipeline.calibration)

            try:
                if self._cycle_requires_startup_travel:
                    self._execute_startup_travel(
                        robot,
                        self._abort_event,
                        document=calibration_document,
                    )

                class Progress:
                    def on_step(self, list_index: int, scan_count: int, _active_project: str) -> None:
                        with self_outer._lock:
                            self_outer._current_step_index = list_index
                            self_outer._scan_count = scan_count

                    def on_position_resent(self, list_index: int) -> None:
                        with self_outer._lock:
                            self_outer._position_resend_step_indices.add(list_index)

                self_outer = self
                progress = Progress()

                run_calibration_cycle(
                    robot,
                    scanner_service,
                    abort_event=self._abort_event,
                    progress=progress,
                    start_list_index=self._resume_start_list_index,
                    initial_capture_count=self._resume_initial_scan_count,
                )

                finished_at = datetime.now(UTC)
                with self._lock:
                    self._state = "idle"
                    self._current_step_index = None
                    self._scan_count = 0
                    self._finished_at = finished_at
                    self._last_error = None
                    self._record_cycle_timer(finished_at, "full_cycle")
                self._logger.info("Calibration cycle finished")
            finally:
                try:
                    scanner_service.exit_calibration()
                except Exception as exc:
                    self._logger.warning("exit_calibration failed: %s", exc)
        except SdkCommandError as exc:
            message = exc.user_message()
            with self._lock:
                self._state = "error"
                self._last_error = message
                self._finished_at = datetime.now(UTC)
            self._logger.error("Calibration cycle failed: %s", exc)
        except Exception as exc:
            message = str(exc)
            with self._lock:
                self._state = "error" if message != "Cycle aborted" else "idle"
                self._last_error = None if message == "Cycle aborted" else message
                self._finished_at = datetime.now(UTC)
            if message == "Cycle aborted":
                self._logger.info("Calibration cycle aborted")
            else:
                self._logger.error("Calibration cycle failed: %s", exc)
        finally:
            self._abort_event.clear()
            with self._lock:
                robot = self._robot
            if robot is not None:
                robot.clear_motion_cancel()
            self._cycle_mode = None
            self._calibration_document = None
            try:
                trajectory_service.reload_active()
                self.on_path_updated()
            except Exception as exc:
                self._logger.warning("Failed to restore active trajectory after calibration: %s", exc)
            self._run_lock.release()

    def _close_robot_connection(self) -> None:
        with self._lock:
            robot = self._robot
            self._robot = None

        if robot is None:
            return

        try:
            robot.stop()
            self._logger.info("Robot connection closed")
        except Exception as exc:
            self._logger.warning("Robot stop warning: %s", exc)

    def _disconnect_robot(self) -> None:
        self._close_robot_connection()
        self._clear_scanner_project()

    def _create_project(self) -> None:
        project_name = prepare_next_project(scanner_service)
        with self._lock:
            self._project_name = project_name
        self._logger.info("Scanner project ready: %s", project_name)

    def _is_robot_path_connected(self) -> bool:
        robot = self._robot
        return robot is not None and robot.connected

    def _is_turntable_connected(self) -> bool:
        robot = self._robot
        return robot is not None and robot.turn_connected

    def _is_robot_fully_connected(self) -> bool:
        return self._is_robot_path_connected() and self._is_turntable_connected()

    def _set_initializing(self, value: bool) -> None:
        with self._lock:
            self._initializing = value

    def _set_last_error(self, message: Optional[str]) -> None:
        with self._lock:
            self._last_error = message

    def _clear_cycle_timer(self) -> None:
        with self._lock:
            self._last_cycle_duration_sec = None
            self._last_cycle_timing_mode = None

    def _record_cycle_timer(
        self,
        finished_at: datetime,
        timing_mode: CycleTimingMode,
    ) -> None:
        if self._started_at is None:
            return
        duration_sec = max(0.0, (finished_at - self._started_at).total_seconds())
        self._last_cycle_duration_sec = duration_sec
        self._last_cycle_timing_mode = timing_mode

    def _set_state(
        self,
        *,
        state: PipelineState,
        current_step_index: Optional[int],
        scan_count: int,
        project_name: Optional[str],
        last_error: Optional[str],
        started_at: Optional[datetime],
        finished_at: Optional[datetime],
    ) -> None:
        with self._lock:
            self._state = state
            self._current_step_index = current_step_index
            self._scan_count = scan_count
            self._project_name = project_name
            self._last_error = last_error
            self._started_at = started_at
            self._finished_at = finished_at


pipeline_service = PipelineService()
