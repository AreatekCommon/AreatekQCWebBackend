from __future__ import annotations

import xml.etree.ElementTree as ET

from app.core.runtime_settings_store import get_runtime_settings
from app.eki.constants import AXIS_ANGLE_ROOT, ROBOT_STATUS_ROOT, TURN_COMMAND_ROOT
from app.eki.messages import AxisAngleCommand, PathRobotStatus, TurnCommandMessage
from app.eki.turntable_units import format_turntable_turn_for_xml


def bool_to_digit(value: bool) -> str:
    return "1" if value else "0"


def build_axis_angle_xml(command: AxisAngleCommand) -> str:
    return (
        f"<{AXIS_ANGLE_ROOT}>"
        f"<A1>{command.a1:.6f}</A1>"
        f"<A2>{command.a2:.6f}</A2>"
        f"<A3>{command.a3:.6f}</A3>"
        f"<A4>{command.a4:.6f}</A4>"
        f"<A5>{command.a5:.6f}</A5>"
        f"<A6>{command.a6:.6f}</A6>"
        f"<Alive>{bool_to_digit(command.alive)}</Alive>"
        f"<Execute>{bool_to_digit(command.execute)}</Execute>"
        f"</{AXIS_ANGLE_ROOT}>"
    )


def build_turn_command_xml(message: TurnCommandMessage) -> str:
    wire_format = get_runtime_settings().turntable_wire_format
    turn_text = format_turntable_turn_for_xml(message.turn, wire_format)
    return (
        f"<{TURN_COMMAND_ROOT}>"
        f"<Turn>{turn_text}</Turn>"
        f"<Alive>{bool_to_digit(message.alive)}</Alive>"
        f"</{TURN_COMMAND_ROOT}>"
    )


def parse_path_robot_status(xml_packet: str) -> PathRobotStatus:
    root = ET.fromstring(xml_packet)
    if root.tag != ROBOT_STATUS_ROOT:
        raise ValueError(f"Expected <{ROBOT_STATUS_ROOT}>, received <{root.tag}>")

    status_node = root.find("Status")
    if status_node is None or status_node.text is None:
        raise ValueError("RobotStatus is missing Status node")

    return PathRobotStatus(status=int(status_node.text.strip()))
