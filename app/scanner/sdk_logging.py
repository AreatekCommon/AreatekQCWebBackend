from __future__ import annotations

from app.models.runtime_settings import RuntimeSettings
from app.scanner.sdk_log_collector import sdk_log_collector
from app.scanner.sdk_tcp_trace import configure_sdk_trace_logging


def apply_sdk_logging(settings: RuntimeSettings, *, restart_native_mirror: bool = False) -> None:
    configure_sdk_trace_logging(
        enabled=settings.sdk_log_enabled,
        log_dir=settings.sdk_log_dir,
        log_to_console=settings.sdk_tcp_log_to_console,
    )

    if not restart_native_mirror:
        return

    if settings.sdk_log_enabled:
        sdk_log_collector.start(settings)
    else:
        sdk_log_collector.stop()
