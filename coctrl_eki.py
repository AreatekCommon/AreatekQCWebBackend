"""Legacy entrypoint for path execution EKI client."""

from app.eki.path_client import KukaEkiPathClient

__all__ = ["KukaEkiPathClient"]


def main() -> None:
    from app.core.logger import apply_log_level, configure_logging, get_logger

    configure_logging(debug=True)
    apply_log_level("INFO")
    logger = get_logger("coctrl_eki")

    robot_ip = "192.168.0.5"
    robot_port = 54603
    turntable_port = 54601
    trajectories_folder = r"C:\Users\Areatek\Desktop\KUKA TRAJECTORIES"

    client = KukaEkiPathClient(
        robot_ip=robot_ip,
        robot_port=robot_port,
        turntable_port=turntable_port,
        allowed_point_types=None,
    )

    client.turn_connected = True
    client._connect_turntable = lambda: None  # type: ignore[method-assign]

    try:
        client.run_trajectory_from_latest_json(folder=trajectories_folder)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        client.stop()


if __name__ == "__main__":
    main()
