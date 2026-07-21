import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import r2_uploader


class ArtifactBlobSourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.saved_cache = r2_uploader._blob_sources_cache.copy()
        r2_uploader._blob_sources_cache.update(signature=None, data=None)

    def tearDown(self):
        r2_uploader._blob_sources_cache.clear()
        r2_uploader._blob_sources_cache.update(self.saved_cache)

    def test_blob_sources_rescan_when_wire_signature_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory)
            wire = sessions / "workspace" / "session_test" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text("first\n", encoding="utf-8")

            with patch.object(r2_uploader, "SESSIONS_DIR", sessions), \
                    patch.object(r2_uploader, "_scan_blob_sources_uncached", return_value={"sha": "ai"}) as scan:
                self.assertEqual(r2_uploader._scan_blob_sources(), {"sha": "ai"})
                self.assertEqual(r2_uploader._scan_blob_sources(), {"sha": "ai"})
                scan.assert_called_once_with()

                wire.write_text("second content\n", encoding="utf-8")
                self.assertEqual(r2_uploader._scan_blob_sources(), {"sha": "ai"})
                self.assertEqual(scan.call_count, 2)


class ArtifactFileDiscoveryTests(unittest.TestCase):
    _PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24

    def test_unindexed_files_are_discovered_and_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            files_dir = Path(directory)
            indexed_id = "f_indexed"
            unindexed_id = "f_unindexed-target"
            (files_dir / indexed_id).write_bytes(self._PNG_HEADER)
            (files_dir / unindexed_id).write_bytes(self._PNG_HEADER + b"target")
            (files_dir / "index.json").write_text(
                json.dumps({
                    "version": 1,
                    "files": [{
                        "id": indexed_id,
                        "name": "indexed.png",
                        "media_type": "image/png",
                        "size": len(self._PNG_HEADER),
                        "created_at": "2026-01-01T00:00:00Z",
                    }],
                }),
                encoding="utf-8",
            )

            with patch.object(r2_uploader, "FILES_DIR", files_dir), \
                    patch.object(r2_uploader, "CACHE_PATH", files_dir / "cache.json"), \
                    patch.object(r2_uploader, "load_image_bed_config", return_value={"enabled": False}):
                listed = r2_uploader.list_artifacts(file_type="image", limit=100)
                ids = [item["id"] for item in listed["files"]]
                self.assertEqual(ids.count(indexed_id), 1)
                self.assertIn(unindexed_id, ids)

                resolved = r2_uploader.resolve_file_artifact(unindexed_id)
                self.assertIsNotNone(resolved)
                path, entry = resolved
                self.assertEqual(path.name, unindexed_id)
                self.assertEqual(entry["media_type"], "image/png")
                self.assertEqual(entry["size"], len(self._PNG_HEADER) + len(b"target"))

                all_items = r2_uploader.list_all_artifacts(file_type="image", limit=100)["items"]
                self.assertIn(unindexed_id, [item["id"] for item in all_items])


if __name__ == "__main__":
    unittest.main()
