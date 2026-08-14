from __future__ import annotations

import socket
import sys
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.app_state import app_state
from app.axis.service import axis_receiver_service
from app.pipeline.service import pipeline_service
from app.trajectory.kuka_folder_watcher import kuka_folder_watcher

router = APIRouter(prefix="/system", tags=["system"])

_pick_folder_lock = threading.Lock()
_pick_file_lock = threading.Lock()


class HostInfoResponse(BaseModel):
    hostname: str
    platform: str


class PickFolderResponse(BaseModel):
    cancelled: bool = False
    path: str | None = None


class UiLocaleResponse(BaseModel):
    locale: str


class UiLocaleRequest(BaseModel):
    locale: str = Field(pattern="^(en|ru)$")


class PrepareShutdownResponse(BaseModel):
    ok: bool = True


@router.post("/prepare-shutdown", response_model=PrepareShutdownResponse)
def prepare_shutdown() -> PrepareShutdownResponse:
    app_state.is_shutting_down = True
    axis_receiver_service.stop()
    kuka_folder_watcher.stop()
    pipeline_service.shutdown()
    return PrepareShutdownResponse(ok=True)


@router.get("/ui-locale", response_model=UiLocaleResponse)
def get_ui_locale() -> UiLocaleResponse:
    return UiLocaleResponse(locale=app_state.ui_locale)


@router.put("/ui-locale", response_model=UiLocaleResponse)
def set_ui_locale(payload: UiLocaleRequest) -> UiLocaleResponse:
    app_state.ui_locale = payload.locale
    return UiLocaleResponse(locale=app_state.ui_locale)


@router.get("/host-info", response_model=HostInfoResponse)
def get_host_info() -> HostInfoResponse:
    return HostInfoResponse(hostname=socket.gethostname(), platform=sys.platform)


@router.post("/pick-folder", response_model=PickFolderResponse)
def pick_folder() -> PickFolderResponse:
    with _pick_folder_lock:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError as exc:
            raise RuntimeError("Folder picker is not available on this system") from exc

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory()
        finally:
            root.destroy()

        if not selected:
            return PickFolderResponse(cancelled=True, path=None)
        return PickFolderResponse(cancelled=False, path=selected)


@router.post("/pick-file", response_model=PickFolderResponse)
def pick_file() -> PickFolderResponse:
    with _pick_file_lock:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError as exc:
            raise RuntimeError("File picker is not available on this system") from exc

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askopenfilename(
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            )
        finally:
            root.destroy()

        if not selected:
            return PickFolderResponse(cancelled=True, path=None)
        return PickFolderResponse(cancelled=False, path=selected)
