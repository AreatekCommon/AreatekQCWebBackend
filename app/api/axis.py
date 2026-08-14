from fastapi import APIRouter

from app.axis.service import axis_receiver_service
from app.models.axis import AxisSnapshotResponse

router = APIRouter(prefix="/axis", tags=["axis"])


@router.get("", response_model=AxisSnapshotResponse)
def read_axis_snapshot() -> AxisSnapshotResponse:
    snapshot = axis_receiver_service.get_snapshot()
    return AxisSnapshotResponse(**snapshot)
