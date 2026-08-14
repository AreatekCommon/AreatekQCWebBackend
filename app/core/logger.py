import logging
import sys
from pathlib import Path

from uvicorn.logging import AccessFormatter, DefaultFormatter

from app.core.logging_handler import (
    InMemoryAndWebSocketLogHandler,
    WEB_LOG_LEVEL,
    configure_web_log_handler,
)

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOGGER_CONFIGURED = False
_FILE_HANDLER: logging.FileHandler | None = None
_FILE_HANDLER_PATH: Path | None = None

LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _has_web_handler(logger: logging.Logger) -> bool:
    return any(isinstance(handler, InMemoryAndWebSocketLogHandler) for handler in logger.handlers)


def _sync_web_handlers(*loggers: logging.Logger) -> None:
    for logger in loggers:
        for handler in logger.handlers:
            if isinstance(handler, InMemoryAndWebSocketLogHandler):
                configure_web_log_handler(handler)


def ensure_web_log_handlers() -> None:
    root_logger = logging.getLogger()
    access_logger = logging.getLogger("uvicorn.access")
    uvicorn_logger = logging.getLogger("uvicorn")
    access_logger.setLevel(logging.WARNING)

    _sync_web_handlers(root_logger, access_logger, uvicorn_logger)

    if not _has_web_handler(access_logger):
        access_handler = InMemoryAndWebSocketLogHandler()
        access_handler.setFormatter(
            AccessFormatter(fmt='%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s')
        )
        configure_web_log_handler(access_handler)
        access_logger.addHandler(access_handler)

    if not _has_web_handler(uvicorn_logger):
        default_handler = InMemoryAndWebSocketLogHandler()
        default_handler.setFormatter(DefaultFormatter(fmt="%(levelprefix)s %(message)s"))
        configure_web_log_handler(default_handler)
        uvicorn_logger.addHandler(default_handler)


def apply_log_level(level_name: str) -> None:
    level = LOG_LEVELS.get(level_name.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers:
        if isinstance(handler, InMemoryAndWebSocketLogHandler):
            configure_web_log_handler(handler)
            continue
        handler.setLevel(level)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def apply_file_logging(*, enabled: bool, log_file_path: str, level_name: str = "INFO") -> None:
    global _FILE_HANDLER, _FILE_HANDLER_PATH

    root_logger = logging.getLogger()
    level = LOG_LEVELS.get(level_name.upper(), logging.INFO)

    if _FILE_HANDLER is not None:
        root_logger.removeHandler(_FILE_HANDLER)
        _FILE_HANDLER.close()
        _FILE_HANDLER = None
        _FILE_HANDLER_PATH = None

    if not enabled:
        return

    log_path = Path(log_file_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root_logger.addHandler(file_handler)
    _FILE_HANDLER = file_handler
    _FILE_HANDLER_PATH = log_path


def apply_runtime_logging_settings(
    *,
    log_level: str,
    log_to_file: bool,
    log_file_path: str,
) -> None:
    apply_log_level(log_level)
    apply_file_logging(
        enabled=log_to_file,
        log_file_path=log_file_path,
        level_name=log_level,
    )


def configure_logging(debug: bool = True) -> None:
    global _LOGGER_CONFIGURED

    if _LOGGER_CONFIGURED:
        return

    console_level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(_LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(console_level)
    root_logger.handlers.clear()

    memory_ws_handler = InMemoryAndWebSocketLogHandler()
    memory_ws_handler.setFormatter(formatter)
    configure_web_log_handler(memory_ws_handler)
    root_logger.addHandler(memory_ws_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    ensure_web_log_handlers()

    _LOGGER_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)