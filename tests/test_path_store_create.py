import json
import tempfile
import unittest
from pathlib import Path

from app.trajectory.path_store import PathStoreError, create_path_file, read_document


class PathStoreCreateTests(unittest.TestCase):
    def test_create_path_file_writes_empty_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            created = create_path_file(temp_dir, "new_path.json")
            self.assertTrue(created.is_file())
            document = read_document(created)
            self.assertEqual(document["points"], [])
            self.assertEqual(document["nodes"], [])
            self.assertEqual(document["safe_route_ids"], [])
            self.assertEqual(document["safe_routes"], [])

    def test_create_path_file_rejects_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "existing.json"
            target.write_text(json.dumps({"points": [], "nodes": []}), encoding="utf-8")
            with self.assertRaises(PathStoreError):
                create_path_file(temp_dir, "existing.json")


if __name__ == "__main__":
    unittest.main()
