from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from app.models.runtime_settings import RuntimeSettings
from app.scanner.sdk_log_collector import (
    SdkLogCollector,
    discover_native_log_dirs,
    resolve_native_log_dir,
)


class SdkLogCollectorPathTests(unittest.TestCase):
    def test_resolve_native_log_dir_from_process_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "OptimScan Q"
            log_dir = install_dir / "log"
            log_dir.mkdir(parents=True)
            resolved = resolve_native_log_dir(
                str(install_dir / "Sn3DProcessManager.exe")
            )
            self.assertEqual(resolved, log_dir)

    def test_resolve_native_log_dir_uses_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            override = Path(temp_dir)
            resolved = resolve_native_log_dir(
                r"C:\missing\Sn3DProcessManager.exe",
                str(override),
            )
            self.assertEqual(resolved, override)

    def test_discover_native_log_dirs_includes_syncservice_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir)
            (install_dir / "log").mkdir()
            sync_log = install_dir / "syncservice" / "log"
            sync_log.mkdir(parents=True)

            discovered = discover_native_log_dirs(
                str(install_dir / "Sn3DProcessManager.exe")
            )
            self.assertEqual(len(discovered), 2)
            self.assertIn(install_dir / "log", discovered)
            self.assertIn(sync_log, discovered)


class SdkLogCollectorTailTests(unittest.TestCase):
    def test_tail_appends_only_new_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source"
            dest_dir = Path(temp_dir) / "dest"
            source_dir.mkdir()
            source_file = source_dir / "plugin.log"
            source_file.write_text("line-1\n", encoding="utf-8")

            collector = SdkLogCollector()
            collector._mirror_path = dest_dir / "mirror.log"
            collector._sources_path = dest_dir / "sources.json"
            collector._tail_file(source_file)

            mirror_text = collector._mirror_path.read_text(encoding="utf-8")
            self.assertIn("[plugin.log] line-1", mirror_text)

            source_file.write_text("line-1\nline-2\n", encoding="utf-8")
            collector._tail_file(source_file)

            mirror_text = collector._mirror_path.read_text(encoding="utf-8")
            self.assertEqual(mirror_text.count("line-1"), 1)
            self.assertIn("[plugin.log] line-2", mirror_text)

    def test_tail_handles_truncated_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source"
            dest_dir = Path(temp_dir) / "dest"
            source_dir.mkdir()
            source_file = source_dir / "rotated.log"
            source_file.write_text("old-content-that-is-long\n", encoding="utf-8")

            collector = SdkLogCollector()
            collector._mirror_path = dest_dir / "mirror.log"
            collector._sources_path = dest_dir / "sources.json"
            collector._file_offsets[source_file] = 999

            source_file.write_text("new-content\n", encoding="utf-8")
            collector._tail_file(source_file)

            mirror_text = collector._mirror_path.read_text(encoding="utf-8")
            self.assertIn("[rotated.log] new-content", mirror_text)
            self.assertNotIn("old-content", mirror_text)


class SdkLogCollectorLifecycleTests(unittest.TestCase):
    def test_start_stop_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            install_dir = Path(temp_dir) / "OptimScan Q"
            log_dir = install_dir / "log"
            log_dir.mkdir(parents=True)
            (log_dir / "sdk.log").write_text("native-line\n", encoding="utf-8")

            settings = RuntimeSettings(
                sdk_log_enabled=True,
                sdk_log_dir=str(Path(temp_dir) / "mirrored"),
            )
            settings = settings.model_copy(
                update={
                    "scanner": settings.scanner.model_copy(
                        update={
                            "process_path": str(install_dir / "Sn3DProcessManager.exe"),
                        }
                    )
                }
            )

            collector = SdkLogCollector()
            collector.start(settings)
            self.assertTrue(collector.is_running)

            time.sleep(1.2)

            mirror_files = list((Path(temp_dir) / "mirrored" / "sdk_native").glob("mirror_*.log"))
            self.assertTrue(mirror_files)
            self.assertIn("native-line", mirror_files[0].read_text(encoding="utf-8"))

            collector.stop()
            self.assertFalse(collector.is_running)
            collector.stop()
            self.assertFalse(collector.is_running)


if __name__ == "__main__":
    unittest.main()
