from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.app_state import app_state
from app.trajectory.kuka_folder_watcher import KukaFolderWatcher, KukaFolderWatcherSettings

SAMPLE_KUKA = {
    "path_settings": {"version": "1.0"},
    "paths": [
        {
            "index": 0,
            "point_type": "transition",
            "comment": "home",
            "arm_joint_angles": {
                "J1": 0.0,
                "J2": 0.0,
                "J3": 0.0,
                "J4": 0.0,
                "J5": 0.0,
                "J6": 0.0,
            },
            "arm_motion_paras": {"speed": 50.0, "acceleration": 50.0},
            "turntable": {"angle": 0.0, "speed": 50.0, "acceleration": 50.0},
        }
    ],
}


class KukaFolderWatcherTests(unittest.TestCase):
    def test_imports_new_json_to_locale_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "kuka"
            output_root = Path(temp_dir) / "output"
            source_root.mkdir()
            output_root.mkdir()
            source_file = source_root / "scan_path_demo.json"
            source_file.write_text(json.dumps(SAMPLE_KUKA), encoding="utf-8")
            old_mtime = time.time() - 5
            import os

            os.utime(source_file, (old_mtime, old_mtime))

            app_state.ui_locale = "en"
            watcher = KukaFolderWatcher(
                KukaFolderWatcherSettings(
                    source_dir=source_root,
                    stable_age_s=0.0,
                    stable_check_interval_s=0.0,
                )
            )

            with patch("app.trajectory.kuka_import.KUKA_TRAJECTORIES_DIR", source_root), patch(
                "app.trajectory.kuka_import.PARSED_TRAJECTORIES_DIR", output_root
            ), patch(
                "app.trajectory.kuka_import.pipeline_service.get_status",
                return_value=MagicMock(state="idle"),
            ), patch(
                "app.trajectory.kuka_import.update_runtime_settings",
                side_effect=lambda value: value,
            ) as update_settings_mock:
                watcher.process_once()

            target = output_root / "New trajectory.json"
            self.assertTrue(target.is_file())
            self.assertFalse(source_file.exists())
            update_settings_mock.assert_not_called()

    def test_skips_import_when_pipeline_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "kuka"
            output_root = Path(temp_dir) / "output"
            source_root.mkdir()
            output_root.mkdir()
            source_file = source_root / "scan_path_demo.json"
            source_file.write_text(json.dumps(SAMPLE_KUKA), encoding="utf-8")
            old_mtime = time.time() - 5
            import os

            os.utime(source_file, (old_mtime, old_mtime))

            watcher = KukaFolderWatcher(
                KukaFolderWatcherSettings(
                    source_dir=source_root,
                    stable_age_s=0.0,
                    stable_check_interval_s=0.0,
                )
            )

            with patch("app.trajectory.kuka_import.KUKA_TRAJECTORIES_DIR", source_root), patch(
                "app.trajectory.kuka_import.PARSED_TRAJECTORIES_DIR", output_root
            ), patch(
                "app.trajectory.kuka_import.pipeline_service.get_status",
                return_value=MagicMock(state="running"),
            ):
                watcher.process_once()

            self.assertFalse(any(output_root.iterdir()))


if __name__ == "__main__":
    unittest.main()
