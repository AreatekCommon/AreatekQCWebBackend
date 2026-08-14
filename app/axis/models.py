from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ReceiverSettings:
    host: str = "192.168.0.5"
    port: int = 54600
    connect_timeout_s: float = 5.0
    receive_timeout_s: float = 1.0
    reconnect_delay_s: float = 2.0
    send_ready_on_connect: bool = True
    ready_value: bool = True
    tcp_no_delay: bool = True
    receive_buffer_size: int = 4096


@dataclass(frozen=True)
class ForwardSettings:
    host: str = "192.168.40.154"
    port: int = 3400
    connect_timeout_s: float = 5.0
    send_timeout_s: float = 2.0
    reconnect_delay_s: float = 2.0
    tcp_no_delay: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class AxisSample:
    a1: float
    a2: float
    a3: float
    a4: float
    a5: float
    a6: float
    external_axis: float = 30.0
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @classmethod
    def from_xml(cls, xml_text: str, external_axis: float = 30.0) -> AxisSample:
        root = ET.fromstring(xml_text)
        if root.tag != "Axes":
            raise ValueError(f"Expected root tag <Axes>, received <{root.tag}>")

        values: dict[str, float] = {}
        for axis_name in ("A1", "A2", "A3", "A4", "A5", "A6"):
            raw_value = root.findtext(axis_name)
            if raw_value is None:
                raise ValueError(f"Axis <{axis_name}> is absent in XML")
            values[axis_name] = float(raw_value)

        return cls(
            a1=values["A1"],
            a2=values["A2"],
            a3=values["A3"],
            a4=values["A4"],
            a5=values["A5"],
            a6=values["A6"],
            external_axis=external_axis,
        )

    def joint_values(self) -> list[float]:
        return [self.a1, self.a2, self.a3, self.a4, self.a5, self.a6, self.external_axis]

    def to_core_control_visual_message(self) -> str:
        payload = {
            "Timestamp": self.timestamp_ms,
            "RobotAndExternalAxisJointValues": self.joint_values(),
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


@dataclass
class AxisState:
    last_sample: Optional[AxisSample] = None
    sample_count: int = 0

    def update(self, sample: AxisSample) -> None:
        self.last_sample = sample
        self.sample_count += 1
