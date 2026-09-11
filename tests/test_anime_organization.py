import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QDragLeaveEvent, QDragMoveEvent, QDropEvent, QFontDatabase, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel

from app.domain.anime_organization import anime_groups, reorder_anime
from app.infrastructure.database import DataStore
from app.infrastructure.store import Store
from app.presentation.anime_dialog import AnimeDialog
from app.presentation.anime_organization import AnimeGroupsDialog, AnimeListWidget
from app.presentation.window import TimeTipWindow


def entries():
    return [dict(id=key, title=title, category="backlog", group=group,
                 episode_count=12, progress=0, folder="", cover="")
            for key, title, group in (("a", "Zeta", "收藏"), ("b", "Beta", "未分组"),
                                      ("c", "Alpha", "收藏"), ("d", "Delta", "未分组"))]


class OrganizationRulesTests(unittest.TestCase):
    def test_filtered_order_keeps_hidden_slots_and_fields(self):
        original = entries()
        reordered = reorder_anime(original, ["c", "a"])
        self.assertEqual([item["id"] for item in reordered], ["c", "b", "a", "d"])
        self.assertEqual(original, entries())
        self.assertIs(reordered[1], original[1])

    def test_invalid_order_is_rejected(self):
        for ids in (["a", "a"], ["missing"]):
            with self.assertRaises(ValueError):
                reorder_anime(entries(), ids)

    def test_groups_include_empty_saved_groups_and_normalize_names(self):
        self.assertEqual(anime_groups([{"group": " 收藏 "}, {"group": None}], ["收藏", "未来"]),
                         ["未分组", "收藏", "未来"])

    def test_order_groups_and_backup_roundtrip_both_backends(self):
        for sqlite in (False, True):
            with self.subTest(sqlite=sqlite), tempfile.TemporaryDirectory() as folder:
                def open_store(name):
                    return DataStore(str(Path(folder) / name)) if sqlite else Store(str(Path(folder) / (name + ".ini")))
                store = open_store("original")
                reordered = reorder_anime(entries(), ["d", "c", "b", "a"])
                store.save_anime(reordered)
                store.write_json("anime_groups", ["收藏", "未来"])
                if sqlite:
                    store.close()
                store = open_store("original")
                self.assertEqual([item["id"] for item in store.anime()], ["d", "c", "b", "a"])
                for suffix in ("json", "zip"):
                    backup = str(Path(folder) / ("backup." + suffix))
                    store.export_data(backup)
                    restored = open_store("restored_" + suffix)
                    restored.import_data(backup)
                    self.assertEqual([item["id"] for item in restored.anime()], ["d", "c", "b", "a"])
                    self.assertEqual(restored.read_json("anime_groups", []), ["收藏", "未来"])
                    if sqlite:
                        restored.close()
                if sqlite:
                    store.close()


class OrganizationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"):
            if Path(path).exists():
                QFontDatabase.addApplicationFont(path)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.folder.name) / "settings.ini"))
        self.store.save_anime(entries())
        self.window = TimeTipWindow(self.store)
        self.window.timer.stop()
        self.window.resize(1220, 920)
        self.window._switch_page(6)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.quitting = True
        self.window.geometry_timer.stop()
        self.window.close()
        self.window.tray.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def test_filtered_keyboard_reorder_persists_and_preserves_selection(self):
        window = self.window
        window.anime_group_filter.setCurrentIndex(window.anime_group_filter.findData("收藏"))
        self.assertEqual(window.anime_list.ids(), ["a", "c"])
        window.anime_list.setCurrentRow(1)
        QTest.keyClick(window.anime_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
        self.app.processEvents()
        self.assertEqual(window.anime_list.ids(), ["c", "a"])
        self.assertEqual(window.anime_list.currentRow(), 0)
        self.assertEqual([item["id"] for item in self.store.anime()], ["c", "b", "a", "d"])
        self.assertFalse(window.anime_move_up.isEnabled())
        self.assertTrue(window.anime_move_down.isEnabled())

    def test_search_reordering_and_automatic_sort_do_not_overwrite_manual_order(self):
        window = self.window
        window.anime_search.setText("ta")
        window._save_anime_order(["d", "b", "a"])
        self.assertEqual([item["id"] for item in window.anime], ["d", "b", "c", "a"])
        window.anime_search.clear()
        window.anime_sort.setCurrentIndex(window.anime_sort.findData("title"))
        self.assertFalse(window.anime_list.dragEnabled())
        self.assertFalse(window.anime_list.acceptDrops())
        self.assertEqual(window.anime_list.ids(), ["c", "b", "d", "a"])
        window._save_anime_order(["a", "b", "c", "d"])
        window.anime_sort.setCurrentIndex(0)
        self.assertEqual(window.anime_list.ids(), ["d", "b", "c", "a"])

    def test_card_press_drag_threshold_and_release(self):
        view = self.window.anime_list
        card = view.itemWidget(view.item(0))
        self.assertTrue(all(label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                            for label in card.findChildren(QLabel)))
        with patch.object(view, "startDrag", return_value=None) as start_drag:
            QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
            small = QMouseEvent(QEvent.Type.MouseMove, QPointF(41, 40), QPointF(41, 40),
                                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(card, small)
            start_drag.assert_not_called()
            large = QMouseEvent(QEvent.Type.MouseMove, QPointF(90, 90), QPointF(90, 90),
                                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(card, large)
            start_drag.assert_called_once_with(Qt.DropAction.MoveAction)
            QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(90, 90))
            self.assertIsNone(card._drag_start_pos)

    def test_drop_moves_to_end_then_top_and_preserves_card_widgets(self):
        view = self.window.anime_list

        class LocalDrop(QDropEvent):
            def source(self):
                return view

        def drop(item_id, position):
            mime = QMimeData()
            mime.setData(view.MIME_TYPE, item_id.encode())
            event = LocalDrop(QPointF(position), Qt.DropAction.MoveAction, mime,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            view.dropEvent(event)
            self.assertTrue(event.isAccepted())
            self.app.processEvents()

        view.setCurrentRow(0)
        drop("a", view.visualItemRect(view.item(3)).bottomLeft())
        self.assertEqual(view.ids(), ["b", "c", "d", "a"])
        self.assertTrue(all(view.itemWidget(view.item(i)) for i in range(view.count())))
        drop("a", view.visualItemRect(view.item(0)).topLeft())
        self.assertEqual(view.ids(), ["a", "b", "c", "d"])
        self.assertEqual([item["id"] for item in self.store.anime()], view.ids())

    def test_drag_edge_scroll_and_cancel_leave_data_unchanged(self):
        view = self.window.anime_list
        class LocalMove(QDragMoveEvent):
            def source(self):
                return view
        mime = QMimeData()
        mime.setData(view.MIME_TYPE, b"a")
        event = LocalMove(QPoint(30, view.viewport().height() - 4),
                          Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
        view.dragMoveEvent(event)
        self.assertTrue(event.isAccepted())
        QTest.qWait(120)
        self.assertGreater(view.verticalScrollBar().value(), 0)
        self.assertIsNotNone(view._drop_row)
        view.dragLeaveEvent(QDragLeaveEvent())
        self.assertFalse(view._scroll_timer.isActive())
        self.assertIsNone(view._drop_row)
        self.assertEqual([item["id"] for item in self.store.anime()], ["a", "b", "c", "d"])

    def test_group_named_all_is_not_confused_with_all_groups(self):
        self.window.anime[0]["group"] = "all"
        self.window._refresh_anime_list()
        combo = self.window.anime_group_filter
        combo.setCurrentIndex(combo.findData("all"))
        self.assertEqual(self.window.anime_list.ids(), ["a"])

    def test_external_drop_and_stale_order_are_ignored(self):
        view = self.window.anime_list
        mime = QMimeData()
        mime.setData(view.MIME_TYPE, b"a")
        event = QDropEvent(QPointF(10, 10), Qt.DropAction.MoveAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dropEvent(event)
        self.assertFalse(event.isAccepted())
        self.window._save_anime_order(["missing"])
        self.assertEqual(view.ids(), ["a", "b", "c", "d"])

    def test_group_editor_add_rename_delete_and_cancel(self):
        original = entries()
        dialog = AnimeGroupsDialog(original, ["未来"])
        dialog.name.setText("新番")
        dialog.add_group()
        self.assertIn("新番", dialog.groups)
        dialog.name.setText("收藏")
        dialog.add_group()
        self.assertIn("已存在", dialog.feedback.text())
        dialog._refresh("收藏")
        dialog.name.setText("珍藏")
        dialog.rename_group()
        self.assertEqual([item["group"] for item in dialog.items], ["珍藏", "未分组", "珍藏", "未分组"])
        dialog.delete_group()
        self.assertEqual(len(dialog.items), 4)
        self.assertTrue(all(item["group"] == "未分组" for item in dialog.items))
        dialog.reject()
        self.assertEqual(original, entries())
        dialog.deleteLater()

    def test_save_group_manager_and_empty_group_filter(self):
        def accept_draft(dialog):
            dialog.name.setText("空分组")
            dialog.add_group()
            return QDialog.DialogCode.Accepted
        with patch.object(AnimeGroupsDialog, "exec", accept_draft):
            self.window.manage_anime_groups()
        self.assertIn("空分组", self.store.read_json("anime_groups", []))
        combo = self.window.anime_group_filter
        combo.setCurrentIndex(combo.findData("空分组"))
        self.assertEqual(self.window.anime_list.count(), 0)
        self.assertTrue(self.window.anime_empty.isVisible())
        self.assertEqual(combo.currentData(), "空分组")

    def test_editor_reuses_group_and_saves_category(self):
        dialog = AnimeDialog(entries()[0], groups=["未来"])
        self.assertGreaterEqual(dialog.group.findText("未来"), 0)
        dialog.group.setCurrentText("  新番  ")
        dialog.category.setCurrentIndex(dialog.category.findData("completed"))
        values = dialog.values()
        self.assertEqual(values["group"], "新番")
        self.assertEqual(values["category"], "completed")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
