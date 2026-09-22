"""Tests for the imported lyrics learning feature."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from PyQt6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from app.features.lyrics import LyricsModule, highlighted_lyrics_html, validate_song_payload
from app.infrastructure.store import Store
from app.presentation.module_runtime import ModuleManager, ModuleSpec


class LyricsDomainTests(unittest.TestCase):
    def test_validation_normalizes_optional_fields_and_rejects_duplicates(self):
        payload = {
            "version": 1,
            "song": {"id": "song-1", "title": "夜", "artist": "A"},
            "lyrics": [{"id": "line-1", "text": "夜明けの歌"}],
            "vocab": [{
                "id": "word-1", "surface": "夜明け", "meaning": "黎明"
            }],
        }
        result = validate_song_payload(payload)
        self.assertEqual(result["cover"], "")
        self.assertEqual(result["vocab"][0]["reading"], "")
        with self.assertRaisesRegex(ValueError, "生词原文重复"):
            validate_song_payload({
                **payload,
                "vocab": [
                    {"id": "a", "surface": "夜", "meaning": "夜"},
                    {"id": "b", "surface": "夜", "meaning": "夜间"},
                ],
            })

    def test_highlighted_html_escapes_text_and_links_longest_match(self):
        html = highlighted_lyrics_html(
            [{"id": "line", "text": "A+B 夜明け"}],
            [
                {"id": "short", "surface": "夜", "meaning": "夜"},
                {"id": "long", "surface": "夜明け", "meaning": "黎明"},
            ],
        )
        self.assertIn("vocab:long", html)
        self.assertNotIn("vocab:short", html)
        self.assertIn("A+B", html)
        self.assertNotIn("<script>", html)

    def test_japanese_payload_has_three_lyric_fields_and_split_marker(self):
        payload = {
            "version": 1,
            "song": {"id": "song-ja", "title": "夜", "language": "ja"},
            "lyrics": [{
                "id": "line-1", "romaji": "yoake", "text": "夜明けの歌",
                "translation": "黎明之歌",
            }],
            "vocab": [{"id": "word-1", "surface": "夜明け", "meaning": "黎明"}],
        }
        result = validate_song_payload(payload)
        line = result["lyrics"][0]
        self.assertEqual(result["language"], "ja")
        self.assertEqual((line["romaji"], line["text"], line["translation"]),
                         ("yoake", "夜明けの歌", "黎明之歌"))
        self.assertNotIn("split_at", line)
        rendered = highlighted_lyrics_html(
            result["lyrics"], result["vocab"], result["language"],
            split_points={"line-1": [2, 3]},
        )
        self.assertIn("yoake", rendered)
        self.assertIn("黎明之歌", rendered)
        self.assertIn("<strong>", rendered)
        self.assertEqual(rendered.count("lyricsSplit"), 2)

    def test_theme_colors_are_applied_to_japanese_rows(self):
        lyrics = [{
            "id": "line", "romaji": "yoake", "text": "夜明け", "translation": "黎明"
        }]
        vocab = [{"id": "word", "surface": "夜明け", "meaning": "黎明"}]
        light = highlighted_lyrics_html(
            lyrics, vocab, "ja", colors={"text": "#111111", "muted": "#222222", "primary": "#333333"}
        )
        dark = highlighted_lyrics_html(
            lyrics, vocab, "ja", colors={"text": "#EEEEEE", "muted": "#AAAAAA", "primary": "#B4A7FF"}
        )
        self.assertIn("#111111", light)
        self.assertIn("#EEEEEE", dark)
        self.assertIn('style="color:#EEEEEE;', dark)
        self.assertNotEqual(light, dark)


class LyricsModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / "settings.ini"))
        self.host = QWidget()
        self.host.store = self.store
        self.host.pages = QStackedWidget(self.host)
        self.host.navigation = QVBoxLayout()
        self.host.modules = ModuleManager(self.host, self.host.pages, self.host.navigation)
        self.host.notify = lambda text: None

    def tearDown(self):
        self.host.deleteLater()
        self.app.sendPostedEvents(None, 52)
        self.store.close()
        self.temp.cleanup()

    def test_song_collection_round_trips_through_backup(self):
        song = {
            "id": "song-1",
            "title": "夜",
            "artist": "A",
            "lyrics": [{"id": "line-1", "text": "夜明け"}],
            "vocab": [{"id": "word-1", "surface": "夜明け", "reading": "よあけ", "meaning": "黎明", "note": ""}],
        }
        self.store.write_json("lyrics_songs", [song])
        backup = Path(self.temp.name) / "backup.json"
        self.store.export_data(str(backup))
        restored = Store(str(Path(self.temp.name) / "restored.ini"))
        try:
            restored.import_data(str(backup))
            self.assertEqual(restored.read_json("lyrics_songs", []), [song])
        finally:
            restored.close()

    def test_module_loads_saved_song_and_reloads_after_data_event(self):
        self.store.write_json("lyrics_songs", [{
            "id": "song-1",
            "title": "夜",
            "artist": "A",
            "lyrics": [{"id": "line-1", "text": "夜明け"}],
            "vocab": [{"id": "word-1", "surface": "夜明け", "reading": "よあけ", "meaning": "黎明", "note": ""}],
        }])
        self.host.modules.register(ModuleSpec("lyrics", "歌词学习", LyricsModule))
        self.assertTrue(self.host.modules.enable("lyrics"))
        instance = self.host.modules.entries["lyrics"].instance
        self.assertEqual([song["id"] for song in instance.songs], ["song-1"])
        self.store.write_json("lyrics_songs", [])
        self.host.modules.publish("data.reloaded")
        self.assertEqual(instance.songs, [])
        self.assertTrue(self.host.modules.disable("lyrics"))
        self.assertIsNone(self.host.modules.entries["lyrics"].instance)

    def test_split_points_are_local_and_support_multiple_positions(self):
        self.store.write_json("lyrics_songs", [{
            "id": "song-1",
            "title": "夜",
            "lyrics": [{"id": "line-1", "text": "夜明けの歌"}],
            "vocab": [],
        }])
        self.host.modules.register(ModuleSpec("lyrics", "歌词学习", LyricsModule))
        self.assertTrue(self.host.modules.enable("lyrics"))
        instance = self.host.modules.entries["lyrics"].instance
        instance._open_song("song-1")

        instance._selected_lyric_text = "夜明け"
        instance._selected_lyric_block_text = "夜明けの歌"
        instance._selected_lyric_offset = 0
        instance._split_selected_line()
        instance._selected_lyric_text = "明"
        instance._selected_lyric_offset = 1
        instance._split_selected_line()

        self.assertEqual(instance.split_points, {"song-1": {"line-1": [2, 3]}})
        self.assertNotIn("split_at", instance.songs[0]["lyrics"][0])
        self.assertEqual(
            self.store.read_json("lyrics_splits", []),
            [{"song_id": "song-1", "line_id": "line-1", "positions": [2, 3]}],
        )
        backup = Path(self.temp.name) / "split-backup.json"
        self.store.export_data(str(backup))
        restored = Store(str(Path(self.temp.name) / "split-restored.ini"))
        try:
            restored.import_data(str(backup))
            self.assertEqual(
                restored.read_json("lyrics_splits", []),
                [{"song_id": "song-1", "line_id": "line-1", "positions": [2, 3]}],
            )
        finally:
            restored.close()


if __name__ == "__main__":
    unittest.main()

