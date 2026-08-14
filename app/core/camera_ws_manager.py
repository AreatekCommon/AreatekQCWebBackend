import asyncio
from typing import Set

from fastapi import WebSocket


class CameraWebSocketManager:
    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def count(self) -> int:
        async with self._lock:
            return len(self._clients)

    async def broadcast_bytes(self, payload: bytes) -> None:
        if not payload:
            return

        async with self._lock:
            clients = list(self._clients)

        stale_clients: list[WebSocket] = []

        for client in clients:
            try:
                await client.send_bytes(payload)
            except Exception:
                stale_clients.append(client)

        if stale_clients:
            async with self._lock:
                for client in stale_clients:
                    self._clients.discard(client)

    async def broadcast_text(self, payload: str) -> None:
        if not payload:
            return

        async with self._lock:
            clients = list(self._clients)

        stale_clients: list[WebSocket] = []

        for client in clients:
            try:
                await client.send_text(payload)
            except Exception:
                stale_clients.append(client)

        if stale_clients:
            async with self._lock:
                for client in stale_clients:
                    self._clients.discard(client)


camera_ws_manager = CameraWebSocketManager()
