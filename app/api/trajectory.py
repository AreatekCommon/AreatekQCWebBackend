from fastapi import APIRouter

from app.models.trajectory import TrajectoryPointResponse, TrajectoryResponse
from app.trajectory.service import trajectory_service

router = APIRouter(prefix="/trajectory", tags=["trajectory"])


@router.get("", response_model=TrajectoryResponse)
def read_trajectory() -> TrajectoryResponse:
    snapshot = trajectory_service.get_snapshot()
    points = [
        TrajectoryPointResponse(
            index=point.index,
            point_type=point.point_type,
            comment=point.comment,
            a1=point.axes[0],
            a2=point.axes[1],
            a3=point.axes[2],
            a4=point.axes[3],
            a5=point.axes[4],
            a6=point.axes[5],
            turntable_angle=point.a7,
        )
        for point in snapshot.points
    ]
    return TrajectoryResponse(
        source_path=snapshot.source_path,
        point_count=snapshot.point_count,
        load_error=snapshot.load_error,
        points=points,
    )
