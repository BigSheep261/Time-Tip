"""Regression tests for normalization and portable SQLite backups."""
from __future__ import annotations

from datetime import date
import json
import sys
import tempfile
import unittest
from pathlib import Path
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from app.application.anime_records import normalize_anime_records
from app.application.update_security import expected_sha256, safe_update_filename, validated_http_url
from app.infrastructure.database import DataStore


class AnimeRecordTests(unittest.TestCase):
    def test_legacy_records_and_duplicate_ids_are_normalized(self):
        identifiers = iter(("generated-1", "generated-2"))
        records = normalize_anime_records(
            [
                {
                    "id": "same",
                    "title": "旧版追番",
                    "air_days": [2],
                    "progress": 3,
                },
                {
                    "id": "same",
                    "title": "本地清单",
                    "category": "backlog",
                    "episode_count": 10,
                    "progress": 1,
                },
            ],
            today=date(2026, 9, 18),
            id_factory=lambda: next(identifiers),
        )

        self.assertEqual([record["id"] for record in records], ["same", "generated-1"])
        self.assertTrue(records[0]["legacy_compat"])
        self.assertEqual(records[0]["air_days"], [2])
        self.assertEqual(records[1]["category"], "backlog")


class UpdateSecurityTests(unittest.TestCase):
    def test_update_inputs_are_restricted_to_safe_values(self):
        self.assertEqual(safe_update_filename("../危险 安装包.exe"), "______.exe")
        self.assertEqual(validated_http_url("https://updates.example/app.exe"),
                         "https://updates.example/app.exe")
        with self.assertRaises(ValueError):
            validated_http_url("file:///C:/Windows/notepad.exe")
        with self.assertRaises(ValueError):
            expected_sha256({"sha256": "not-a-digest"})
        self.assertEqual(expected_sha256({"sha256": "A" * 64}), "a" * 64)


class DataStoreBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = DataStore(self.root / "source", migrate_legacy=False)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_zip_round_trip_includes_cover_and_emoji_assets(self):
        original_cover = self.root / "cover.png"
        original_cover.write_bytes(b"cover-bytes")
        saved_cover = self.store.save_cover(str(original_cover), "anime-1")
        self.store.save_anime([
            {
                "id": "anime-1",
                "title": "测试番剧",
                "category": "backlog",
                "episode_count": 12,
                "progress": 2,
                "cover": saved_cover,
            }
        ])
        emoji = self.store.root / "emojis" / "favorites" / "smile.gif"
        emoji.parent.mkdir(parents=True)
        emoji.write_bytes(b"emoji-bytes")
        self.store.write_json("emojis", [{"id": "emoji-1", "path": "favorites/smile.gif"}])

        backup = self.root / "backup.zip"
        self.store.export_data(str(backup))
        with zipfile.ZipFile(backup) as archive:
            self.assertIn("covers/anime-1.png", archive.namelist())
            self.assertIn("emojis/favorites/smile.gif", archive.namelist())
            payload = json.loads(archive.read("data.json"))
            self.assertEqual(payload["collections"]["anime"][0]["cover"], "covers/anime-1.png")

        restored = DataStore(self.root / "restored", migrate_legacy=False)
        try:
            restored.import_data(str(backup))
            self.assertEqual((restored.covers / "anime-1.png").read_bytes(), b"cover-bytes")
            self.assertEqual(
                (restored.root / "emojis" / "favorites" / "smile.gif").read_bytes(),
                b"emoji-bytes",
            )
            self.assertEqual(restored.anime()[0]["cover"], str(restored.covers / "anime-1.png"))
        finally:
            restored.close()

    def test_invalid_payload_is_rejected_before_assets_are_written(self):
        backup = self.root / "invalid.zip"
        with zipfile.ZipFile(backup, "w") as archive:
            archive.writestr(
                "data.json",
                json.dumps({"version": 2, "settings": {}, "collections": {"anime": {}}}),
            )
            archive.writestr("covers/untrusted.png", b"not-written")

        with self.assertRaisesRegex(ValueError, "anime"):
            self.store.import_data(str(backup))
        self.assertFalse((self.store.covers / "untrusted.png").exists())


if __name__ == "__main__":
    unittest.main()
