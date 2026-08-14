from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app.api import paths as paths_api
from app.models.paths import KukaTrajectoryImportRequest

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


class PathsImportKukaTests(unittest.TestCase):
    def test_rejects_source_outside_kuka_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = Path(temp_dir) / "outside.json"
            outside.write_text(json.dumps(SAMPLE_KUKA), encoding="utf-8")
            kuka_root = Path(temp_dir) / "kuka"
            output_root = Path(temp_dir) / "output"
            kuka_root.mkdir()
            output_root.mkdir()

            payload = KukaTrajectoryImportRequest(
                source_path=str(outside),
                output_folder=str(output_root),
                output_filename="parsed.json",
            )

            with patch.object(paths_api, "KUKA_TRAJECTORIES_DIR", kuka_root), patch.object(
                paths_api, "PARSED_TRAJECTORIES_DIR", output_root
            ), patch.object(
                paths_api.pipeline_service,
                "get_status",
                return_value=type("Status", (), {"state": "idle"})(),
            ):
                with self.assertRaises(HTTPException) as raised:
                    paths_api.import_kuka_trajectory(payload)
                self.assertEqual(raised.exception.status_code, 400)

    def test_writes_to_fixed_output_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            kuka_root = Path(temp_dir) / "kuka"
            output_root = Path(temp_dir) / "output"
            kuka_root.mkdir()
            output_root.mkdir()
            source = kuka_root / "scan_path_demo.json"
            source.write_text(json.dumps(SAMPLE_KUKA), encoding="utf-8")

            payload = KukaTrajectoryImportRequest(
                source_path=str(source),
                output_folder="C:\\ignored\\folder",
                output_filename="demo_parsed.json",
            )

            with patch.object(paths_api, "KUKA_TRAJECTORIES_DIR", kuka_root), patch.object(
                paths_api, "PARSED_TRAJECTORIES_DIR", output_root
            ), patch.object(
                paths_api.pipeline_service,
                "get_status",
                return_value=type("Status", (), {"state": "idle"})(),
            ):
                response = paths_api.import_kuka_trajectory(payload)

            target = output_root / "demo_parsed.json"
            self.assertTrue(target.is_file())
            self.assertEqual(response.filename, "demo_parsed.json")


if __name__ == "__main__":
    unittest.main()
