import time

from coctrl_eki import KukaEkiPathClient


if __name__ == "__main__":
    ROBOT_IP = "192.168.0.5"
    FOLDER = r"C:\Users\Areatek\Desktop\Программы"

    json_file = KukaEkiPathClient.find_latest_json(FOLDER)
    print(f"[APP] Using file: {json_file}")

    client = KukaEkiPathClient(
        robot_ip=ROBOT_IP,
        robot_port=54602,
        heartbeat_period=0.2,
        json_path=json_file,
        allowed_point_types=None,   # или ["scan"]
    )

    client.load_points_from_json()
    client.start()

    print("X = run full trajectory")
    print("Q = quit")

    try:
        while True:
            cmd = input("[APP] Enter command: ").strip().upper()

            if cmd == "Q":
                print("[APP] Quit")
                break

            if cmd != "X":
                print("[APP] Unknown command. Use X or Q")
                continue

            print("[APP] Full trajectory start")

            total = len(client.points)
            ok = True

            for i in range(total):
                if client.stop_event.is_set():
                    ok = False
                    break

                client.wait_until_status(client.STATUS_IDLE, timeout=None)

                if not client.trigger_point_by_list_index(i):
                    print(f"[APP] Failed to send point {i}")
                    ok = False
                    break

                client.wait_motion_done(start_timeout=None, finish_timeout=None)

            if ok:
                print("[APP] Full trajectory done")
            else:
                print("[APP] Full trajectory aborted")

            time.sleep(0.1)

    finally:
        client.stop()