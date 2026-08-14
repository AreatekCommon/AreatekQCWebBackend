from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from coctrl_eki import KukaEkiPathClient
from q12_client import SdkConfig, TcpJsonTransport, Sn3dSdkClient, Sn3dCommandFactory
from auto_import import ScanFolderWatcher, ScanFolderWatcherSettings


ROBOT_IP = "192.168.0.5"
ROBOT_PORT = 54603
TURNTABLE_PORT = 54601
PATH_FOLDER = r"C:\Users\Areatek\Desktop\KUKA TRAJECTORIES"

SCANNER_HOST = "127.0.0.1"
SCANNER_PORT = 3001
SDK_TIMEOUT_SEC = 120.0
SDK_PROCESS_PATH = r"C:\Program Files\OptimScan Q\Sn3DProcessManager.exe"

PROJECT_ROOT = r"C:\Shining Projects"
EXPORT_ROOT = r"C:\Users\Areatek\Desktop\scans"

SETTLE_SEC = 1.0
RESTART_DELAY_SEC = 1.0
RUN_GLOBAL_OPT = False
REAPPLY_PARAMS_EACH_CYCLE = False
SAVE_TYPE = "stl"

SCAN_WATCHER_SETTINGS = ScanFolderWatcherSettings(
    scans_root=EXPORT_ROOT,
    monitored_folder="",
    successful_imports_dir_name="Successful_imports",
    failed_imports_dir_name="Failed_imports",
    reports_dir_name="reports",
    poll_interval_s=1.0,
    stable_age_s=2.0,
    directory_copy_retry_s=0.5,
    open_pdf_after_move=True,
)


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [APP] {message}", flush=True)


def connect_scanner() -> Sn3dSdkClient:
    config = SdkConfig(
        host=SCANNER_HOST,
        port=SCANNER_PORT,
        timeout_sec=SDK_TIMEOUT_SEC,
    )
    transport = TcpJsonTransport(config)
    sdk = Sn3dSdkClient(transport, timeout_sec=SDK_TIMEOUT_SEC)

    log("Connecting to scanner SDK...")
    sdk.connect()
    sdk.initialize_sdk(SDK_PROCESS_PATH)

    log("Applying scanner parameters...")
    apply_scanner_parameters(sdk)

    log("Scanner SDK ready")
    return sdk


def apply_scanner_parameters(sdk: Sn3dSdkClient) -> None:
    sdk.send_command(
        Sn3dCommandFactory.set_camera_exposure(
            exp_type=1,
            exp_obj=0,
            marker_exp=8,
            val1=7,
            val2=1,
            val3=1,
        )
    )
    sdk.send_command(
        Sn3dCommandFactory.set_exposure_range(
            center_x=1024,
            center_y=750,
            radius=100,
        )
    )
    sdk.send_command(
        Sn3dCommandFactory.set_background_mask(
            mask_enable=False,
            mask_val=30,
        )
    )
    sdk.send_command(
        Sn3dCommandFactory.set_camera_gain(
            camera=0,
            val=0.1,
        )
    )
    sdk.send_command(
        Sn3dCommandFactory.set_scan_params(
            align_mod=4,
            scan_markers=True,
            scan_point_cloud=False,
            add_global_markers=True,
            monocular_scan=False,
            resolution=2,
            marker_radius=7,
            scan_obj=2,
        )
    )


def connect_robot() -> KukaEkiPathClient:
    json_file = KukaEkiPathClient.find_latest_json(PATH_FOLDER)
    log(f"Using path file: {json_file}")

    robot = KukaEkiPathClient(
        robot_ip=ROBOT_IP,
        robot_port=ROBOT_PORT,
        turntable_port=TURNTABLE_PORT,
        heartbeat_period=0.2,
        recv_timeout=0.2,
        json_path=json_file,
        allowed_point_types=None,
    )

    robot.load_points_from_json()
    if not robot.points:
        raise RuntimeError("Trajectory is empty")

    log("Connecting to robot...")
    robot.start()

    if not robot.wait_until_status(robot.STATUS_IDLE):
        raise RuntimeError("Robot did not become IDLE after connect")

    log("Robot ready")
    return robot


def create_project(sdk: Sn3dSdkClient, project_name: str) -> None:
    log(f"Creating project: {project_name}")
    sdk.send_command(
        Sn3dCommandFactory.create_solution(
            sln_dir_path=PROJECT_ROOT,
            sln_name=project_name,
            work_range=1,
            need_limit=2,
        )
    )

    if REAPPLY_PARAMS_EACH_CYCLE:
        log("Reapplying scanner parameters after project creation")
        apply_scanner_parameters(sdk)


def run_scan(sdk: Sn3dSdkClient, scan_index: int, point: dict) -> None:
    log(
        f"Scan #{scan_index}: "
        f"idx={point.get('index')} "
        f"type={point.get('point_type')} "
        f"comment={point.get('comment', '')}"
    )
    sdk.send_command(Sn3dCommandFactory.start_scan())
    log(f"Scan #{scan_index} completed")


def generate_mesh_and_save(sdk: Sn3dSdkClient, project_name: str) -> None:
    export_dir = Path(EXPORT_ROOT) / project_name
    export_dir.mkdir(parents=True, exist_ok=True)

    if RUN_GLOBAL_OPT:
        log("Running global optimization...")
        sdk.send_command(Sn3dCommandFactory.global_optimization())

    log("Generating mesh...")
    sdk.send_command(
        Sn3dCommandFactory.mesh(
            mesh_type=0,
            unwatertight_detail=0,
            depth=0,
            filter_level=1,
            smooth_level=1,
            remove_small=1,
            max_face=True,
            face_limit=20_000_000,
            fill_small_hole=True,
            small_hole_perimeter=10,
            neighbourhood=3,
            spike_sensitivity=True,
            fill_marker_hole=True,
            border_opt=True,
            need_thin_obj_mesh=False,
        )
    )

    save_path = export_dir / f"{project_name}.stl"

    log(f"Saving data: {save_path}")
    sdk.send_command(
        Sn3dCommandFactory.save_data(
            save_type=SAVE_TYPE,
            save_path=str(save_path),
            name=save_path.name,
        )
    )

    log("Mesh and save completed")


def is_home_point(point: dict) -> bool:
    point_type = str(point.get("point_type", "")).strip().lower()
    comment = str(point.get("comment", "")).strip().lower()
    return point_type == "home" or comment == "home" or comment.startswith("home")


def is_end_point(point: dict) -> bool:
    point_type = str(point.get("point_type", "")).strip().lower()
    comment = str(point.get("comment", "")).strip().lower()
    return point_type == "end" or comment == "end" or comment.startswith("end")


def get_end_index(points: list[dict]) -> int:
    end_indexes = [i for i, point in enumerate(points) if is_end_point(point)]
    if not end_indexes:
        raise RuntimeError("End point not found in trajectory")
    return end_indexes[-1]


def move_robot_to_point(robot: KukaEkiPathClient, list_index: int, point: dict) -> None:
    log(
        f"Move to point list={list_index} "
        f"idx={point.get('index')} "
        f"type={point.get('point_type')} "
        f"comment={point.get('comment', '')}"
    )

    if not robot.wait_until_status(robot.STATUS_IDLE):
        raise RuntimeError("Robot is not IDLE before move command")

    if not robot.trigger_point_by_list_index(list_index):
        raise RuntimeError(f"Failed to trigger point {list_index}")

    if not robot.wait_motion_done():
        raise RuntimeError(f"Robot motion failed at point {list_index}")

    log(f"Reached point idx={point.get('index')}, settle {SETTLE_SEC:.1f}s")
    time.sleep(SETTLE_SEC)


def run_cycle(robot: KukaEkiPathClient, sdk: Sn3dSdkClient) -> None:
    points = robot.points
    end_index = get_end_index(points)
    project_name = datetime.now().strftime("scan_%Y%m%d_%H%M%S")

    create_project(sdk, project_name)

    scan_index = 0

    for list_index, point in enumerate(points):
        point_idx = point.get("index", list_index)
        point_type = str(point.get("point_type", "")).strip().lower()
        point_comment = str(point.get("comment", "")).strip()

        if is_home_point(point):
            log(
                f"Point list={list_index} idx={point_idx} "
                f"type={point_type} comment={point_comment} -> HOME skipped"
            )
            continue

        if list_index == end_index:
            log(
                f"Starting END move list={list_index} idx={point_idx} "
                f"type={point_type} comment={point_comment}"
            )

            if not robot.wait_until_status(robot.STATUS_IDLE):
                raise RuntimeError("Robot is not IDLE before END move")

            if not robot.trigger_point_by_list_index(list_index):
                raise RuntimeError("Failed to trigger END point")

            worker_error: dict[str, Exception] = {}

            def mesh_worker() -> None:
                try:
                    generate_mesh_and_save(sdk, project_name)
                except Exception as exc:
                    worker_error["error"] = exc

            worker = threading.Thread(target=mesh_worker, daemon=False)
            worker.start()

            if not robot.wait_motion_done():
                raise RuntimeError("Robot did not finish END motion")

            worker.join()

            if "error" in worker_error:
                raise worker_error["error"]

            log(f"Cycle completed successfully on END point: {project_name}")
            return

        move_robot_to_point(robot, list_index, point)

        if point_type == "scan":
            scan_index += 1
            run_scan(sdk, scan_index, point)
        else:
            log(f"Point idx={point_idx} type={point_type}, scan skipped")

    raise RuntimeError("Cycle ended without END execution")


def main() -> None:
    sdk = None
    watcher = None

    try:
        sdk = connect_scanner()

        watcher = ScanFolderWatcher(SCAN_WATCHER_SETTINGS)
        watcher.start()
        log("Background scan watcher started")

        while True:
            robot = None
            try:
                robot = connect_robot()
                run_cycle(robot, sdk)
                log(f"Restarting next cycle in {RESTART_DELAY_SEC:.1f}s")
                time.sleep(RESTART_DELAY_SEC)

            except KeyboardInterrupt:
                raise

            except Exception as exc:
                log(f"Cycle error: {exc}")
                time.sleep(2.0)

            finally:
                if robot is not None:
                    try:
                        robot.stop()
                        log("Robot connection closed")
                    except Exception as exc:
                        log(f"Robot stop warning: {exc}")

    except KeyboardInterrupt:
        log("Stopped by user")

    finally:
        if watcher is not None:
            try:
                watcher.stop()
                log("Background scan watcher stopped")
            except Exception as exc:
                log(f"Watcher stop warning: {exc}")

        if sdk is not None:
            try:
                sdk.release_sdk()
                log("Scanner SDK released")
            except Exception as exc:
                log(f"Scanner release warning: {exc}")

            try:
                sdk.disconnect()
                log("Scanner disconnected")
            except Exception as exc:
                log(f"Scanner disconnect warning: {exc}")


if __name__ == "__main__":
    main()
