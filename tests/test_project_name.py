from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models.scanner_settings import (
    ProjectNameIncrementPart,
    ProjectNameTemplate,
    ProjectNameTextPart,
    ProjectNameTimestampPart,
    ScannerSettings,
)
from app.scanner.project_name import (
    advance_project_name_counter,
    assemble_project_name,
    suggest_project_name_counter,
    template_has_increment_part,
)


class ProjectNameTests(unittest.TestCase):
    def test_empty_template_uses_legacy_fallback(self) -> None:
        scanner = ScannerSettings(project_name=ProjectNameTemplate(parts=[]))
        name = assemble_project_name(
            scanner,
            now=datetime(2026, 7, 23, 15, 0, 30),
        )
        self.assertEqual(name, "scan_20260723_150030")

    def test_text_increment_timestamp_assembly(self) -> None:
        scanner = ScannerSettings(
            project_name=ProjectNameTemplate(
                parts=[
                    ProjectNameTextPart(value="brake"),
                    ProjectNameIncrementPart(width=3),
                    ProjectNameTimestampPart(format="YYYYMMDD"),
                ]
            ),
            project_name_counter=7,
        )
        name = assemble_project_name(
            scanner,
            now=datetime(2026, 7, 23, 15, 0, 30),
        )
        self.assertEqual(name, "brake_007_20260723")

    def test_increment_zero_padding(self) -> None:
        scanner = ScannerSettings(
            project_name=ProjectNameTemplate(
                parts=[ProjectNameIncrementPart(width=4)]
            ),
            project_name_counter=12,
        )
        name = assemble_project_name(scanner, now=datetime(2026, 1, 1))
        self.assertEqual(name, "0012")

    def test_counter_advances_only_when_increment_part_present(self) -> None:
        without_increment = ScannerSettings(
            project_name=ProjectNameTemplate(
                parts=[ProjectNameTextPart(value="part")]
            ),
            project_name_counter=5,
        )
        with_increment = ScannerSettings(
            project_name=ProjectNameTemplate(
                parts=[ProjectNameIncrementPart(width=2)]
            ),
            project_name_counter=5,
        )

        self.assertFalse(template_has_increment_part(without_increment.project_name))
        self.assertEqual(
            advance_project_name_counter(without_increment).project_name_counter,
            5,
        )
        self.assertTrue(template_has_increment_part(with_increment.project_name))
        self.assertEqual(
            advance_project_name_counter(with_increment).project_name_counter,
            6,
        )

    def test_sanitization_of_unsafe_characters(self) -> None:
        scanner = ScannerSettings(
            project_name=ProjectNameTemplate(
                parts=[ProjectNameTextPart(value="brake scan/test")]
            )
        )
        name = assemble_project_name(scanner, now=datetime(2026, 1, 1))
        self.assertEqual(name, "brake_scan_test")

    def test_suggest_counter_empty_export_root(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            scanner = ScannerSettings(
                project_name=ProjectNameTemplate(
                    parts=[
                        ProjectNameTextPart(value="brake"),
                        ProjectNameIncrementPart(width=3),
                    ]
                ),
                export_root=tmp_dir,
                project_name_counter=99,
            )
            self.assertEqual(suggest_project_name_counter(scanner), 1)

    def test_suggest_counter_fills_lowest_gap(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "brake_001").mkdir()
            (root / "brake_003").mkdir()
            scanner = ScannerSettings(
                project_name=ProjectNameTemplate(
                    parts=[
                        ProjectNameTextPart(value="brake"),
                        ProjectNameIncrementPart(width=3),
                    ]
                ),
                export_root=tmp_dir,
                project_name_counter=99,
            )
            self.assertEqual(suggest_project_name_counter(scanner), 2)

    def test_suggest_counter_without_increment_part(self) -> None:
        scanner = ScannerSettings(
            project_name=ProjectNameTemplate(parts=[ProjectNameTextPart(value="part")]),
            project_name_counter=5,
        )
        self.assertEqual(suggest_project_name_counter(scanner), 5)


if __name__ == "__main__":
    unittest.main()
