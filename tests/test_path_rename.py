from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.runtime_settings import RuntimeSettings
from app.trajectory.path_store import PathStoreError, rename_path_file


class PathRenameStoreTests(unittest.TestCase):
    def test_rename_path_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "old_name.json"
            payload = {"points": [], "nodes": [], "safe_route_ids": [], "safe_routes": []}
            source.write_text(json.dumps(payload), encoding="utf-8")

            renamed = rename_path_file(temp_dir, "old_name.json", "new_name.json")
            self.assertEqual(renamed.name, "new_name.json")
            self.assertFalse(source.exists())
            self.assertTrue(renamed.is_file())

    def test_rename_rejects_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = {"points": [], "nodes": [], "safe_route_ids": [], "safe_routes": []}
            (Path(temp_dir) / "source.json").write_text(json.dumps(payload), encoding="utf-8")
            (Path(temp_dir) / "target.json").write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(PathStoreError):
                rename_path_file(temp_dir, "source.json", "target.json")


class PathRenameApiTests(unittest.TestCase):
    def test_rename_inactive_file_keeps_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            active = Path(temp_dir) / "active.json"
            other = Path(temp_dir) / "other.json"
            payload = {"points": [], "nodes": [], "safe_route_ids": [], "safe_routes": []}
            active.write_text(json.dumps(payload), encoding="utf-8")
            other.write_text(json.dumps(payload), encoding="utf-8")

            settings = RuntimeSettings(
                paths_folder=temp_dir,
                active_path_file="active.json",
            )

            with patch("app.api.paths.get_runtime_settings", return_value=settings), patch(
                "app.api.paths.pipeline_service.get_status",
                return_value=MagicMock(state="idle"),
            ):
                from app.api.paths import rename_path
                from app.models.paths import PathRenameRequest

                response = rename_path(
                    PathRenameRequest(
                        source_filename="other.json",
                        target_filename="renamed.json",
                    )
                )

            self.assertEqual(response.filename, "renamed.json")
            self.assertEqual(response.active_file, "active.json")
            self.assertTrue((Path(temp_dir) / "renamed.json").is_file())

    def test_rename_active_file_updates_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            active = Path(temp_dir) / "active.json"
            payload = {"points": [], "nodes": [], "safe_route_ids": [], "safe_routes": []}
            active.write_text(json.dumps(payload), encoding="utf-8")

            settings = RuntimeSettings(
                paths_folder=temp_dir,
                active_path_file="active.json",
            )

            with patch("app.api.paths.get_runtime_settings", return_value=settings), patch(
                "app.api.paths.update_runtime_settings",
                side_effect=lambda value: value,
            ) as update_settings_mock, patch(
                "app.api.paths.pipeline_service.get_status",
                return_value=MagicMock(state="idle"),
            ), patch(
                "app.api.paths.trajectory_service.reload_active"
            ), patch(
                "app.api.paths.pipeline_service.on_path_updated"
            ):
                from app.api.paths import rename_path
                from app.models.paths import PathRenameRequest

                response = rename_path(
                    PathRenameRequest(
                        source_filename="active.json",
                        target_filename="renamed_active.json",
                    )
                )

            self.assertEqual(response.active_file, "renamed_active.json")
            update_settings_mock.assert_called_once()
            self.assertTrue((Path(temp_dir) / "renamed_active.json").is_file())


if __name__ == "__main__":
    unittest.main()
