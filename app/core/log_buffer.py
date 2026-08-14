from collections import deque
from threading import Lock
from typing import Deque


class LogBuffer:
    def __init__(self, max_lines: int = 500) -> None:
        self._lines: Deque[str] = deque(maxlen=max_lines)
        self._lock = Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def get_lines(self, limit: int | None = None) -> list[str]:
        with self._lock:
            lines = list(self._lines)

        if limit is None or limit >= len(lines):
            return lines
        return lines[-limit:]


log_buffer = LogBuffer()