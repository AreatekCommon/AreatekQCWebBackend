from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any


@dataclass
class AppState:
    started_at: datetime | None = None
    is_running: bool = False
    status: str = "starting"
    last_error: str | None = None
    connected_web_clients: int = 0
    ui_locale: str = "ru"
    is_shutting_down: bool = False
    current_position: dict[str, Any] = field(default_factory=dict)
    last_logs: list[str] = field(default_factory=list)

    def mark_started(self) -> None:
        self.started_at = datetime.now(UTC)
        self.is_running = True
        self.status = "running"
        self.last_error = None

    def mark_stopped(self) -> None:
        self.is_running = False
        self.status = "stopped"

    def mark_error(self, message: str) -> None:
        self.last_error = message
        self.status = "error"

    def add_log(self, message: str) -> None:
        self.last_logs.append(message)
        if len(self.last_logs) > 100:
            self.last_logs.pop(0)


app_state = AppState()