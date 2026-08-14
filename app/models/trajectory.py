from pydantic import BaseModel, Field


class TrajectoryPointResponse(BaseModel):
    index: int
    point_type: str
    comment: str
    a1: float
    a2: float
    a3: float
    a4: float
    a5: float
    a6: float
    turntable_angle: float = Field(description="Turntable angle (A7)")


class TrajectoryResponse(BaseModel):
    source_path: str
    point_count: int
    load_error: str | None
    points: list[TrajectoryPointResponse]
