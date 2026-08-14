from fastapi import APIRouter, HTTPException

from app.core.logger import get_logger
from app.models.cycle_history import CycleHistoryResponse
from app.models.pipeline import PipelineStatusResponse
from app.pipeline.service import pipeline_service

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = get_logger(__name__)

_SDK_BUSY_MARKERS = (
    "ещё выполняется",
    "еще выполняется",
    "still running",
    "command in progress",
)


def _cycle_start_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, ConnectionError):
        return HTTPException(
            status_code=503,
            detail="Scanner connection lost; reconnect and retry",
        )
    if isinstance(exc, TimeoutError):
        return HTTPException(
            status_code=503,
            detail="Scanner command timed out; wait for background init to finish",
        )
    if isinstance(exc, RuntimeError):
        message = str(exc)
        lowered = message.lower()
        if "already running" in lowered:
            return HTTPException(status_code=409, detail=message)
        if any(marker in lowered for marker in _SDK_BUSY_MARKERS):
            return HTTPException(
                status_code=409,
                detail="Scanner busy, retry in a few seconds",
            )
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=503, detail=str(exc))


def _start_cycle() -> None:
    try:
        pipeline_service.start_cycle()
    except RuntimeError as exc:
        raise _cycle_start_http_exception(exc) from exc
    except (ConnectionError, TimeoutError) as exc:
        raise _cycle_start_http_exception(exc) from exc
    except Exception as exc:
        logger.exception("Pipeline start failed")
        raise _cycle_start_http_exception(exc) from exc


def _continue_cycle() -> None:
    try:
        pipeline_service.continue_cycle()
    except RuntimeError as exc:
        raise _cycle_start_http_exception(exc) from exc
    except (ConnectionError, TimeoutError) as exc:
        raise _cycle_start_http_exception(exc) from exc
    except Exception as exc:
        logger.exception("Pipeline continue failed")
        raise _cycle_start_http_exception(exc) from exc


@router.get("/cycle-history", response_model=CycleHistoryResponse)
def read_cycle_history() -> CycleHistoryResponse:
    return CycleHistoryResponse(entries=pipeline_service.get_cycle_history())


@router.get("/status", response_model=PipelineStatusResponse)
def read_pipeline_status() -> PipelineStatusResponse:
    snapshot = pipeline_service.get_status()
    return PipelineStatusResponse(
        state=snapshot.state,
        current_step_index=snapshot.current_step_index,
        scan_count=snapshot.scan_count,
        project_name=snapshot.project_name,
        last_error=snapshot.last_error,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        scanner_connected=snapshot.scanner_connected,
        robot_path_connected=snapshot.robot_path_connected,
        turntable_connected=snapshot.turntable_connected,
        project_ready=snapshot.project_ready,
        trajectory_ready=snapshot.trajectory_ready,
        initializing=snapshot.initializing,
        can_resume=snapshot.can_resume,
        position_resend_step_indices=snapshot.position_resend_step_indices,
        cycle_mode=snapshot.cycle_mode,
        calibration_trajectory_ready=snapshot.calibration_trajectory_ready,
        last_cycle_duration_sec=snapshot.last_cycle_duration_sec,
        last_cycle_timing_mode=snapshot.last_cycle_timing_mode,
    )


@router.post("/start")
def start_pipeline() -> dict:
    _start_cycle()
    return {"ok": True}


@router.post("/calibration/start")
def start_calibration_pipeline() -> dict:
    try:
        pipeline_service.start_calibration_cycle()
    except RuntimeError as exc:
        raise _cycle_start_http_exception(exc) from exc
    except (ConnectionError, TimeoutError) as exc:
        raise _cycle_start_http_exception(exc) from exc
    except Exception as exc:
        logger.exception("Calibration start failed")
        raise _cycle_start_http_exception(exc) from exc
    return {"ok": True}


@router.post("/continue")
def continue_pipeline() -> dict:
    _continue_cycle()
    return {"ok": True}


@router.post("/stop")
def stop_pipeline() -> dict:
    pipeline_service.stop_cycle()
    return {"ok": True}


@router.post("/scanner/reload")
def reload_scanner_sdk() -> dict:
    try:
        pipeline_service.reload_scanner()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/scanner/reconnect")
def reconnect_scanner() -> dict:
    try:
        pipeline_service.reconnect_scanner()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}
