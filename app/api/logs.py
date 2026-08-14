from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.log_buffer import log_buffer
from app.core.log_ws_manager import log_ws_manager
from app.core.runtime_settings_store import get_runtime_settings
from app.models.logs import LogSourceInfo, LogSourcesResponse, LogsResponse

router = APIRouter(tags=["logs"])


def _describe_log_file(source_id: str, path: Path) -> LogSourceInfo:
    if not path.exists():
        return LogSourceInfo(id=source_id, path=str(path).replace("\\", "/"), exists=False)

    stat = path.stat()
    return LogSourceInfo(
        id=source_id,
        path=str(path).replace("\\", "/"),
        exists=True,
        size_bytes=stat.st_size,
        modified_at=stat.st_mtime,
    )


def _latest_native_mirror_log(sdk_log_dir: Path) -> Path:
    native_dir = sdk_log_dir / "sdk_native"
    if not native_dir.is_dir():
        return native_dir / "mirror.log"

    candidates = sorted(
        native_dir.glob("mirror_*.log"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return native_dir / "mirror.log"


def collect_log_sources() -> LogSourcesResponse:
    settings = get_runtime_settings()
    sdk_log_dir = Path(settings.sdk_log_dir)

    sources = [
        _describe_log_file("application", Path(settings.log_file_path)),
        _describe_log_file("sdk_tcp", sdk_log_dir / "sdk_tcp" / "sdk_tcp.log"),
        _describe_log_file("host", Path("logs/host/host.log")),
        _describe_log_file("sdk_native", _latest_native_mirror_log(sdk_log_dir)),
    ]
    return LogSourcesResponse(sources=sources)


@router.get("/logs", response_model=LogsResponse)
def read_logs(limit: int = Query(default=150, ge=1, le=500)) -> LogsResponse:
    return LogsResponse(lines=log_buffer.get_lines(limit=limit))


@router.get("/logs/sources", response_model=LogSourcesResponse)
def read_log_sources() -> LogSourcesResponse:
    return collect_log_sources()


@router.websocket("/ws/logs")
async def logs_websocket(websocket: WebSocket) -> None:
    await log_ws_manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await log_ws_manager.disconnect(websocket)
    except Exception:
        await log_ws_manager.disconnect(websocket)
