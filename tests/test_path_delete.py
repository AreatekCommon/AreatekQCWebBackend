from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.runtime_settings import RuntimeSettings
from app.trajectory.path_store import PathStoreError, create_path_file, delete_path_file, list_json_files


class PathDeleteStoreTests(unittest.TestCase):
    def test_delete_path_file_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            created = create_path_file(temp_dir, "remove_me.json")
            self.assertTrue(created.is_file())

            deleted = delete_path_file(temp_dir, "remove_me.json")
            self.assertEqual(deleted.name, "remove_me.json")
            self.assertFalse(created.exists())

    def test_delete_path_file_missing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(PathStoreError):
                delete_path_file(temp_dir, "missing.json")


class PathDeleteApiTests(unittest.TestCase):
    def test_delete_inactive_file_keeps_active(self) -> None:
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
                "app.api.paths.update_runtime_settings",
                side_effect=lambda value: value,
            ), patch("app.api.paths.pipeline_service.get_status", return_value=MagicMock(state="idle")), patch(
                "app.api.paths.trajectory_service.reload_active"
            ), patch(
                "app.api.paths.pipeline_service.on_path_updated"
            ):
                from app.api.paths import delete_path

                response = delete_path("other.json")

            self.assertEqual(response.filename, "other.json")
            self.assertEqual(response.active_file, "active.json")
            self.assertFalse(other.exists())
            self.assertTrue(active.exists())

    def test_delete_active_file_switches_to_remaining(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            active = Path(temp_dir) / "active.json"
            backup = Path(temp_dir) / "backup.json"
            payload = {"points": [], "nodes": [], "safe_route_ids": [], "safe_routes": []}
            active.write_text(json.dumps(payload), encoding="utf-8")
            backup.write_text(json.dumps(payload), encoding="utf-8")

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
                from app.api.paths import delete_path

                response = delete_path("active.json")

            self.assertEqual(response.active_file, "backup.json")
            update_settings_mock.assert_called_once()
            updated = update_settings_mock.call_args.args[0]
            self.assertEqual(updated.active_path_file, "backup.json")
            self.assertFalse(active.exists())
            self.assertTrue(backup.exists())

    def test_delete_last_file_creates_new_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            only = Path(temp_dir) / "only.json"
            payload = {"points": [], "nodes": [], "safe_route_ids": [], "safe_routes": []}
            only.write_text(json.dumps(payload), encoding="utf-8")

            settings = RuntimeSettings(
                paths_folder=temp_dir,
                active_path_file="only.json",
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
                from app.api.paths import delete_path

                response = delete_path("only.json")

            self.assertEqual(response.active_file, "new_path.json")
            updated = update_settings_mock.call_args.args[0]
            self.assertEqual(updated.active_path_file, "new_path.json")
            remaining = [entry["name"] for entry in list_json_files(temp_dir)]
            self.assertEqual(remaining, ["new_path.json"])


if __name__ == "__main__":
    unittest.main()
