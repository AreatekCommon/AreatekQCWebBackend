from __future__ import annotations

from app.axis import AxisReceiver, ReceiverSettings


def run_demo_main() -> None:
    from app.core.logger import configure_logging, get_logger

    configure_logging(debug=True)
    logger = get_logger("axis_receiver_demo")
    logger.info("Starting AxisReceiver demo main")

    receiver = AxisReceiver(
        ReceiverSettings(
            host="192.168.0.5",
            port=54600,
            connect_timeout_s=5.0,
            receive_timeout_s=1.0,
            reconnect_delay_s=2.0,
            send_ready_on_connect=True,
            ready_value=True,
            tcp_no_delay=True,
        )
    )

    try:
        receiver.run_demo_forever()
    finally:
        receiver.close()
        logger.info("AxisReceiver demo main finished")


if __name__ == "__main__":
    run_demo_main()
