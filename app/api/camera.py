from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.camera_ws_manager import camera_ws_manager
from app.scanner.camera_stream import camera_stream_service

router = APIRouter(tags=["camera"])


@router.websocket("/ws/camera")
async def camera_websocket(websocket: WebSocket) -> None:
    await camera_ws_manager.connect(websocket)
    await camera_stream_service.on_subscriber_connected()

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await camera_ws_manager.disconnect(websocket)
    except Exception:
        await camera_ws_manager.disconnect(websocket)
    finally:
        await camera_stream_service.on_subscriber_disconnected()
