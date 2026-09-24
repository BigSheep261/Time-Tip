"""Tests for the imported lyrics learning feature."""
import os
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from PyQt6.QtCore import QPoint, Qt, QUrl
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QLabel, QMessageBox, QPushButton,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from app.features.lyrics import (
    ENGLISH_TEMPLATE, TEMPLATE, LyricsModule, LyricsSongCard,
    highlighted_lyrics_html, validate_song_payload,
)
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

    def test_english_rows_show_translation_and_keep_vocab_and_splits(self):
        payload = copy.deepcopy(ENGLISH_TEMPLATE)
        payload["song"]["language"] = " English "
        payload["lyrics"][0]["translation"] = "晨光 <img src=x> & 窗户"
        payload["lyrics"][1].pop("translation")
        result = validate_song_payload(payload)
        self.assertEqual(result["language"], "en")
        self.assertNotIn("romaji", result["lyrics"][0])
        rendered = highlighted_lyrics_html(
            result["lyrics"], result["vocab"], result["language"],
            split_points={"line-001": [7]},
            colors={"text": "#EEEEEE", "primary": "#B4A7FF"},
        )
        self.assertIn("晨光 &lt;img src=x&gt; &amp; 窗户", rendered)
        self.assertNotIn("<img", rendered)
        self.assertIn("I welcome a new day.", rendered)
        self.assertIn("vocab:word-001", rendered)
        self.assertEqual(rendered.count("lyricsSplit"), 1)
        self.assertEqual(rendered.count("#B4A7FF"), 1)
        self.assertIn("#EEEEEE", rendered)

    def test_line_language_override_renders_english_translation(self):
        rendered = highlighted_lyrics_html([
            {"id": "one", "language": "en", "text": "Hello", "translation": "你好"},
            {"id": "two", "romaji": "uta", "text": "歌", "translation": "歌曲"},
        ], [], "ja")
        self.assertIn("你好", rendered)
        self.assertIn("uta", rendered)
        self.assertIn("歌曲", rendered)

    def test_documented_templates_are_valid_and_match_ui_templates(self):
        root = Path(__file__).resolve().parents[1] / "docs"
        for name, template in (
            ("lyrics-import-template.json", TEMPLATE),
            ("lyrics-import-template-en.json", ENGLISH_TEMPLATE),
        ):
            with self.subTest(template=name):
                payload = json.loads((root / name).read_text(encoding="utf-8"))
                self.assertEqual(payload, template)
                self.assertEqual(validate_song_payload(payload)["language"], template["song"]["language"])


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

    def _enable_songs(self, *songs):
        self.store.write_json("lyrics_songs", list(songs))
        self.host.modules.register(ModuleSpec("lyrics", "歌词学习", LyricsModule))
        self.assertTrue(self.host.modules.enable("lyrics"))
        return self.host.modules.entries["lyrics"].instance

    def _cards(self, instance):
        return [
            instance.cards_layout.itemAt(index).widget()
            for index in range(instance.cards_layout.count())
            if isinstance(instance.cards_layout.itemAt(index).widget(), LyricsSongCard)
        ]

    def test_language_tabs_filter_existing_songs_and_keep_legacy_chinese(self):
        english = validate_song_payload(ENGLISH_TEMPLATE)
        japanese = validate_song_payload(TEMPLATE)
        legacy = {"id": "legacy", "title": "旧歌曲", "lyrics": [{"id": "one", "text": "你好"}], "vocab": []}
        korean = {**legacy, "id": "korean", "language": "ko"}
        instance = self._enable_songs(english, japanese, legacy, korean)
        for index, expected in (
            (0, [english["id"], japanese["id"], "legacy", "korean"]),
            (1, [japanese["id"]]), (2, [english["id"]]), (3, ["legacy", "korean"]),
        ):
            with self.subTest(tab=index):
                instance.language_tabs.setCurrentIndex(index)
                self.assertEqual([card.song_id for card in self._cards(instance)], expected)
        self.host.modules.publish("data.reloaded")
        self.assertEqual(instance.language_tabs.currentIndex(), 3)
        self.assertEqual([card.song_id for card in self._cards(instance)], ["legacy", "korean"])
        self.assertEqual(instance._song_by_id("legacy")["language"], "zh")

    def test_cancel_delete_keeps_current_song_and_saved_data(self):
        song = validate_song_payload(ENGLISH_TEMPLATE)
        instance = self._enable_songs(song)
        instance.split_points = {song["id"]: {"line-001": [7]}}
        instance._save_splits()
        instance._open_song(song["id"])
        original_splits = self.store.read_json("lyrics_splits", [])
        with patch("app.features.lyrics.QMessageBox.exec", return_value=QMessageBox.StandardButton.No):
            instance.delete_button.click()
        self.assertEqual(instance.songs, [song])
        self.assertEqual(self.store.read_json("lyrics_songs", []), [song])
        self.assertEqual(self.store.read_json("lyrics_splits", []), original_splits)
        self.assertIs(instance.stack.currentWidget(), instance.detail_page)
        self.assertEqual(instance.current_song, song)
        confirmation = instance.page.findChild(QMessageBox)
        self.assertEqual(confirmation.standardButton(confirmation.defaultButton()), QMessageBox.StandardButton.No)

    def test_delete_from_detail_clears_only_target_and_survives_reload(self):
        english = validate_song_payload(ENGLISH_TEMPLATE)
        japanese = validate_song_payload(TEMPLATE)
        instance = self._enable_songs(english, japanese)
        instance.split_points = {
            english["id"]: {"line-001": [7]}, japanese["id"]: {"line-001": [2]},
        }
        instance._save_splits()
        instance.language_tabs.setCurrentIndex(2)
        instance._open_song(english["id"])
        instance._show_word(QUrl("vocab:word-001"))
        self.assertIn("窗户", instance.word_meaning.text())
        with patch("app.features.lyrics.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
            instance.delete_button.click()
        self.assertIsNone(instance.current_song)
        self.assertEqual(instance.lyrics_browser.toPlainText(), "")
        self.assertEqual(instance.word_meaning.text(), "")
        self.assertIs(instance.stack.currentWidget(), instance.library_page)
        self.assertEqual(instance.language_tabs.currentIndex(), 2)
        self.assertEqual(self._cards(instance), [])
        self.assertIn("还没有英语歌曲", instance.cards_layout.itemAt(0).widget().text())
        self.assertEqual(self.store.read_json("lyrics_songs", []), [japanese])
        self.assertEqual(self.store.read_json("lyrics_splits", []), [
            {"song_id": japanese["id"], "line_id": "line-001", "positions": [2]},
        ])
        self.host.modules.disable("lyrics")
        self.host.modules.enable("lyrics")
        reloaded = self.host.modules.entries["lyrics"].instance
        self.assertEqual(reloaded.songs, [japanese])
        self.assertEqual(reloaded.split_points, {japanese["id"]: {"line-001": [2]}})

    def test_card_delete_last_song_preserves_source_and_allows_reimport(self):
        source = Path(self.temp.name) / "english.json"
        source_text = json.dumps(ENGLISH_TEMPLATE, ensure_ascii=False)
        source.write_text(source_text, encoding="utf-8")
        instance = self._enable_songs()
        instance.language_tabs.setCurrentIndex(1)
        with patch("app.features.lyrics.QFileDialog.getOpenFileName", return_value=(str(source), "")):
            instance.import_button.click()
        self.assertEqual(instance.language_tabs.currentIndex(), 2)
        card = self._cards(instance)[0]
        with patch("app.features.lyrics.QMessageBox.exec", return_value=QMessageBox.StandardButton.Yes):
            card.delete_button.click()
        self.assertEqual(self.store.read_json("lyrics_songs", []), [])
        self.assertEqual(self.store.read_json("lyrics_splits", []), [])
        self.assertEqual(source.read_text(encoding="utf-8"), source_text)
        with patch("app.features.lyrics.QFileDialog.getOpenFileName", return_value=(str(source), "")):
            instance.import_button.click()
        self.assertEqual(len(self._cards(instance)), 1)
        self.assertEqual(instance.split_points, {})

    def test_english_detail_supports_vocab_and_local_split(self):
        song = validate_song_payload(ENGLISH_TEMPLATE)
        instance = self._enable_songs(song)
        instance._open_song(song["id"])
        self.assertIn("晨光透过我的窗户。", instance.lyrics_browser.toPlainText())
        instance.lyrics_browser.anchorClicked.emit(QUrl("vocab:word-001"))
        self.assertEqual(instance.word_title.text(), "window")
        self.assertIn("/ˈwɪndəʊ/", instance.word_reading.text())
        instance._selected_lyric_text = "Morning"
        instance._selected_lyric_block_text = song["lyrics"][0]["text"]
        instance._selected_lyric_offset = 0
        instance.split_button.click()
        self.assertEqual(instance.split_points, {song["id"]: {"line-001": [7]}})
        self.assertIn("│", instance.lyrics_browser.toPlainText())
        self.assertIn("晨光透过我的窗户。", instance.lyrics_browser.toPlainText())

    def test_split_edits_preserve_scroll_position_and_word_details(self):
        for language, template in (("en", ENGLISH_TEMPLATE), ("ja", TEMPLATE)):
            with self.subTest(language=language):
                song = validate_song_payload(template)
                base_line = song["lyrics"][0]
                song["lyrics"] = [
                    {**base_line, "id": f"line-{index}", "text": f"{index:03d} {base_line['text']}"}
                    for index in range(100)
                ]
                if "lyrics" not in self.host.modules.entries:
                    instance = self._enable_songs(song)
                else:
                    self.store.write_json("lyrics_songs", [song])
                    self.host.modules.publish("data.reloaded")
                    instance = self.host.modules.entries["lyrics"].instance
                self.host.resize(660, 620)
                self.host.pages.resize(660, 620)
                self.host.show()
                instance._open_song(song["id"])
                self.app.processEvents()
                browser = instance.lyrics_browser
                scrollbar = browser.verticalScrollBar()
                self.assertGreater(scrollbar.maximum(), 0)
                instance._show_word(QUrl("vocab:word-001"))
                word_details = (instance.word_title.text(), instance.word_meaning.text())
                target = song["lyrics"][70]
                expected_positions = []
                second_word = "Morning" if language == "en" else "ここ"
                for word in ("070", second_word):
                    block = browser.document().findBlockByNumber(0)
                    while block.isValid() and not block.text().startswith("070"):
                        block = block.next()
                    self.assertTrue(block.isValid())
                    start = block.text().index(word)
                    cursor = QTextCursor(block)
                    cursor.setPosition(block.position() + start)
                    cursor.setPosition(block.position() + start + len(word), QTextCursor.MoveMode.KeepAnchor)
                    browser.setTextCursor(cursor)
                    browser.ensureCursorVisible()
                    self.app.processEvents()
                    before = scrollbar.value()
                    self.assertGreater(before, 0)
                    instance.split_button.click()
                    self.app.processEvents()
                    self.assertEqual(scrollbar.value(), before)
                    expected_positions.append(target["text"].index(word) + len(word))
                    self.assertEqual(instance.split_points[song["id"]][target["id"]], expected_positions)
                    self.assertEqual((instance.word_title.text(), instance.word_meaning.text()), word_details)

                cursor = browser.document().find("070")
                self.assertFalse(cursor.isNull())
                browser.setTextCursor(cursor)
                browser.ensureCursorVisible()
                self.app.processEvents()
                before = scrollbar.value()
                instance.clear_split_button.click()
                self.assertIn(song["id"], instance.split_points)
                QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=browser.cursorRect(cursor).center())
                instance.clear_split_button.click()
                self.app.processEvents()
                self.assertEqual(scrollbar.value(), before)
                self.assertNotIn(song["id"], instance.split_points)
                self.assertEqual(self.store.read_json("lyrics_splits", []), [])
                self.assertEqual((instance.word_title.text(), instance.word_meaning.text()), word_details)
                self.assertIs(instance.stack.currentWidget(), instance.detail_page)
                instance._show_library()
                instance._open_song(song["id"])
                self.app.processEvents()
                self.assertEqual(scrollbar.value(), 0)

    def _show_lyrics_page(self, instance, song_id):
        self.host.resize(660, 620)
        self.host.pages.resize(660, 620)
        self.host.show()
        self.host.activateWindow()
        instance._open_song(song_id)
        self.app.processEvents()

    def _click_lyric_text(self, instance, text, occurrence=0):
        browser = instance.lyrics_browser
        cursor = browser.document().find(text)
        for _ in range(occurrence):
            cursor = browser.document().find(text, cursor)
        self.assertFalse(cursor.isNull())
        cursor.setPosition(cursor.selectionStart())
        browser.setTextCursor(cursor)
        browser.ensureCursorVisible()
        self.app.processEvents()
        QTest.mouseClick(browser.viewport(), Qt.MouseButton.LeftButton, pos=browser.cursorRect(cursor).center())
        self.app.processEvents()

    def test_clear_mode_requires_clicking_a_row_and_second_confirmation(self):
        song = validate_song_payload(ENGLISH_TEMPLATE)
        song["lyrics"] = [{**song["lyrics"][0], "id": f"line-{index}"} for index in range(3)]
        instance = self._enable_songs(song)
        instance.split_points = {song["id"]: {"line-0": [7, 12], "line-1": [7]}}
        instance._save_splits()
        saved = self.store.read_json("lyrics_splits", [])
        self._show_lyrics_page(instance, song["id"])
        browser = instance.lyrics_browser
        browser.setTextCursor(browser.document().find("Morning"))
        instance.clear_split_button.click()
        self.assertTrue(instance._clear_split_mode)
        self.assertIsNone(instance._clear_split_line_id)
        self.assertFalse(instance.split_button.isEnabled())
        self.assertEqual(self.store.read_json("lyrics_splits", []), saved)
        instance.clear_split_button.click()
        self.assertEqual(self.store.read_json("lyrics_splits", []), saved)
        self.assertIn("尚未选择", instance.lyrics_hint.text())
        self._click_lyric_text(instance, "comes", 0)
        self.assertEqual(instance._clear_split_line_id, "line-0")
        self._click_lyric_text(instance, "comes", 1)
        self.assertEqual(instance._clear_split_line_id, "line-1")
        self.assertEqual(len(browser.extraSelections()), 2)
        self.assertEqual(self.store.read_json("lyrics_splits", []), saved)
        instance.clear_split_button.click()
        self.assertEqual(instance.split_points, {song["id"]: {"line-0": [7, 12]}})
        self.assertFalse(instance._clear_split_mode)
        self.assertEqual(browser.extraSelections(), [])
        self.assertTrue(instance.split_button.isEnabled())
        self.assertIn("已清除第 2 行", instance.lyrics_hint.text())
        self.host.modules.publish("data.reloaded")
        self.assertEqual(instance.split_points, {song["id"]: {"line-0": [7, 12]}})

    def test_clear_mode_selects_japanese_romaji_or_translation_without_text_matching(self):
        song = validate_song_payload(TEMPLATE)
        song["lyrics"] = [{**song["lyrics"][0], "id": f"line-{index}"} for index in range(2)]
        instance = self._enable_songs(song)
        instance.split_points = {song["id"]: {"line-0": [2], "line-1": [2, 4]}}
        instance._save_splits()
        self._show_lyrics_page(instance, song["id"])
        instance.clear_split_button.click()
        self._click_lyric_text(instance, "koko", 0)
        self.assertEqual(instance._clear_split_line_id, "line-0")
        self._click_lyric_text(instance, "这里填写", 1)
        self.assertEqual(instance._clear_split_line_id, "line-1")
        selections = instance.lyrics_browser.extraSelections()
        self.assertEqual(len(selections), 3)
        self.assertEqual(selections[0].cursor.selectedText(), song["lyrics"][1]["romaji"])
        self.assertEqual(selections[-1].cursor.selectedText(), song["lyrics"][1]["translation"])
        instance.clear_split_button.click()
        self.assertEqual(instance.split_points, {song["id"]: {"line-0": [2]}})

    def test_clear_mode_empty_space_no_splits_and_escape_are_safe(self):
        song = validate_song_payload(ENGLISH_TEMPLATE)
        instance = self._enable_songs(song)
        instance.split_points = {song["id"]: {"line-001": [7]}}
        instance._save_splits()
        self._show_lyrics_page(instance, song["id"])
        instance.clear_split_button.click()
        self._click_lyric_text(instance, "window")
        self.assertEqual(instance.word_title.text(), "点击加粗词查看详情")
        QTest.mouseClick(instance.lyrics_browser.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(10, instance.lyrics_browser.viewport().height() - 5))
        self.assertIsNone(instance._clear_split_line_id)
        instance.clear_split_button.click()
        self.assertIn("尚未选择", instance.lyrics_hint.text())
        self._click_lyric_text(instance, "welcome")
        instance.clear_split_button.click()
        self.assertIn("没有分割点", instance.lyrics_hint.text())
        self.assertEqual(instance.split_points, {song["id"]: {"line-001": [7]}})
        instance.clear_split_button.click()
        self._click_lyric_text(instance, "window")
        instance.lyrics_browser.setFocus()
        self.app.processEvents()
        QTest.keyClick(instance.lyrics_browser, Qt.Key.Key_Escape)
        self.assertFalse(instance._clear_split_mode)
        self.assertEqual(instance.lyrics_browser.extraSelections(), [])
        self.assertEqual(instance.split_points, {song["id"]: {"line-001": [7]}})

    def test_clear_mode_resets_when_leaving_or_reloading_a_song(self):
        english = validate_song_payload(ENGLISH_TEMPLATE)
        japanese = validate_song_payload(TEMPLATE)
        instance = self._enable_songs(english, japanese)
        self._show_lyrics_page(instance, english["id"])
        for leave in (instance._show_library, lambda: instance._open_song(japanese["id"]),
                      lambda: self.host.modules.publish("data.reloaded")):
            instance._open_song(english["id"])
            instance.clear_split_button.click()
            self._click_lyric_text(instance, "window")
            leave()
            self.assertFalse(instance._clear_split_mode)
            self.assertIsNone(instance._clear_split_line_id)
            self.assertEqual(instance.lyrics_browser.extraSelections(), [])
            self.assertEqual(instance.clear_split_button.text(), "清除本行分割")

    def test_template_dialog_switches_languages_and_copies_selection(self):
        instance = self._enable_songs()
        instance.language_tabs.setCurrentIndex(2)
        def inspect_dialog():
            dialog = instance.page.findChild(QDialog)
            selector = dialog.findChild(QComboBox)
            editor = dialog.findChild(QTextEdit)
            self.assertEqual(json.loads(editor.toPlainText()), ENGLISH_TEMPLATE)
            selector.setCurrentIndex(0)
            self.assertEqual(json.loads(editor.toPlainText()), TEMPLATE)
            selector.setCurrentIndex(1)
            copy_button = next(button for button in dialog.findChildren(QPushButton) if button.text() == "复制模板")
            with patch("app.features.lyrics.QApplication.clipboard") as clipboard:
                copy_button.click()
                copied = clipboard.return_value.setText.call_args.args[0]
                self.assertEqual(json.loads(copied), ENGLISH_TEMPLATE)
            return QDialog.DialogCode.Rejected
        with patch("app.features.lyrics.QDialog.exec", side_effect=inspect_dialog):
            instance.template_button.click()


if __name__ == "__main__":
    unittest.main()

