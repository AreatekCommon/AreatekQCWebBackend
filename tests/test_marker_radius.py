from __future__ import annotations

import unittest

from app.marker_radius import (
    MARKER_RADIUS_1MM,
    MARKER_RADIUS_2MM,
    MARKER_RADIUS_4MM,
    WORK_RANGE_LARGE,
    encode_mm_sizes,
    is_valid_marker_radius,
    normalize_marker_radius,
    selected_mm_sizes,
)


class MarkerRadiusTests(unittest.TestCase):
    def test_encode_mm_sizes(self) -> None:
        self.assertEqual(encode_mm_sizes([2, 4]), 6)
        self.assertEqual(encode_mm_sizes([1, 2, 4]), 7)

    def test_selected_mm_sizes(self) -> None:
        self.assertEqual(selected_mm_sizes(6), [2, 4])
        self.assertEqual(selected_mm_sizes(7), [1, 2, 4])

    def test_normalize_large_range_strips_1mm_bit(self) -> None:
        self.assertEqual(normalize_marker_radius(WORK_RANGE_LARGE, 7), 6)

    def test_normalize_large_range_preserves_6(self) -> None:
        self.assertEqual(normalize_marker_radius(WORK_RANGE_LARGE, 6), 6)

    def test_normalize_large_range_strips_1mm_from_3(self) -> None:
        self.assertEqual(normalize_marker_radius(WORK_RANGE_LARGE, 3), 2)

    def test_normalize_zero_defaults_to_4(self) -> None:
        self.assertEqual(normalize_marker_radius(WORK_RANGE_LARGE, 0), 4)
        self.assertEqual(normalize_marker_radius(0, 0), 4)

    def test_normalize_small_range_preserves_7(self) -> None:
        self.assertEqual(normalize_marker_radius(0, 7), 7)

    def test_is_valid_marker_radius(self) -> None:
        self.assertTrue(is_valid_marker_radius(WORK_RANGE_LARGE, 6))
        self.assertFalse(is_valid_marker_radius(WORK_RANGE_LARGE, 7))
        self.assertFalse(is_valid_marker_radius(WORK_RANGE_LARGE, 0))
        self.assertTrue(is_valid_marker_radius(0, MARKER_RADIUS_1MM | MARKER_RADIUS_2MM))


if __name__ == "__main__":
    unittest.main()
