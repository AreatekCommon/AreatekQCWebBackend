from typing import Literal, Optional

from pydantic import BaseModel

PipelineState = Literal["idle", "running", "stopping", "error"]
CycleMode = Literal["production", "calibration"]
CycleTimingMode = Literal["last_scan", "full_cycle"]


class PipelineStatusResponse(BaseModel):
    state: PipelineState
    current_step_index: Optional[int] = None
    scan_count: int = 0
    project_name: Optional[str] = None
    last_error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    scanner_connected: bool = False
    robot_path_connected: bool = False
    turntable_connected: bool = False
    project_ready: bool = False
    trajectory_ready: bool = False
    initializing: bool = False
    can_resume: bool = False
    position_resend_step_indices: list[int] = []
    cycle_mode: Optional[CycleMode] = None
    calibration_trajectory_ready: bool = False
    last_cycle_duration_sec: Optional[float] = None
    last_cycle_timing_mode: Optional[CycleTimingMode] = None
