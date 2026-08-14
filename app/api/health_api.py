from fastapi import APIRouter

from app.core.app_state import app_state

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def get_health() -> dict:
    return {
        "status": app_state.status,
        "is_running": app_state.is_running,
        "started_at": app_state.started_at.isoformat() if app_state.started_at else None,
        "last_error": app_state.last_error,
        "connected_web_clients": app_state.connected_web_clients,
    }