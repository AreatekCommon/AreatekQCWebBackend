import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.eki.path_parser import (
    expand_turntable_angles,
    expand_turntable_angles_step,
    parse_positions_json,
)
from app.eki.turntable_units import (
    DEFAULT_COUNTS_PER_REV,
    angle_deg_to_counts,
    counts_to_angle_deg,
    format_turntable_turn_for_xml,
    quantize_turntable_angle,
    turntable_angle_for_wire,
    turntable_wire_display_value,
)
from app.eki.xml_codec import build_turn_command_xml
from app.eki.messages import TurnCommandMessage
from app.models.runtime_settings import RuntimeSettings

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_movement_path.json"
SAMPLE_ANGLE = 32.72727272727273


def counts_for_angle(angle_deg: float) -> int:
    return round(angle_deg / 360.0 * DEFAULT_COUNTS_PER_REV)


class TurntableUnitsTests(unittest.TestCase):
    def test_zero_and_full_revolution(self) -> None:
        self.assertEqual(angle_deg_to_counts(0.0), 0)
        self.assertEqual(angle_deg_to_counts(360.0), DEFAULT_COUNTS_PER_REV)
        self.assertEqual(quantize_turntable_angle(0.0), 0.0)
        self.assertEqual(quantize_turntable_angle(360.0), 360.0)

    def test_slight_overflow_clamps_to_counts_per_rev(self) -> None:
        self.assertEqual(angle_deg_to_counts(360.000001), DEFAULT_COUNTS_PER_REV)
        self.assertEqual(quantize_turntable_angle(360.000001), 360.0)

    def test_negative_angle_clamps_to_zero(self) -> None:
        self.assertEqual(angle_deg_to_counts(-10.0), 0)
        self.assertEqual(quantize_turntable_angle(-10.0), 0.0)

    def test_multi_turn_angle_clamps_with_warning(self) -> None:
        self.assertEqual(angle_deg_to_counts(720.0), DEFAULT_COUNTS_PER_REV)
        self.assertEqual(quantize_turntable_angle(720.0), 360.0)

    def test_round_trip_via_counts(self) -> None:
        counts = 123456
        self.assertEqual(counts_to_angle_deg(counts), counts / DEFAULT_COUNTS_PER_REV * 360.0)
        self.assertEqual(angle_deg_to_counts(counts_to_angle_deg(counts)), counts)

    def test_quantize_matches_count_grid(self) -> None:
        angle = 32.72727272727273
        quantized = quantize_turntable_angle(angle)
        self.assertEqual(counts_for_angle(quantized), angle_deg_to_counts(angle))


class TurntableAngleForWireTests(unittest.TestCase):
    def test_zero_and_full_revolution(self) -> None:
        self.assertEqual(turntable_angle_for_wire(0.0), 0.0)
        self.assertEqual(turntable_angle_for_wire(360.0), 360.0)

    def test_fractional_input_stays_count_quantized(self) -> None:
        angle = 32.72727272727273
        self.assertEqual(turntable_angle_for_wire(angle), quantize_turntable_angle(angle))

    def test_negative_angle_clamps_to_zero(self) -> None:
        self.assertEqual(turntable_angle_for_wire(-10.0), 0.0)

    def test_overflow_clamps_to_full_revolution(self) -> None:
        self.assertEqual(turntable_angle_for_wire(360.000001), 360.0)
        self.assertEqual(turntable_angle_for_wire(720.0), 360.0)


class TurntableWireFormatTests(unittest.TestCase):
    def test_format_decimal_two(self) -> None:
        self.assertEqual(
            format_turntable_turn_for_xml(SAMPLE_ANGLE, "decimal_2"),
            f"{turntable_angle_for_wire(SAMPLE_ANGLE):.2f}",
        )

    def test_format_integer(self) -> None:
        self.assertEqual(format_turntable_turn_for_xml(SAMPLE_ANGLE, "integer"), "33")

    def test_display_value_decimal_two(self) -> None:
        self.assertEqual(
            turntable_wire_display_value(SAMPLE_ANGLE, "decimal_2"),
            round(turntable_angle_for_wire(SAMPLE_ANGLE), 2),
        )

    def test_display_value_integer(self) -> None:
        self.assertEqual(turntable_wire_display_value(SAMPLE_ANGLE, "integer"), 33.0)


class ExpandTurntableAnglesTests(unittest.TestCase):
    def test_zero_to_three_sixty_twelve_steps(self) -> None:
        angles = expand_turntable_angles(0.0, 360.0, 12)
        self.assertEqual(len(angles), 12)
        self.assertEqual(angles[0], 30.0)
        self.assertEqual(angles[-1], 360.0)

        for angle in angles:
            counts = counts_for_angle(angle)
            self.assertEqual(counts, round(angle / 360.0 * DEFAULT_COUNTS_PER_REV))
            self.assertLessEqual(counts, DEFAULT_COUNTS_PER_REV)

    def test_zero_to_three_sixty_four_steps(self) -> None:
        angles = expand_turntable_angles(0.0, 360.0, 4)
        self.assertEqual(angles, [90.0, 180.0, 270.0, 360.0])

    def test_three_sixty_to_zero_four_steps(self) -> None:
        angles = expand_turntable_angles(360.0, 0.0, 4)
        self.assertEqual(angles, [270.0, 180.0, 90.0, 0.0])

    def test_full_revolution_single_step_uses_end_angle(self) -> None:
        self.assertEqual(expand_turntable_angles(0.0, 360.0, 1), [360.0])
        self.assertEqual(expand_turntable_angles(360.0, 0.0, 1), [0.0])

    def test_three_sixty_to_zero_thirty_four_steps(self) -> None:
        angles = expand_turntable_angles(360.0, 0.0, 34)
        self.assertEqual(len(angles), 34)
        self.assertEqual(angles[0], quantize_turntable_angle(360.0 - 360.0 / 34))
        self.assertEqual(angles[-1], 0.0)

        for angle in angles:
            counts = angle_deg_to_counts(angle)
            self.assertGreaterEqual(counts, 0)
            self.assertLessEqual(counts, DEFAULT_COUNTS_PER_REV)

    def test_steps_use_uniform_count_spacing_within_one(self) -> None:
        angles = expand_turntable_angles(0.0, 360.0, 12)
        count_values = [angle_deg_to_counts(angle) for angle in angles]
        expected_step = DEFAULT_COUNTS_PER_REV // 12
        for left, right in zip(count_values, count_values[1:]):
            self.assertAlmostEqual(right - left, expected_step, delta=1)

    def test_brake_path_first_advanced_scan_skips_zero(self) -> None:
        brake_path = Path(__file__).resolve().parents[1] / "data" / "Brake.json"
        with brake_path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)

        points = parse_positions_json(data)
        first_scan_angles = [point.a7 for point in points if point.point_type == "scan"][:4]
        self.assertEqual(first_scan_angles, [90.0, 180.0, 270.0, 360.0])


class ExpandTurntableAnglesStepTests(unittest.TestCase):
    def test_positive_step(self) -> None:
        angles = expand_turntable_angles_step(0.0, 4, 90.0)
        self.assertEqual(angles, [0.0, 90.0, 180.0, 270.0])

    def test_negative_step(self) -> None:
        angles = expand_turntable_angles_step(270.0, 4, -90.0)
        self.assertEqual(angles, [270.0, 180.0, 90.0, 0.0])

    def test_rejects_zero_step(self) -> None:
        with self.assertRaises(ValueError):
            expand_turntable_angles_step(0.0, 4, 0.0)

    def test_parser_step_mode_produces_expected_a7_values(self) -> None:
        document = {
            "positions": [
                {
                    "id": "1",
                    "type": "advanced_scan",
                    "comment": "step scan",
                    "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0},
                    "turntable": {
                        "advanced_scan_mode": "step",
                        "start_angle": 0,
                        "scan_count": 4,
                        "step_angle": 90,
                    },
                }
            ]
        }

        points = parse_positions_json(document)

        self.assertEqual(len(points), 4)
        self.assertEqual([point.a7 for point in points], [0.0, 90.0, 180.0, 270.0])


class BuildTurnCommandXmlTests(unittest.TestCase):
    def test_xml_uses_decimal_two_format_by_default(self) -> None:
        settings = RuntimeSettings(turntable_wire_format="decimal_2")
        with patch("app.eki.xml_codec.get_runtime_settings", return_value=settings):
            xml = build_turn_command_xml(
                TurnCommandMessage(turn=SAMPLE_ANGLE, alive=True)
            )
        self.assertIn(
            f"<Turn>{format_turntable_turn_for_xml(SAMPLE_ANGLE, 'decimal_2')}</Turn>",
            xml,
        )

    def test_xml_uses_integer_format_when_configured(self) -> None:
        settings = RuntimeSettings(turntable_wire_format="integer")
        with patch("app.eki.xml_codec.get_runtime_settings", return_value=settings):
            xml = build_turn_command_xml(
                TurnCommandMessage(turn=SAMPLE_ANGLE, alive=True)
            )
        self.assertIn("<Turn>33</Turn>", xml)


class SamplePathTests(unittest.TestCase):
    def test_sample_path_a7_values_are_count_aligned(self) -> None:
        with SAMPLE_PATH.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)

        points = parse_positions_json(data)
        self.assertGreater(len(points), 0)

        for point in points:
            counts = counts_for_angle(point.a7)
            self.assertEqual(counts, round(point.a7 / 360.0 * DEFAULT_COUNTS_PER_REV))
            self.assertLessEqual(counts, DEFAULT_COUNTS_PER_REV)
            self.assertEqual(point.a7, quantize_turntable_angle(point.a7))


if __name__ == "__main__":
    unittest.main()
