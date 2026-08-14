from pydantic import BaseModel, Field


class AxisSnapshotResponse(BaseModel):
    connected: bool = False
    axes_available: bool = False
    sample_count: int = 0
    timestamp_ms: int | None = None
    a1: float | None = None
    a2: float | None = None
    a3: float | None = None
    a4: float | None = None
    a5: float | None = None
    a6: float | None = None
    external_axis: float | None = None
    last_error: str | None = None
    forward_connected: bool = False
    forward_last_error: str | None = None
