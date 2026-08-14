from __future__ import annotations

from copy import deepcopy
from typing import Any

from uvicorn.config import LOGGING_CONFIG


def build_uvicorn_log_config() -> dict[str, Any]:
    config = deepcopy(LOGGING_CONFIG)

    config["handlers"]["web_access"] = {
        "()": "app.core.logging_handler.InMemoryAndWebSocketLogHandler",
        "formatter": "access",
        "level": "DEBUG",
    }
    config["handlers"]["web_default"] = {
        "()": "app.core.logging_handler.InMemoryAndWebSocketLogHandler",
        "formatter": "default",
        "level": "INFO",
    }

    config["loggers"]["uvicorn"]["handlers"] = ["default", "web_default"]
    config["loggers"]["uvicorn"]["propagate"] = False

    config["loggers"]["uvicorn.access"]["handlers"] = ["access", "web_access"]
    config["loggers"]["uvicorn.access"]["level"] = "WARNING"
    config["loggers"]["uvicorn.access"]["propagate"] = False

    return config
