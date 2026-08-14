from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.logging_handler import InMemoryAndWebSocketLogHandler


@dataclass(frozen=True)
class LoggerSettings:
    level: int = logging.INFO
    log_to_console: bool = True
    log_to_file: bool = False
    log_file_path: str = "logs/application.log"
    file_mode: str = "a"


class AppLogger:
    """
    Единая конфигурация логирования для проекта.

    Все именованные логгеры, полученные через get_logger(...),
    будут писать через root logger и его handlers:
    - в память для web log widget,
    - в консоль,
    - в файл.
    """

    _FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    _configured = False

    @classmethod
    def configure(cls, settings: LoggerSettings | None = None) -> logging.Logger:
        if cls._configured:
            return logging.getLogger()

        settings = settings or LoggerSettings()

        formatter = logging.Formatter(cls._FORMAT)

        root_logger = logging.getLogger()
        root_logger.setLevel(settings.level)
        root_logger.handlers.clear()

        memory_ws_handler = InMemoryAndWebSocketLogHandler()
        memory_ws_handler.setLevel(settings.level)
        memory_ws_handler.setFormatter(formatter)
        root_logger.addHandler(memory_ws_handler)

        if settings.log_to_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(settings.level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        if settings.log_to_file:
            log_path = Path(settings.log_file_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(
                log_path,
                mode=settings.file_mode,
                encoding="utf-8",
            )
            file_handler.setLevel(settings.level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

        if not root_logger.handlers:
            raise ValueError("At least one logging target must be enabled: console and/or file")

        for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(logger_name)
            logger.setLevel(settings.level)
            logger.propagate = True

        cls._configured = True
        root_logger.debug("Logger configured: %s", settings)
        return root_logger

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.propagate = True
        return logger