import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtGui import QFont, QFontDatabase, QTextCursor, QTextListFormat
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.infrastructure.database import DataStore
from app.infrastructure.memo_transfer import export_memos, read_memos
from app.infrastructure.store import Store
from app.presentation.window import TimeTipWindow


class MemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"):
            if Path(path).exists():
                QFontDatabase.addApplicationFont(path)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.folder.name) / "settings.ini"))
        self.window = TimeTipWindow(self.store)
        self.window.timer.stop()

    def dispose(self):
        self.window.quitting = True
        self.window.geometry_timer.stop()
        self.window.close()
        self.window.tray.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def tearDown(self):
        self.dispose()
        self.folder.cleanup()

    def restart(self):
        self.dispose()
        self.window = TimeTipWindow(Store(self.store.settings.fileName()))
        self.window.timer.stop()

    def add(self, title="中文笔记", text="保留这段内容"):
        self.window.add_memo()
        self.window.memo_title.setText(title)
        self.window.memo_edit.setPlainText(text)
        self.window.save_memo()
        return self.window.active_memo_id

    def test_rich_format_only_changes_autosave_and_survive_switch_and_restart(self):
        first = self.add()
        before = self.window.memos[0].copy()
        editor = self.window.memo_edit
        editor.selectAll()
        bar = self.window.memo_format
        with patch("app.presentation.memos.memo_timestamp", return_value="2026-09-14T12:00:01+08:00"):
            bar.bold_action.trigger()
            bar.italic_action.trigger()
            bar.underline_action.trigger()
            bar.font_size.setValue(22)
            bar.set_family(QFont("Microsoft YaHei"))
        QTest.qWait(600)
        saved = self.store.read_json("memos", [])[0]
        self.assertEqual(saved["text"], before["text"])
        self.assertNotEqual(saved["html"], before["html"])
        self.assertEqual(saved["edited_at"], "2026-09-14T12:00:01+08:00")
        self.add("第二条")
        self.window._select_list_id(self.window.memo_list, first)
        self.assertTrue(self.window.memo_format.bold_action.isChecked())
        self.restart()
        cursor = self.window.memo_edit.document().find("保留")
        fmt = cursor.charFormat()
        self.assertGreaterEqual(fmt.fontWeight(), QFont.Weight.Bold)
        self.assertTrue(fmt.fontItalic())
        self.assertTrue(fmt.fontUnderline())
        self.assertEqual(fmt.fontPointSize(), 22)
        self.assertIn("Microsoft YaHei", fmt.fontFamilies())
        self.assertEqual(self.window.memos[0]["edited_at"], saved["edited_at"])

    def test_edit_and_save_times_are_distinct_and_viewing_does_not_change_them(self):
        with patch("app.presentation.memos.memo_timestamp", return_value="2026-09-14T09:00:00+08:00"):
            first = self.add()
        with patch("app.presentation.memos.memo_timestamp", return_value="2026-09-14T10:00:00+08:00"):
            self.window.memo_title.setText("仅改标题")
        self.assertIn("09:00:00", self.window.memo_saved_at_label.text())
        self.assertIn("10:00:00", self.window.memo_edited_at_label.text())
        with patch("app.presentation.memos.memo_timestamp", return_value="2026-09-14T10:00:01+08:00"):
            self.window.save_memo()
        saved = self.window.memos[0].copy()
        self.assertNotEqual(saved["saved_at"], saved["edited_at"])
        self.add("另一条")
        self.window._select_list_id(self.window.memo_list, first)
        self.window.save_memo()
        self.restart()
        self.assertEqual(self.window.memos[0], saved)
        with patch("app.presentation.memos.memo_timestamp", return_value="2026-09-14T11:00:00+08:00"):
            self.window.memo_save_button.click()
        self.assertEqual(self.window.memos[0]["edited_at"], saved["edited_at"])
        self.assertEqual(self.window.memos[0]["saved_at"], "2026-09-14T11:00:00+08:00")

    def test_table_editing_persists_cells_and_dimensions(self):
        self.add(text="表格示例\n")
        editor = self.window.memo_edit
        editor.moveCursor(QTextCursor.MoveOperation.End)
        table = self.window.memo_format.insert_table(2, 3)
        editor.insertPlainText("项目名称")
        self.window.memo_format.edit_table("row_add")
        self.window.memo_format.edit_table("column_add")
        self.assertEqual((table.rows(), table.columns()), (3, 4))
        self.window.save_memo()
        self.restart()
        editor = self.window.memo_edit
        cursor = editor.document().find("项目名称")
        table = cursor.currentTable()
        self.assertIsNotNone(table)
        self.assertEqual((table.rows(), table.columns()), (3, 4))
        editor.setTextCursor(cursor)
        self.window.memo_format.edit_table("row_remove")
        self.window.memo_format.edit_table("column_remove")
        self.assertEqual((table.rows(), table.columns()), (2, 3))
        self.window.memo_format.edit_table("remove")
        self.assertNotIn("<table", editor.toHtml())

    def test_lists_and_keyboard_formatting(self):
        self.add(text="第一项\n第二项")
        self.window.show()
        self.window._switch_page(3)
        self.app.processEvents()
        editor = self.window.memo_edit
        editor.setFocus()
        editor.selectAll()
        QTest.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertGreaterEqual(editor.currentCharFormat().fontWeight(), QFont.Weight.Bold)
        self.window.memo_format.set_list(QTextListFormat.Style.ListDecimal)
        self.assertEqual(editor.document().firstBlock().textList().count(), 2)
        self.window.save_memo()
        self.restart()
        editor = self.window.memo_edit
        self.assertEqual(editor.document().firstBlock().textList().format().style(), QTextListFormat.Style.ListDecimal)
        editor.selectAll()
        self.window.memo_format.remove_list()
        self.assertIsNone(editor.document().firstBlock().textList())

    def test_native_list_move_preserves_pending_edit_selection_and_restart_order(self):
        ids = [self.add(title) for title in ("一", "二", "三")]
        view = self.window.memo_list
        self.assertTrue(view.dragEnabled())
        self.assertTrue(view.acceptDrops())
        self.window.memo_edit.insertPlainText("尚未自动保存")
        self.window.memo_edit.selectAll()
        selected = self.window.memo_edit.textCursor().selectedText()
        self.assertTrue(view.model().moveRow(QModelIndex(), 2, QModelIndex(), 0))
        self.assertEqual(self.window.active_memo_id, ids[2])
        self.assertEqual(self.window.memo_edit.textCursor().selectedText(), selected)
        self.assertEqual([m["id"] for m in self.store.read_json("memos", [])], [ids[2], ids[0], ids[1]])
        self.restart()
        self.assertEqual([m["id"] for m in self.window.memos], [ids[2], ids[0], ids[1]])
        self.assertIn("尚未自动保存", self.window.memo_edit.toPlainText())

    def test_export_current_and_all_then_import_append_with_new_ids(self):
        self.add("一")
        second = self.add("二")
        self.window.memo_edit.selectAll()
        self.window.memo_format.bold_action.trigger()
        current_path = str(Path(self.folder.name) / "current.json")
        all_path = str(Path(self.folder.name) / "all.json")
        with patch("app.presentation.memos.QFileDialog.getSaveFileName", return_value=(current_path, "")):
            self.window.export_memos(current_only=True)
        current = json.loads(Path(current_path).read_text(encoding="utf-8"))
        self.assertEqual([m["id"] for m in current["memos"]], [second])
        self.assertIn("font-weight:700", current["memos"][0]["html"])
        self.assertNotIn("settings", current)
        with patch("app.presentation.memos.QFileDialog.getSaveFileName", return_value=(all_path, "")):
            self.window.export_memos()
        before = self.window.memos.copy()
        self.store.set("work", "42")
        with patch("app.presentation.memos.QFileDialog.getOpenFileName", return_value=(all_path, "")):
            self.window.import_memos()
        self.assertEqual([m["title"] for m in self.window.memos], ["一", "二", "一", "二"])
        self.assertEqual(len({m["id"] for m in self.window.memos}), 4)
        self.assertEqual(self.window.memos[:2], before)
        self.assertEqual(self.window.memos[3]["html"], before[1]["html"])
        self.assertEqual(self.window.memos[3]["edited_at"], before[1]["edited_at"])
        self.assertEqual(self.store.get("work"), "42")
        self.restart()
        self.assertEqual(len(self.window.memos), 4)

    def test_legacy_plaintext_keeps_literal_markup_and_unknown_timestamps(self):
        legacy = {"id": "old", "title": "旧笔记", "text": "<b>不是加粗</b>\n第二行"}
        self.store.write_json("memos", [legacy])
        self.restart()
        self.assertEqual(self.window.memo_edit.toPlainText(), legacy["text"])
        self.assertIn("暂无记录", self.window.memo_saved_at_label.text())
        self.assertIn("暂无记录", self.window.memo_edited_at_label.text())
        self.window.save_memo()
        self.assertEqual(self.store.read_json("memos", []), [legacy])

    def test_failed_import_and_cancellation_do_not_partially_change_data(self):
        self.add()
        original = self.store.read_json("memos", [])
        path = str(Path(self.folder.name) / "bad.json")
        invalid_payloads = ["{", json.dumps([{"title": "有效", "text": "内容"}, {"title": "缺少内容"}]),
                            json.dumps({"format": "timetip-memos", "version": 999, "memos": []}),
                            json.dumps([{"title": "错误时间", "text": "", "edited_at": 7}])]
        for payload in invalid_payloads:
            Path(path).write_text(payload, encoding="utf-8")
            with patch("app.presentation.memos.QFileDialog.getOpenFileName", return_value=(path, "")):
                self.window.import_memos()
            self.assertEqual(self.store.read_json("memos", []), original)
            self.assertIn("导入失败", self.window.memo_transfer_feedback.text())
        with patch("app.presentation.memos.QFileDialog.getOpenFileName", return_value=("", "")):
            self.window.import_memos()
        self.assertEqual(self.store.read_json("memos", []), original)

    def test_save_failure_keeps_dirty_content_and_original_save_timestamp(self):
        self.add()
        before = self.window.memos[0].copy()
        self.window.memo_edit.insertPlainText("未保存")
        with patch.object(self.store, "write_json", side_effect=sqlite3.OperationalError("disk full")):
            self.assertFalse(self.window.save_memo())
            self.assertTrue(self.window._memo_dirty)
            self.assertEqual(self.window.memos[0]["saved_at"], before["saved_at"])
            self.assertIn("保存失败", self.window.memo_status.text())
        self.assertTrue(self.window.save_memo())
        self.assertIn("未保存", self.store.read_json("memos", [])[0]["text"])

    def test_full_backup_and_memo_backup_roundtrip_both_backends(self):
        self.add()
        self.window.memo_format.insert_table(2, 2)
        self.window.memo_edit.insertPlainText("表格内容")
        self.window.save_memo()
        records = self.window.memos.copy()
        for sqlite in (False, True):
            with self.subTest(sqlite=sqlite):
                backend = DataStore(str(Path(self.folder.name) / "db")) if sqlite else self.store
                backend.write_json("memos", records)
                full_path = str(Path(self.folder.name) / "full.json")
                backend.export_data(full_path)
                self.assertEqual(read_memos(full_path)[0]["html"], records[0]["html"])
                backend.write_json("memos", [])
                backend.import_data(full_path)
                self.assertEqual(backend.read_json("memos", []), records)
                memo_path = str(Path(self.folder.name) / "memo.json")
                export_memos(memo_path, backend.read_json("memos", []))
                self.assertEqual(read_memos(memo_path)[0]["edited_at"], records[0]["edited_at"])
                if sqlite:
                    backend.close()

    def test_rich_memo_layout_light_and_dark_at_minimum_and_default_size(self):
        self.add("项目记录", "今天的计划\n用富文本整理想法。\n")
        self.window.memo_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.window.memo_format.insert_table(2, 3)
        self.window.memo_edit.insertPlainText("待办事项")
        self.window.save_memo()
        self.window.show()
        self.window._switch_page(3)
        output = Path(__file__).resolve().parents[1] / "build" / "memo-preview"
        output.mkdir(parents=True, exist_ok=True)
        for theme in ("light", "dark"):
            self.window.set_theme(theme)
            for width, height in ((860, 620), (1220, 830)):
                self.window.resize(width, height)
                self.app.processEvents()
                self.assertEqual(self.window.width(), width)
                self.assertEqual(self.window.height(), height)
                self.assertGreater(self.window.memo_edit.height(), 100)
                self.assertTrue(self.window.memo_edited_at_label.isVisible())
                self.assertTrue(self.window.grab().save(str(output / f"memo-{theme}-{width}.png")))


if __name__ == "__main__":
    unittest.main()
