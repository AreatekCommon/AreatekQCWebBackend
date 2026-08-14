import logging

from app.core.log_buffer import log_buffer
from app.core.log_ws_manager import log_ws_manager

WEB_LOG_LEVEL = logging.INFO


class WebStreamLogFilter(logging.Filter):
    """Drop low-level websocket protocol noise from the web log stream."""

    _NOISE_LOGGER_PREFIXES = ("websockets",)
    _NOISE_MESSAGE_PREFIXES = ("> TEXT", "< TEXT", "> BINARY", "< BINARY")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(self._NOISE_LOGGER_PREFIXES):
            return False

        message = record.getMessage()
        return not any(message.startswith(prefix) for prefix in self._NOISE_MESSAGE_PREFIXES)


def configure_web_log_handler(handler: logging.Handler) -> None:
    handler.setLevel(WEB_LOG_LEVEL)
    if not any(isinstance(log_filter, WebStreamLogFilter) for log_filter in handler.filters):
        handler.addFilter(WebStreamLogFilter())


class InMemoryAndWebSocketLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            log_buffer.append(message)
            log_ws_manager.schedule_broadcast(message)
        except Exception:
            self.handleError(record)