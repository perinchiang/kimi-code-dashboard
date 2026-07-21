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


if __name__ == "__main__":
    unittest.main()
