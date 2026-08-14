import unittest

from app.core.runtime_settings_store import _normalize_runtime_settings
from app.models.pipeline_settings import PipelineSettings
from app.models.runtime_settings import RuntimeSettings
from app.models.scanner_settings import ScannerScanParams, ScannerSettings


class RuntimeSettingsMarkersOnlyTests(unittest.TestCase):
    def test_markers_only_clears_import_markers(self) -> None:
        settings = RuntimeSettings(
            scanner=ScannerSettings(
                save_type="stl",
                scan=ScannerScanParams(
                    align_mod=4,
                    scan_markers=True,
                    scan_point_cloud=False,
                ),
            ),
            pipeline=PipelineSettings(import_markers=True, marker_framework_path="C:\\ref.p3"),
        )

        normalized = _normalize_runtime_settings(settings)

        self.assertEqual(normalized.scanner.scan.align_mod, 8)
        self.assertEqual(normalized.scanner.save_type, "p3")
        self.assertFalse(normalized.pipeline.import_markers)


if __name__ == "__main__":
    unittest.main()
