from __future__ import annotations

import json
import shutil
import socket
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class ProtocolError(Exception):
    pass


@dataclass(slots=True)
class TcpProtocolConfig:
    host: str = "192.168.0.10"
    port: int = 55555
    encoding: str = "utf-8"
    timeout_sec: float = 100.0
    scan_count: int = 2
    max_payload_len: int = 0xFF

    source_scan_dir: str = r"C:\Users\Areatek\Desktop\RVScans\NewestScans"
    archive_root_dir: str = r"C:\Users\Areatek\Desktop\RVScans"

    scan_wait_timeout_sec: float = 300.0
    fs_poll_interval_sec: float = 0.5
    fs_quiet_period_sec: float = 2.0
    recursive_watch: bool = True

    model_file_prefix: str = "Model_"
    wait_for_enter_between_scans: bool = True

class JsonHexFrameProtocol:
    def __init__(self, encoding: str = "utf-8", max_payload_len: int = 0xFF) -> None:
        self.encoding = encoding
        self.max_payload_len = max_payload_len

    def encode(self, message: Dict[str, Any]) -> bytes:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode(self.encoding)
        if len(payload) > self.max_payload_len:
            raise ValueError(f"Payload too large: {len(payload)} bytes, max={self.max_payload_len}")
        header = f"{len(payload):02x}".encode("ascii")
        return header + payload

    def send(self, sock: socket.socket, message: Dict[str, Any]) -> None:
        sock.sendall(self.encode(message))

    def receive(self, sock: socket.socket) -> Dict[str, Any]:
        header = self._recv_exact(sock, 2)
        try:
            payload_len = int(header.decode("ascii"), 16)
        except ValueError as exc:
            raise ProtocolError(f"Invalid hex header: {header!r}") from exc

        payload = self._recv_exact(sock, payload_len)
        try:
            return json.loads(payload.decode(self.encoding))
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"Invalid JSON payload: {payload!r}") from exc

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("Socket closed while receiving data")
            data.extend(chunk)
        return bytes(data)


class ScanDirectoryMonitor:
    def __init__(self, config: TcpProtocolConfig) -> None:
        self.config = config
        self.source_dir = Path(config.source_scan_dir)
        self.archive_root_dir = Path(config.archive_root_dir)

    def validate_directories(self) -> None:
        if not self.source_dir.exists():
            raise FileNotFoundError(f"Source scan directory not found: {self.source_dir}")
        if not self.source_dir.is_dir():
            raise NotADirectoryError(f"Source scan path is not a directory: {self.source_dir}")
        self.archive_root_dir.mkdir(parents=True, exist_ok=True)

    def create_series_dir(self) -> Path:
        series_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        series_dir = self.archive_root_dir / series_name
        series_dir.mkdir(parents=True, exist_ok=True)
        return series_dir

    def snapshot(self) -> Dict[Path, tuple[int, int]]:
        files = self._list_files()
        result: Dict[Path, tuple[int, int]] = {}
        for file_path in files:
            try:
                stat = file_path.stat()
                result[file_path] = (stat.st_size, stat.st_mtime_ns)
            except FileNotFoundError:
                continue
        return result

    def wait_for_model_result(
            self,
            baseline_snapshot: Dict[Path, tuple[int, int]],
    ) -> tuple[list[Path], Dict[Path, tuple[int, int]]]:
        last_activity_at: Optional[float] = None
        tracked: Dict[Path, tuple[int, int]] = {}
        previous_snapshot = baseline_snapshot

        print(f"[FS] Waiting for model files in: {self.source_dir}")

        while True:
            current_snapshot = self.snapshot()

            activity_delta = self._diff_new_or_modified(previous_snapshot, current_snapshot)
            model_activity = {
                path: meta
                for path, meta in activity_delta.items()
                if path.name.startswith(self.config.model_file_prefix)
            }
            if model_activity:
                last_activity_at = time.monotonic()

            baseline_delta = self._diff_new_or_modified(baseline_snapshot, current_snapshot)
            tracked.update(
                {
                    path: meta
                    for path, meta in baseline_delta.items()
                    if path.name.startswith(self.config.model_file_prefix)
                }
            )

            if tracked:
                quiet_ok = (
                        last_activity_at is not None
                        and (time.monotonic() - last_activity_at) >= self.config.fs_quiet_period_sec
                )
                if quiet_ok:
                    files = sorted(tracked.keys())
                    print(f"[FS] Model completed, found files: {len(files)}")
                    for f in files:
                        print(f"[FS]   + {f}")
                    return files, current_snapshot

            previous_snapshot = current_snapshot
            time.sleep(self.config.fs_poll_interval_sec)

    def wait_for_scan_result(
        self,
        baseline_snapshot: Dict[Path, tuple[int, int]],
        scan_index: int,
    ) -> tuple[list[Path], Dict[Path, tuple[int, int]]]:
        started_at = time.monotonic()
        last_activity_at: Optional[float] = None
        tracked: Dict[Path, tuple[int, int]] = {}
        previous_snapshot = baseline_snapshot

        print(f"[FS] Waiting for scan #{scan_index} files in: {self.source_dir}")

        while time.monotonic() - started_at <= self.config.scan_wait_timeout_sec:
            current_snapshot = self.snapshot()

            activity_delta = self._diff_new_or_modified(previous_snapshot, current_snapshot)
            if activity_delta:
                last_activity_at = time.monotonic()

            tracked.update(self._diff_new_or_modified(baseline_snapshot, current_snapshot))

            if tracked:
                quiet_ok = (
                    last_activity_at is not None
                    and (time.monotonic() - last_activity_at) >= self.config.fs_quiet_period_sec
                )
                if quiet_ok:
                    files = sorted(tracked.keys())
                    print(f"[FS] Scan #{scan_index} completed, found files: {len(files)}")
                    for f in files:
                        print(f"[FS]   + {f}")
                    return files, current_snapshot

            previous_snapshot = current_snapshot
            time.sleep(self.config.fs_poll_interval_sec)

        raise TimeoutError(
            f"Timeout waiting for scan #{scan_index} data in directory: {self.source_dir}"
        )

    def move_model_files_to_series(
            self,
            files: list[Path],
            series_dir: Path,
    ) -> None:
        model_dir = series_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)

        unique_files = list(dict.fromkeys(files))
        print(f"[FS] Moving {len(unique_files)} model files to: {model_dir}")

        for src in unique_files:
            if not src.exists():
                print(f"[FS] Skipped missing model file: {src}")
                continue

            rel_path = src.relative_to(self.source_dir)
            dst = model_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst = self._make_unique_path(dst)

            print(f"[FS] MOVE {src} -> {dst}")
            shutil.move(str(src), str(dst))

    def move_scan_files_to_series(
        self,
        files: list[Path],
        series_dir: Path,
        scan_index: int,
    ) -> None:
        scan_dir = series_dir / f"scan_{scan_index:02d}"
        scan_dir.mkdir(parents=True, exist_ok=True)

        unique_files = list(dict.fromkeys(files))
        print(f"[FS] Moving {len(unique_files)} files to: {scan_dir}")

        for src in unique_files:
            if not src.exists():
                print(f"[FS] Skipped missing file: {src}")
                continue

            rel_path = src.relative_to(self.source_dir)
            dst = scan_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst = self._make_unique_path(dst)

            print(f"[FS] MOVE {src} -> {dst}")
            shutil.move(str(src), str(dst))

    def _list_files(self) -> list[Path]:
        if self.config.recursive_watch:
            return [p for p in self.source_dir.rglob("*") if p.is_file()]
        return [p for p in self.source_dir.glob("*") if p.is_file()]

    @staticmethod
    def _diff_new_or_modified(
        old_snapshot: Dict[Path, tuple[int, int]],
        new_snapshot: Dict[Path, tuple[int, int]],
    ) -> Dict[Path, tuple[int, int]]:
        delta: Dict[Path, tuple[int, int]] = {}
        for path, meta in new_snapshot.items():
            if path not in old_snapshot or old_snapshot[path] != meta:
                delta[path] = meta
        return delta

    @staticmethod
    def _make_unique_path(path: Path) -> Path:
        if not path.exists():
            return path

        counter = 1
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1


class ControlSoftwareServer:
    def __init__(self, config: TcpProtocolConfig) -> None:
        self.config = config
        self.protocol = JsonHexFrameProtocol(
            encoding=config.encoding,
            max_payload_len=config.max_payload_len,
        )
        self.monitor = ScanDirectoryMonitor(config)
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._client_address: Optional[tuple[str, int]] = None

    def wait_for_operator_next_scan(self, completed_scan_index: int) -> None:
        if not self.config.wait_for_enter_between_scans:
            return

        if completed_scan_index >= self.config.scan_count:
            return

        input(
            f"[SERVER] Scan {completed_scan_index}/{self.config.scan_count} saved. "
            f"Press Enter to start next scan..."
        )

    def start(self) -> None:
        self.monitor.validate_directories()

        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(self.config.timeout_sec)
        self._server_socket.bind((self.config.host, self.config.port))
        self._server_socket.listen(1)

        print(f"[SERVER] Listening on {self.config.host}:{self.config.port}")

    def accept_client(self) -> None:
        if self._server_socket is None:
            raise RuntimeError("Server is not started")

        self._client_socket, self._client_address = self._server_socket.accept()

        # После подключения реального клиента ждем его ответы бесконечно
        self._client_socket.settimeout(None)

        print(f"[SERVER] Client connected: {self._client_address}")

    def run_scan_session(self) -> None:
        self._ensure_client()

        start_msg = self.receive_message()
        self._expect_command(start_msg, "script_starting")
        print("[SERVER] Client is ready")

        series_dir = self.monitor.create_series_dir()
        print(f"[SERVER] Series directory created: {series_dir}")

        baseline_snapshot = self.monitor.snapshot()

        self.send_command("clear_tree")
        self.wait_for_success("clear_tree")

        baseline_snapshot = self.monitor.snapshot()

        for scan_index in range(1, self.config.scan_count + 1):
            self.send_command("start_scanning")
            print(f"[SERVER] Scan {scan_index}/{self.config.scan_count} started")

            new_files, _ = self.monitor.wait_for_scan_result(
                baseline_snapshot=baseline_snapshot,
                scan_index=scan_index,
            )

            self.monitor.move_scan_files_to_series(
                files=new_files,
                series_dir=series_dir,
                scan_index=scan_index,
            )

            baseline_snapshot = self.monitor.snapshot()
            self.wait_for_operator_next_scan(scan_index)

        self.send_command("generate_model")
        self.wait_for_success("generate_model")

        model_files, _ = self.monitor.wait_for_model_result(
            baseline_snapshot=baseline_snapshot
        )

        self.monitor.move_model_files_to_series(
            files=model_files,
            series_dir=series_dir,
        )

        baseline_snapshot = self.monitor.snapshot()

        self.send_command("clear_tree")
        self.wait_for_success("clear_tree")

        print("[SERVER] Scan session completed")
        print(f"[SERVER] All scans and model exported to: {series_dir}")

    def wait_for_success(self, action_name: str) -> None:
        msg = self.receive_message()
        command = msg.get("command")

        if command == "successful":
            print(f"[SERVER] Action '{action_name}' finished successfully")
            return

        if command == "error_occurred":
            description = msg.get("description", "Error")
            raise ProtocolError(f"3D Studio error on '{action_name}': {description}")

        raise ProtocolError(f"Unexpected response for '{action_name}': {msg}")

    def wait_for_model_result(
            self,
            baseline_snapshot: Dict[Path, tuple[int, int]],
    ) -> tuple[list[Path], Dict[Path, tuple[int, int]]]:
        started_at = time.monotonic()
        last_activity_at: Optional[float] = None
        tracked: Dict[Path, tuple[int, int]] = {}
        previous_snapshot = baseline_snapshot

        print(f"[FS] Waiting for model files in: {self.source_dir}")

        while True:
            current_snapshot = self.snapshot()

            activity_delta = self._diff_new_or_modified(previous_snapshot, current_snapshot)
            model_activity = {
                path: meta
                for path, meta in activity_delta.items()
                if path.name.startswith(self.config.model_file_prefix)
            }
            if model_activity:
                last_activity_at = time.monotonic()

            baseline_delta = self._diff_new_or_modified(baseline_snapshot, current_snapshot)
            tracked.update(
                {
                    path: meta
                    for path, meta in baseline_delta.items()
                    if path.name.startswith(self.config.model_file_prefix)
                }
            )

            if tracked:
                quiet_ok = (
                        last_activity_at is not None
                        and (time.monotonic() - last_activity_at) >= self.config.fs_quiet_period_sec
                )
                if quiet_ok:
                    files = sorted(tracked.keys())
                    print(f"[FS] Model completed, found files: {len(files)}")
                    for f in files:
                        print(f"[FS]   + {f}")
                    return files, current_snapshot

            previous_snapshot = current_snapshot
            time.sleep(self.config.fs_poll_interval_sec)

    def move_model_files_to_series(
            self,
            files: list[Path],
            series_dir: Path,
    ) -> None:
        model_dir = series_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)

        unique_files = list(dict.fromkeys(files))
        print(f"[FS] Moving {len(unique_files)} model files to: {model_dir}")

        for src in unique_files:
            if not src.exists():
                print(f"[FS] Skipped missing model file: {src}")
                continue

            rel_path = src.relative_to(self.source_dir)
            dst = model_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst = self._make_unique_path(dst)

            print(f"[FS] MOVE {src} -> {dst}")
            shutil.move(str(src), str(dst))

    def send_command(self, command: str, **extra_fields: Any) -> None:
        self._ensure_client()
        message = {"command": command, **extra_fields}
        self.protocol.send(self._client_socket, message)
        print(f"[SERVER] --> {message}")

    def receive_message(self) -> Dict[str, Any]:
        self._ensure_client()
        message = self.protocol.receive(self._client_socket)
        print(f"[SERVER] <-- {message}")
        return message

    @staticmethod
    def _expect_command(message: Dict[str, Any], expected: str) -> None:
        actual = message.get("command")
        if actual != expected:
            raise ProtocolError(f"Expected command '{expected}', got '{actual}'")

    def _ensure_client(self) -> None:
        if self._client_socket is None:
            raise RuntimeError("Client is not connected")

    def close(self) -> None:
        for sock in (self._client_socket, self._server_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._client_socket = None
        self._server_socket = None
        self._client_address = None


def main() -> None:
    config = TcpProtocolConfig()
    server = ControlSoftwareServer(config)

    try:
        server.start()
        print("[SERVER] Waiting for real 3D Studio connection...")
        server.accept_client()
        server.run_scan_session()
    finally:
        server.close()


if __name__ == "__main__":
    main()