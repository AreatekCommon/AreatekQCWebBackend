from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api import projects as projects_api
from app.models.paths import PathDocument
from app.models.runtime_settings import RuntimeSettings
from app.trajectory.service import TrajectorySnapshot


class ProjectsApiTests(unittest.TestCase):
    def test_sanitize_rejects_path_separators(self) -> None:
        with self.assertRaises(HTTPException):
            projects_api._sanitize_project_name("../secret")
        with self.assertRaises(HTTPException):
            projects_api._sanitize_project_name("a/b")

    def test_sanitize_accepts_simple_names(self) -> None:
        self.assertEqual(projects_api._sanitize_project_name("  Brake_1 "), "Brake_1")

    def test_sanitize_accepts_cyrillic_names(self) -> None:
        self.assertEqual(projects_api._sanitize_project_name("  Штуцер "), "Штуцер")
        self.assertEqual(projects_api._sanitize_project_name("Тест-1"), "Тест-1")

    def test_active_project_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            active_path = root / ".active.json"
            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api, "ACTIVE_PROJECT_PATH", active_path
            ):
                self.assertIsNone(projects_api._get_active_project_name())

                projects_api._set_active_project_name("Штуцер")
                self.assertEqual(projects_api._get_active_project_name(), "Штуцер")

                response = projects_api.write_active_project(
                    projects_api.ActiveProjectRequest(name=None)
                )
                self.assertIsNone(response.name)
                self.assertIsNone(projects_api._get_active_project_name())

    def test_write_active_project_requires_existing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            active_path = root / ".active.json"
            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api, "ACTIVE_PROJECT_PATH", active_path
            ):
                with self.assertRaises(HTTPException) as raised:
                    projects_api.write_active_project(
                        projects_api.ActiveProjectRequest(name="Missing")
                    )
                self.assertEqual(raised.exception.status_code, 404)

    def test_save_project_writes_reference_only_and_requires_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            active_path = root / ".active.json"
            runtime_settings = RuntimeSettings(active_path_file="selected.json")
            stale_form_settings = RuntimeSettings(active_path_file="stale.json")
            payload = projects_api.ProjectSaveRequest(
                name="Demo Project",
                overwrite=False,
                settings=stale_form_settings,
            )

            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api, "ACTIVE_PROJECT_PATH", active_path
            ), patch.object(
                projects_api.pipeline_service, "get_status", return_value=MagicMock(state="idle")
            ), patch.object(
                projects_api, "get_runtime_settings", return_value=runtime_settings
            ), patch.object(
                projects_api, "update_runtime_settings", return_value=runtime_settings
            ) as update_mock, patch.object(
                projects_api.pipeline_service,
                "apply_settings_section",
                return_value=MagicMock(apply_error=None),
            ):
                first = projects_api.save_project(payload)
                project_dir = root / "Demo Project"
                self.assertTrue((project_dir / "settings.json").is_file())
                self.assertFalse((project_dir / "path.json").exists())
                self.assertTrue((project_dir / "meta.json").is_file())
                self.assertEqual(first.name, "Demo Project")
                self.assertEqual(projects_api._get_active_project_name(), "Demo Project")

                saved_settings = update_mock.call_args.args[0]
                self.assertEqual(saved_settings.active_path_file, "selected.json")

                settings_data = json.loads((project_dir / "settings.json").read_text(encoding="utf-8"))
                meta_data = json.loads((project_dir / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(settings_data["active_path_file"], "selected.json")
                self.assertEqual(meta_data["active_path_file"], "selected.json")

                with self.assertRaises(HTTPException) as raised:
                    projects_api.save_project(payload)
                self.assertEqual(raised.exception.status_code, 409)

                payload.overwrite = True
                second = projects_api.save_project(payload)
                self.assertEqual(second.name, "Demo Project")
                self.assertFalse((project_dir / "path.json").exists())

    def test_save_project_accepts_cyrillic_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            active_path = root / ".active.json"
            settings = RuntimeSettings(active_path_file="demo.json")
            payload = projects_api.ProjectSaveRequest(
                name="Штуцер",
                overwrite=False,
                settings=settings,
            )

            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api, "ACTIVE_PROJECT_PATH", active_path
            ), patch.object(
                projects_api.pipeline_service, "get_status", return_value=MagicMock(state="idle")
            ), patch.object(
                projects_api, "get_runtime_settings", return_value=settings
            ), patch.object(
                projects_api, "update_runtime_settings", return_value=settings
            ), patch.object(
                projects_api.pipeline_service,
                "apply_settings_section",
                return_value=MagicMock(apply_error=None),
            ):
                response = projects_api.save_project(payload)
                self.assertEqual(response.name, "Штуцер")
                self.assertTrue((root / "Штуцер" / "settings.json").is_file())
                self.assertFalse((root / "Штуцер" / "path.json").exists())

    def test_load_project_reloads_active_trajectory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            active_path = root / ".active.json"
            project_dir = root / "Штуцер"
            project_dir.mkdir(parents=True)
            settings = RuntimeSettings(active_path_file="loaded.json")
            document = PathDocument(
                points=[{"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}}],
                nodes=[
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "0",
                        "turntable": {"angle": 0.0},
                        "motion": {"speed": 50.0, "acceleration": 50.0},
                    }
                ],
            )
            (project_dir / "settings.json").write_text(
                json.dumps(settings.model_dump(), ensure_ascii=False),
                encoding="utf-8",
            )

            snapshot = TrajectorySnapshot(
                source_path="loaded.json",
                point_count=1,
                load_error=None,
                points=[],
            )

            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api, "ACTIVE_PROJECT_PATH", active_path
            ), patch.object(
                projects_api.pipeline_service, "get_status", return_value=MagicMock(state="idle")
            ), patch.object(
                projects_api, "get_runtime_settings", return_value=RuntimeSettings()
            ), patch.object(
                projects_api, "update_runtime_settings", return_value=settings
            ) as update_mock, patch.object(
                projects_api.pipeline_service,
                "apply_settings_section",
                return_value=MagicMock(apply_error=None),
            ), patch.object(
                projects_api.trajectory_service, "reload_active", return_value=snapshot
            ), patch.object(
                projects_api.trajectory_service,
                "get_active_document",
                return_value=document.model_dump(exclude_none=True),
            ), patch.object(
                projects_api.pipeline_service, "on_path_updated"
            ):
                response = projects_api.load_project("Штуцер")
                self.assertEqual(response.name, "Штуцер")
                self.assertEqual(response.settings.active_path_file, "loaded.json")
                self.assertEqual(len(response.path_document.nodes), 1)
                update_mock.assert_called_once()
                self.assertEqual(projects_api._get_active_project_name(), "Штуцер")

    def test_load_project_migrates_legacy_path_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            active_path = root / ".active.json"
            project_dir = root / "Legacy"
            project_dir.mkdir(parents=True)
            settings = RuntimeSettings(active_path_file="loaded.json")
            legacy_document = {
                "points": [{"id": "0", "name": "home", "axes": {"J1": 0, "J2": 0, "J3": 0, "J4": 0, "J5": 0, "J6": 0}}],
                "nodes": [
                    {
                        "id": "0",
                        "type": "home",
                        "point_id": "0",
                        "turntable": {"angle": 0.0},
                        "motion": {"speed": 50.0, "acceleration": 50.0},
                    }
                ],
            }
            (project_dir / "settings.json").write_text(
                json.dumps(settings.model_dump(), ensure_ascii=False),
                encoding="utf-8",
            )
            (project_dir / "path.json").write_text(
                json.dumps(legacy_document, ensure_ascii=False),
                encoding="utf-8",
            )

            failed_snapshot = TrajectorySnapshot(
                source_path="loaded.json",
                point_count=0,
                load_error="Trajectory file not found",
                points=[],
            )
            loaded_snapshot = TrajectorySnapshot(
                source_path="loaded.json",
                point_count=1,
                load_error=None,
                points=[],
            )

            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api, "ACTIVE_PROJECT_PATH", active_path
            ), patch.object(
                projects_api.pipeline_service, "get_status", return_value=MagicMock(state="idle")
            ), patch.object(
                projects_api, "get_runtime_settings", return_value=RuntimeSettings()
            ), patch.object(
                projects_api, "update_runtime_settings", return_value=settings
            ), patch.object(
                projects_api.pipeline_service,
                "apply_settings_section",
                return_value=MagicMock(apply_error=None),
            ), patch.object(
                projects_api.trajectory_service,
                "reload_active",
                side_effect=[failed_snapshot, loaded_snapshot],
            ), patch.object(
                projects_api.trajectory_service,
                "save_active_document",
                return_value=MagicMock(),
            ) as save_mock, patch.object(
                projects_api.trajectory_service,
                "get_active_document",
                return_value=legacy_document,
            ), patch.object(
                projects_api.pipeline_service, "on_path_updated"
            ):
                response = projects_api.load_project("Legacy")
                self.assertEqual(response.name, "Legacy")
                self.assertEqual(len(response.path_document.nodes), 1)
                save_mock.assert_called_once()

    def test_load_project_blocked_while_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            project_dir = root / "Demo"
            project_dir.mkdir(parents=True)
            settings = RuntimeSettings()
            (project_dir / "settings.json").write_text(
                json.dumps(settings.model_dump()),
                encoding="utf-8",
            )

            with patch.object(projects_api, "PROJECTS_ROOT", root), patch.object(
                projects_api.pipeline_service, "get_status", return_value=MagicMock(state="running")
            ):
                with self.assertRaises(HTTPException) as raised:
                    projects_api.load_project("Demo")
                self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
