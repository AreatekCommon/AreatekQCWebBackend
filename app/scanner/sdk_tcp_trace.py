from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

SDK_TCP_LOGGER_NAME = "app.sdk_tcp"
_TRACE_FORMAT = "%(asctime)s | %(message)s"
_file_handler: logging.FileHandler | None = None
_console_handler: logging.StreamHandler | None = None
_configured_log_path: Path | None = None
_configured_console: bool | None = None


def get_sdk_tcp_logger() -> logging.Logger:
    trace_logger = logging.getLogger(SDK_TCP_LOGGER_NAME)
    trace_logger.propagate = False
    return trace_logger


def configure_sdk_trace_logging(
    *,
    enabled: bool,
    log_dir: str,
    log_to_console: bool = False,
) -> None:
    global _file_handler, _console_handler, _configured_log_path, _configured_console

    trace_logger = get_sdk_tcp_logger()
    trace_logger.setLevel(logging.INFO)

    if not enabled:
        if _file_handler is not None:
            trace_logger.removeHandler(_file_handler)
            _file_handler.close()
            _file_handler = None
        if _console_handler is not None:
            trace_logger.removeHandler(_console_handler)
            _console_handler = None
        _configured_log_path = None
        _configured_console = None
        return

    tcp_dir = Path(log_dir) / "sdk_tcp"
    tcp_dir.mkdir(parents=True, exist_ok=True)
    log_path = tcp_dir / "sdk_tcp.log"

    if _file_handler is None or _configured_log_path != log_path:
        if _file_handler is not None:
            trace_logger.removeHandler(_file_handler)
            _file_handler.close()
        _file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        _file_handler.setFormatter(logging.Formatter(_TRACE_FORMAT))
        trace_logger.addHandler(_file_handler)
        _configured_log_path = log_path

    if log_to_console and _console_handler is None:
        _console_handler = logging.StreamHandler(sys.stdout)
        _console_handler.setFormatter(logging.Formatter(_TRACE_FORMAT))
        trace_logger.addHandler(_console_handler)
        _configured_console = True
    elif not log_to_console and _console_handler is not None:
        trace_logger.removeHandler(_console_handler)
        _console_handler = None
        _configured_console = False


def log_sdk_trace(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    get_sdk_tcp_logger().info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
