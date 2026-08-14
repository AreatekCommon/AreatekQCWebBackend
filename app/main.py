import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.axis.service import axis_receiver_service
from app.core.app_state import app_state
from app.core.config import get_settings
from app.core.log_ws_manager import log_ws_manager
from app.core.logger import (
    apply_runtime_logging_settings,
    configure_logging,
    ensure_web_log_handlers,
    get_logger,
)
from app.core.runtime_settings_store import get_runtime_settings
from app.core.messages import tr
from app.pipeline.service import pipeline_service
from app.scanner.sdk_logging import apply_sdk_logging
from app.trajectory.service import trajectory_service
from app.trajectory.kuka_folder_watcher import kuka_folder_watcher

settings = get_settings()
configure_logging(debug=settings.debug)
_runtime_settings = get_runtime_settings()
apply_runtime_logging_settings(
    log_level=_runtime_settings.log_level,
    log_to_file=_runtime_settings.log_to_file,
    log_file_path=_runtime_settings.log_file_path,
)
apply_sdk_logging(_runtime_settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_ws_manager.set_event_loop(asyncio.get_running_loop())
    ensure_web_log_handlers()
    apply_runtime_logging_settings(
        log_level=get_runtime_settings().log_level,
        log_to_file=get_runtime_settings().log_to_file,
        log_file_path=get_runtime_settings().log_file_path,
    )
    apply_sdk_logging(get_runtime_settings())
    runtime_settings = get_runtime_settings()
    logger.info(
        "Axis receiver target: %s:%d",
        runtime_settings.sender_host,
        runtime_settings.sender_port,
    )
    axis_receiver_service.start()
    trajectory_service.load_at_startup()
    pipeline_service.initialize()
    kuka_folder_watcher.start()
    logger.info(tr("app_starting"))
    app_state.mark_started()
    app_state.add_log(tr("app_started"))

    try:
        yield
    except Exception as exc:
        app_state.mark_error(str(exc))
        app_state.add_log(tr("lifespan_error"))
        logger.exception(tr("unhandled_lifespan_error"))
        raise
    finally:
        kuka_folder_watcher.stop()
        pipeline_service.shutdown()
        axis_receiver_service.stop()
        logger.info(tr("app_stopping"))
        app_state.add_log(tr("app_stopped"))
        app_state.mark_stopped()


app = FastAPI(
    title="Areatek QC Backend",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


def _resolve_frontend_dist() -> Path | None:
    candidates = [
        Path(__file__).resolve().parents[2] / "areatekqcweb" / "dist",
        Path(__file__).resolve().parents[1] / "areatekqcweb" / "dist",
        Path.cwd() / "areatekqcweb" / "dist",
        Path.cwd() / "dist",
    ]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent / "dist")

    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


_FRONTEND_DIST = _resolve_frontend_dist()
if _FRONTEND_DIST is not None:
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend_assets")

    @app.get("/")
    async def serve_frontend_root() -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    async def serve_frontend_spa(full_path: str) -> FileResponse:
        if full_path.startswith(("docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404)
        asset_path = _FRONTEND_DIST / full_path
        if asset_path.is_file():
            return FileResponse(asset_path)
        return FileResponse(_FRONTEND_DIST / "index.html")
else:

    @app.get("/")
    def root() -> dict:
        return {
            "message": tr("root_message"),
            "docs": "/docs",
        }


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        client_host = request.client.host if request.client else "-"
        logger.info(
            '%s - "%s %s HTTP/1.1" %s',
            client_host,
            request.method,
            request.url.path,
            response.status_code,
        )
    return response