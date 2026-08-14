"""
EKI reconnect stress-tester
Python = TCP client
KUKA EKI = TCP server on 54601

Тестер:
- подключается к KUKA
- читает RobotStatus
- отправляет корректный ClientCommand под текущий XML
- умеет симулировать FIN / RST / stop-reading / repeated reconnects
"""

import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET
from enum import Enum, auto
from typing import Optional


ROBOT_IP = "192.168.0.5"
ROBOT_PORT = 54601
ENCODING = "utf-8"
BUFFER_SIZE = 4096

CONNECT_TIMEOUT_SEC = 10.0
SOCKET_TIMEOUT_SEC = 1.0

HOLD_SECONDS = 3.0
RECONNECT_PAUSE_SEC = 4.0
FAST_RECONNECT_DELAY_SEC = 0.3

HEARTBEAT_INTERVAL_SEC = 0.5


class Scenario(Enum):
    NORMAL_RECEIVE = auto()
    CLIENT_CLOSE_GRACEFUL = auto()
    CLIENT_CLOSE_RST = auto()
    RECONNECT_FAST = auto()
    RECONNECT_SLOW = auto()
    CLIENT_STOP_READING = auto()
    REPEATED_DISCONNECTS = auto()


class Session:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.stop_event = threading.Event()
        self.tx_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

        self.cmd = 0
        self.value = 0
        self.ack_status = 0
        self.ack_scan = 0
        self.alive = True

        self.sent_count = 0

    def start_heartbeat(self) -> None:
        self.tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self.tx_thread.start()

    def stop_heartbeat(self) -> None:
        self.stop_event.set()
        if self.tx_thread is not None:
            self.tx_thread.join(timeout=1.0)

    def update_from_robot_status(self, status_msg: dict) -> None:
        with self.lock:
            self.ack_status = int(status_msg.get("Status", 0) or 0)
            self.ack_scan = int(status_msg.get("CurrentScan", 0) or 0)

    def set_command(self, cmd: int, value: int = 0) -> None:
        with self.lock:
            self.cmd = int(cmd)
            self.value = int(value)

    def set_alive(self, alive: bool) -> None:
        with self.lock:
            self.alive = bool(alive)

    def build_client_command_xml(self) -> str:
        with self.lock:
            cmd = self.cmd
            value = self.value
            ack_status = self.ack_status
            ack_scan = self.ack_scan
            alive = self.alive

        alive_text = "true" if alive else "false"

        return (
            "<ClientCommand>"
            f"<Cmd>{cmd}</Cmd>"
            f"<Value>{value}</Value>"
            f"<AckStatus>{ack_status}</AckStatus>"
            f"<AckScan>{ack_scan}</AckScan>"
            f"<Alive>{alive_text}</Alive>"
            "</ClientCommand>"
        )

    def send_client_command_once(self) -> None:
        payload = self.build_client_command_xml().encode(ENCODING)
        self.sock.sendall(payload)
        self.sent_count += 1

    def _tx_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.send_client_command_once()
            except OSError:
                break
            time.sleep(HEARTBEAT_INTERVAL_SEC)


def connect_to_robot() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT_SEC)
    sock.connect((ROBOT_IP, ROBOT_PORT))
    sock.settimeout(SOCKET_TIMEOUT_SEC)
    print(f"  [CLI] Connected to {ROBOT_IP}:{ROBOT_PORT}")
    return sock


def open_session() -> Session:
    sock = connect_to_robot()
    session = Session(sock)
    session.start_heartbeat()
    return session


def close_graceful(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def close_rst(sock: socket.socket) -> None:
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def close_session_graceful(session: Session) -> None:
    session.stop_heartbeat()
    close_graceful(session.sock)


def close_session_rst(session: Session) -> None:
    session.stop_heartbeat()
    close_rst(session.sock)


def extract_robot_status_messages(buffer: str) -> tuple[list[dict], str]:
    messages: list[dict] = []

    while True:
        start = buffer.find("<RobotStatus>")
        end = buffer.find("</RobotStatus>")

        if start == -1 or end == -1 or end < start:
            break

        end_pos = end + len("</RobotStatus>")
        xml_chunk = buffer[start:end_pos]

        try:
            root = ET.fromstring(xml_chunk)
        except ET.ParseError:
            break

        msg = {child.tag: child.text for child in root}
        messages.append(msg)
        buffer = buffer[end_pos:]

    return messages, buffer


def drain_loop(session: Session, seconds: float, label: str = "") -> int:
    deadline = time.monotonic() + seconds
    rx_buffer = ""
    count = 0

    while time.monotonic() < deadline:
        try:
            chunk = session.sock.recv(BUFFER_SIZE)
            if not chunk:
                print(f"  [CLI]{label} Robot closed connection")
                return count

            rx_buffer += chunk.decode(ENCODING, errors="replace")
            messages, rx_buffer = extract_robot_status_messages(rx_buffer)

            for msg in messages:
                count += 1
                session.update_from_robot_status(msg)
                print(f"  [CLI]{label} RX #{count}: {msg}")

        except socket.timeout:
            pass
        except OSError as exc:
            print(f"  [CLI]{label} Read error: {exc}")
            return count

    return count


def wait_reconnect(label: str = "", hold: float = HOLD_SECONDS) -> None:
    print(f"  [CLI] Wait {RECONNECT_PAUSE_SEC} s before reconnect...")
    time.sleep(RECONNECT_PAUSE_SEC)

    try:
        session = open_session()
        n = drain_loop(session, hold, f" [{label}]")
        print(f"  [CLI] Reconnected OK, packets received: {n}, heartbeats sent: {session.sent_count}")
        close_session_graceful(session)
    except (OSError, TimeoutError) as exc:
        print(f"  [CLI] Reconnect failed: {exc}")


def run_normal_receive() -> None:
    print(f"\n[SCENARIO] NORMAL_RECEIVE — read for {HOLD_SECONDS} s, then FIN")
    session = open_session()
    n = drain_loop(session, HOLD_SECONDS)
    print(f"  [CLI] Received packets: {n}, heartbeats sent: {session.sent_count}")
    close_session_graceful(session)
    wait_reconnect("after NORMAL")


def run_client_close_graceful() -> None:
    print(f"\n[SCENARIO] CLIENT_CLOSE_GRACEFUL — FIN after {HOLD_SECONDS} s")
    session = open_session()
    n = drain_loop(session, HOLD_SECONDS, " [graceful]")
    print(f"  [CLI] Received packets: {n}, sending FIN")
    close_session_graceful(session)
    wait_reconnect("after GRACEFUL")


def run_client_close_rst() -> None:
    print(f"\n[SCENARIO] CLIENT_CLOSE_RST — RST after {HOLD_SECONDS} s")
    session = open_session()
    n = drain_loop(session, HOLD_SECONDS, " [rst]")
    print(f"  [CLI] Received packets: {n}, sending RST")
    close_session_rst(session)
    wait_reconnect("after RST")


def run_reconnect_fast() -> None:
    print(f"\n[SCENARIO] RECONNECT_FAST — RST and immediate reconnect")
    session = open_session()
    n = drain_loop(session, HOLD_SECONDS, " [fast]")
    print(f"  [CLI] Received packets before break: {n}")
    close_session_rst(session)

    print(f"  [CLI] Fast reconnect after {FAST_RECONNECT_DELAY_SEC} s")
    time.sleep(FAST_RECONNECT_DELAY_SEC)

    try:
        session2 = open_session()
        n2 = drain_loop(session2, HOLD_SECONDS, " [fast-reconnect]")
        print(f"  [CLI] Received after fast reconnect: {n2}, heartbeats sent: {session2.sent_count}")
        close_session_graceful(session2)
    except (OSError, TimeoutError) as exc:
        print(f"  [CLI] Fast reconnect failed: {exc}")


def run_reconnect_slow() -> None:
    pause = 8.0
    print(f"\n[SCENARIO] RECONNECT_SLOW — RST, wait {pause} s")
    session = open_session()
    n = drain_loop(session, HOLD_SECONDS, " [slow]")
    print(f"  [CLI] Received packets before break: {n}")
    close_session_rst(session)

    print(f"  [CLI] Waiting {pause} s...")
    time.sleep(pause)

    try:
        session2 = open_session()
        n2 = drain_loop(session2, HOLD_SECONDS, " [slow-reconnect]")
        print(f"  [CLI] Received after slow reconnect: {n2}, heartbeats sent: {session2.sent_count}")
        close_session_graceful(session2)
    except (OSError, TimeoutError) as exc:
        print(f"  [CLI] Slow reconnect failed: {exc}")


def run_client_stop_reading() -> None:
    silent = 12.0
    print(f"\n[SCENARIO] CLIENT_STOP_READING — connect, do not read for {silent} s")
    session = open_session()
    print("  [CLI] Heartbeat TX keeps running, RX paused intentionally...")
    time.sleep(silent)
    print(f"  [CLI] Heartbeats sent while silent: {session.sent_count}")
    print("  [CLI] Closing stalled socket with RST")
    close_session_rst(session)
    wait_reconnect("after STOP_READING")


def run_repeated_disconnects() -> None:
    repeat = 5
    print(f"\n[SCENARIO] REPEATED_DISCONNECTS — {repeat} immediate RST breaks")

    for i in range(1, repeat + 1):
        try:
            session = open_session()
            time.sleep(0.3)
            print(f"  [CLI] Iteration {i}/{repeat}: RST")
            close_session_rst(session)
            time.sleep(0.5)
        except (OSError, TimeoutError) as exc:
            print(f"  [CLI] Iteration {i}: connect failed — {exc}")

    print("  [CLI] Final normal reconnect")
    wait_reconnect("after REPEATED", hold=HOLD_SECONDS)


SCENARIO_MAP = {
    "1": (Scenario.NORMAL_RECEIVE, run_normal_receive),
    "2": (Scenario.CLIENT_CLOSE_GRACEFUL, run_client_close_graceful),
    "3": (Scenario.CLIENT_CLOSE_RST, run_client_close_rst),
    "4": (Scenario.RECONNECT_FAST, run_reconnect_fast),
    "5": (Scenario.RECONNECT_SLOW, run_reconnect_slow),
    "6": (Scenario.CLIENT_STOP_READING, run_client_stop_reading),
    "7": (Scenario.REPEATED_DISCONNECTS, run_repeated_disconnects),
}


def print_menu() -> None:
    print("\n" + "=" * 64)
    print("  EKI Reconnect Tester  (Python = client, KUKA = server)")
    print(f"  Robot: {ROBOT_IP}:{ROBOT_PORT}")
    print("=" * 64)
    for key, (scenario, _) in SCENARIO_MAP.items():
        print(f"  {key}. {scenario.name}")
    print("  a. Run ALL scenarios")
    print("  q. Quit")
    print("=" * 64)


def main() -> None:
    while True:
        print_menu()
        choice = input("Select scenario: ").strip().lower()

        if choice == "q":
            break
        elif choice == "a":
            for key in sorted(SCENARIO_MAP.keys()):
                _, fn = SCENARIO_MAP[key]
                try:
                    fn()
                except Exception as exc:
                    print(f"  [ERR] Scenario crashed: {exc}")
                time.sleep(1.0)
            print("\n[DONE] All scenarios completed.")
        elif choice in SCENARIO_MAP:
            _, fn = SCENARIO_MAP[choice]
            try:
                fn()
            except Exception as exc:
                print(f"  [ERR] {exc}")
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()