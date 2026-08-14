from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api import markers as markers_api


class MarkersApiTests(unittest.TestCase):
    def test_lists_p3_files_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Markers"
            nested = root / "nested"
            nested.mkdir(parents=True)
            flat_file = root / "flat.p3"
            nested_file = nested / "nested.p3"
            flat_file.write_text("p3", encoding="utf-8")
            nested_file.write_text("p3", encoding="utf-8")

            with patch.object(markers_api, "MARKERS_DIR", root):
                response = markers_api.list_marker_files()

            self.assertEqual(response.folder, str(root.resolve()))
            paths = {entry.path for entry in response.files}
            self.assertIn(str(flat_file.resolve()), paths)
            self.assertIn(str(nested_file.resolve()), paths)


if __name__ == "__main__":
    unittest.main()
