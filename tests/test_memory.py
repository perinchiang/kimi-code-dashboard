import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from routes import memory as memory_route


class MemoryItemsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def _create_l0_db(self, directory: str) -> Path:
        path = Path(directory) / "vectors.db"
        connection = sqlite3.connect(path)
        connection.execute(
            """
            CREATE TABLE l0_conversations (
                record_id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                session_id TEXT DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                message_text TEXT NOT NULL,
                recorded_at TEXT DEFAULT '',
                timestamp INTEGER DEFAULT 0
            )
            """
        )
        rows = [
            (f"r{index}", "kimi-default", "", "user", f"message {index}", f"2026-07-21T00:00:0{index}Z", index)
            for index in range(6)
        ]
        connection.executemany(
            "INSERT INTO l0_conversations VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )
        connection.execute(
            "INSERT INTO l0_conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("other-session", "other-session", "", "user", "other message", "2026-07-21T01:00:00Z", 99),
        )
        connection.commit()
        connection.close()
        return path

    def test_l0_pages_through_all_records_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = self._create_l0_db(directory)
            with patch.object(memory_route, "L0_DB_PATH", db_path):
                first = self.client.get("/api/memory/items?level=l0&limit=3").get_json()
                self.assertEqual(first["total"], 6)
                self.assertEqual(first["returned"], 3)
                self.assertTrue(first["has_more"])
                self.assertEqual([item["record_id"] for item in first["items"]], ["r5", "r4", "r3"])

                cursor = first["next_cursor"]
                second = self.client.get(
                    "/api/memory/items",
                    query_string={
                        "level": "l0",
                        "limit": 3,
                        "before_timestamp": cursor["timestamp"],
                        "before_record_id": cursor["record_id"],
                    },
                ).get_json()

        self.assertEqual(second["total"], 6)
        self.assertEqual(second["returned"], 3)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual([item["record_id"] for item in second["items"]], ["r2", "r1", "r0"])

    def test_l0_search_applies_before_pagination(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = self._create_l0_db(directory)
            with patch.object(memory_route, "L0_DB_PATH", db_path):
                response = self.client.get(
                    "/api/memory/items",
                    query_string={"level": "l0", "limit": 2, "q": "message 4"},
                )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["returned"], 1)
        self.assertFalse(data["has_more"])
        self.assertEqual(data["items"][0]["record_id"], "r4")

    def test_memory_summary_uses_exact_l0_total(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = self._create_l0_db(directory)
            with patch.object(memory_route, "L0_DB_PATH", db_path), \
                    patch.object(memory_route, "http_post", return_value={"results": ""}), \
                    patch.object(memory_route, "http_get", return_value={}):
                response = self.client.get("/api/memory")

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["l0"], 6)
        self.assertEqual(data["l1"], 0)
        self.assertEqual(data["l2"], 0)
        self.assertEqual(data["l3"], 0)


if __name__ == "__main__":
    unittest.main()
