from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PathRobotStatus:
    status: int

    @property
    def is_idle(self) -> bool:
        return self.status == 1

    @property
    def is_moving(self) -> bool:
        return self.status == 2


@dataclass(frozen=True)
class AxisAngleCommand:
    a1: float
    a2: float
    a3: float
    a4: float
    a5: float
    a6: float
    alive: bool = True
    execute: bool = False


@dataclass(frozen=True)
class TurnCommandMessage:
    turn: float
    alive: bool = True


@dataclass(frozen=True)
class TrajectoryPoint:
    index: int
    guid: str
    point_type: str
    comment: str
    speed: float
    acceleration: float
    a7: float
    a7_speed: float
    a7_acceleration: float
    axes: list[float]
    exposure_val1: int | None = None
    exposure_val2: int | None = None
    exposure_val3: int | None = None
    exposure_marker_exp: int | None = None
