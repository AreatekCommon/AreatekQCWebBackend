from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PathFileInfo(BaseModel):
    name: str
    modified_at: str
    source_position_count: Optional[int] = None


class PathsListResponse(BaseModel):
    folder: str
    active_file: str
    files: list[PathFileInfo]


class PathSelectRequest(BaseModel):
    filename: str


class PathPositionAxes(BaseModel):
    J1: float = 0.0
    J2: float = 0.0
    J3: float = 0.0
    J4: float = 0.0
    J5: float = 0.0
    J6: float = 0.0


class PathPositionTurntable(BaseModel):
    angle: Optional[float] = None
    start_angle: Optional[float] = None
    end_angle: Optional[float] = None
    scan_count: Optional[int] = None
    advanced_scan_mode: Optional[str] = None
    step_angle: Optional[float] = None
    speed: Optional[float] = None
    acceleration: Optional[float] = None


class PathPositionMotion(BaseModel):
    speed: Optional[float] = None
    acceleration: Optional[float] = None


class PathPointExposure(BaseModel):
    val1: Optional[int] = None
    val2: Optional[int] = None
    val3: Optional[int] = None
    marker_exp: Optional[int] = None


class PathPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str = ""
    axes: PathPositionAxes


class PathNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    point_id: str
    prev_node_id: Optional[str] = None
    next_node_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    turntable: PathPositionTurntable = Field(default_factory=PathPositionTurntable)
    motion: Optional[PathPositionMotion] = None
    exposure: Optional[PathPointExposure] = None


class PathPosition(BaseModel):
    """Legacy flat position entry used only during migration from old files."""

    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    comment: str = ""
    axes: PathPositionAxes
    turntable: PathPositionTurntable = Field(default_factory=PathPositionTurntable)
    motion: Optional[PathPositionMotion] = None
    exposure: Optional[PathPointExposure] = None


class PathDocument(BaseModel):
    points: list[PathPoint] = Field(default_factory=list)
    nodes: list[PathNode] = Field(default_factory=list)
    safe_route_ids: list[str] = Field(default_factory=list)
    safe_routes: list[list[bool]] = Field(default_factory=list)
    per_point_exposure: bool = False
    per_point_marker_exposure: bool = False
    uniform_advanced_scan_rotations: bool = False
    uniform_advanced_scan_count: Optional[int] = None


class ActivePathResponse(BaseModel):
    folder: str
    filename: str
    source_path: str
    source_position_count: int
    expanded_point_count: int
    load_error: str | None = None
    document: PathDocument


class PathSaveRequest(BaseModel):
    document: PathDocument


class PathCopyRequest(BaseModel):
    source_filename: str
    target_filename: str


class PathCopyResponse(BaseModel):
    filename: str


class PathCreateRequest(BaseModel):
    filename: str


class PathCreateResponse(BaseModel):
    filename: str


class PathDeleteResponse(BaseModel):
    filename: str
    active_file: str


class PathRenameRequest(BaseModel):
    source_filename: str
    target_filename: str


class PathRenameResponse(BaseModel):
    filename: str
    active_file: str


class PathMoveToRequest(BaseModel):
    position_index: int
    node_id: Optional[str] = None
    document: PathDocument | None = None


class PathTravelStep(BaseModel):
    point_id: str
    name: str = ""
    node_type: str = "transition"
    turntable_angle: float = 0.0
    skipped: bool = False


class PathMoveToResponse(BaseModel):
    status: str = "ok"
    route: list[str] = Field(default_factory=list)
    hops_executed: int = 0
    travel_steps: list[PathTravelStep] = Field(default_factory=list)


class KukaTrajectoryImportRequest(BaseModel):
    source_path: str
    output_folder: str
    output_filename: str


class KukaTrajectoryImportResponse(BaseModel):
    output_path: str
    source_point_count: int
    node_count: int
    point_count: int
    filename: str
