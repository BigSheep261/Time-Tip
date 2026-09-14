import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QImage, QImageReader, QMovie
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QFrame, QMessageBox

from app.infrastructure.store import Store
from app.presentation.window import TimeTipWindow


# Three 12x6 red/green/blue frames, 100 ms each, looping forever.
ANIMATED_GIF = base64.b64decode(
    "R0lGODlhDAAGAIEAAP8AAAAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACgAAACwAAAAADAAGAAAIEAABCBxIsKDBgwgTKlxoMCAAIfkEAQoAAQAsAAAAAAwABgCBAIAAAAAAAAAAAAAACBAAAQgcSLCgwYMIEypcaDAgACH5BAEKAAEALAAAAAAMAAYAgQAA/wAAAAAAAAAAAAgQAAEIHEiwoMGDCBMqXGgwIAA7"
)


class EmojiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.folder.name) / "settings.ini"))
        self.window = TimeTipWindow(self.store)
        self.window.timer.stop()

    def tearDown(self):
        self.window.quitting = True
        self.window.geometry_timer.stop()
        self.window.close()
        self.window.tray.hide()
        self.window.deleteLater()
        # Deliver Qt's deferred destruction before deleting the temporary asset directory.
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.folder.cleanup()

    def image(self, name="sticker.png", color=0xFF6655):
        path = Path(self.folder.name) / name
        image = QImage(48, 48, QImage.Format.Format_ARGB32)
        image.fill(color)
        self.assertTrue(image.save(str(path)))
        return str(path)

    def restart(self):
        self.window.quitting = True
        self.window.close()
        self.window.tray.hide()
        self.window.deleteLater()
        # Deliver Qt's deferred destruction before deleting the temporary asset directory.
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.window = TimeTipWindow(Store(self.store.settings.fileName()))
        self.window.timer.stop()

    def test_images_are_only_visuals_and_persist_after_restart(self):
        source = self.image()
        self.window._import_emoji_files([source])
        self.assertEqual(self.window.emoji_grid.count(), 1)
        item = self.window.emoji_grid.item(0)
        self.assertEqual(item.text(), "")
        self.assertTrue(item.toolTip() == "")
        self.assertFalse(item.icon().isNull())
        saved = self.store.read_json("emojis", [])
        self.assertEqual(len(saved), 1)
        self.assertTrue((self.store.asset_root("emojis") / saved[0]["path"]).is_file())
        self.restart()
        self.assertEqual(self.window.emoji_grid.count(), 1)
        self.assertEqual(self.window.emoji_category_list.currentItem().text(), "默认")

    def test_drop_in_and_drag_out_use_image_file_urls(self):
        source = self.image("drop.png", 0xFF22AA)
        received = []
        self.window.emoji_grid.filesDropped.connect(received.extend)
        self.window.emoji_grid.filesDropped.emit([source])
        self.assertEqual(received, [source])
        self.window._import_emoji_files(received)
        self.window.emoji_grid.setCurrentRow(0)

        captured = {}

        class FakeDrag:
            def __init__(self, parent):
                captured["parent"] = parent

            def setMimeData(self, mime):
                captured["mime"] = mime

            def setPixmap(self, pixmap):
                captured["pixmap"] = pixmap

            def exec(self, action):
                captured["action"] = action
                return action

        with patch("app.presentation.emoji_grid.QDrag", FakeDrag):
            self.window.emoji_grid.startDrag(Qt.DropAction.CopyAction)
        urls = captured["mime"].urls()
        self.assertEqual(len(urls), 1)
        self.assertTrue(urls[0].isLocalFile())
        self.assertTrue(Path(urls[0].toLocalFile()).is_file())
        self.assertEqual(captured["action"], Qt.DropAction.CopyAction)

    def gif(self, name="animated.gif"):
        path = Path(self.folder.name) / name
        path.write_bytes(ANIMATED_GIF)
        return str(path)

    def show_emojis(self):
        self.window.show()
        self.window._switch_page(7)
        self.app.processEvents()

    def assert_animation_advances(self, grid):
        movie = next(iter(grid._movies.values()))
        item = grid.item(0)
        frames = []
        movie.frameChanged.connect(lambda frame: frames.append(
            item.icon().pixmap(grid.iconSize()).toImage().pixelColor(0, 0).name()))
        QTest.qWait(380)
        self.assertEqual(movie.state(), QMovie.MovieState.Running)
        self.assertGreaterEqual(len(set(frames)), 2, "The displayed GIF icon must change frames")
        self.assertLessEqual(movie.currentPixmap().width(), grid.iconSize().width())
        self.assertEqual(movie.currentPixmap().width(), movie.currentPixmap().height() * 2)

    def test_dropped_gif_plays_with_static_images_and_after_restart(self):
        source = self.gif()
        self.show_emojis()
        grid = self.window.emoji_grid
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(source)])
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(grid.viewport(), enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(grid.viewport(), drop)
        self.assertTrue(drop.isAccepted())
        self.window._import_emoji_files([self.image()])
        self.assertEqual(grid.count(), 2)
        self.assertEqual(len(grid._movies), 1)
        static_icon_key = grid.item(1).icon().cacheKey()
        self.assert_animation_advances(grid)
        self.assertEqual(grid.item(1).icon().cacheKey(), static_icon_key)
        self.assertTrue(all(grid.item(i).text() == "" for i in range(grid.count())))
        saved = self.store.read_json("emojis", [])[0]
        self.assertEqual((self.window.emoji_root / saved["path"]).read_bytes(), ANIMATED_GIF)
        self.restart()
        self.show_emojis()
        self.assert_animation_advances(self.window.emoji_grid)

    def test_animated_payload_with_jpg_suffix_is_played_and_not_flattened_on_drag(self):
        source = self.gif("animated.jpg")
        self.window._import_emoji_files([source])
        self.assertEqual(len(self.window.emoji_grid._movies), 1)
        self.window.emoji_grid.setCurrentRow(0)
        with patch("app.presentation.emoji_grid.QDrag") as drag_class:
            self.window.emoji_grid.startDrag(Qt.DropAction.CopyAction)
            mime = drag_class.return_value.setMimeData.call_args.args[0]
        self.assertFalse(mime.hasImage())
        self.assertEqual(Path(mime.urls()[0].toLocalFile()).suffix.lower(), ".jpg")

    def test_sorting_current_category_persists_without_reordering_other_categories(self):
        first, second = self.image("first.png"), self.image("second.png")
        self.window._import_emoji_files([first, second])
        with patch("app.presentation.emojis.QInputDialog.getText", return_value=("工作", True)):
            self.window._new_emoji_category()
        self.window._import_emoji_files([self.image("third.png")])
        self.window._refresh_emoji_categories("default")
        default_ids = [r["id"] for r in self.window.emojis if r["category_id"] == "default"]
        other_id = next(r["id"] for r in self.window.emojis if r["category_id"] != "default")
        self.window._toggle_emoji_reordering(True)
        self.window._emoji_rows_reordered(default_ids[::-1])
        self.assertEqual([r["id"] for r in self.window.emojis if r["category_id"] == "default"], default_ids[::-1])
        self.assertEqual(next(r["id"] for r in self.window.emojis if r["category_id"] != "default"), other_id)
        self.assertEqual([r["id"] for r in self.store.read_json("emojis", []) if r["category_id"] == "default"], default_ids[::-1])

    def test_standalone_emoji_package_round_trip(self):
        source = self.image("package.png")
        self.window._import_emoji_files([source])
        package = str(Path(self.folder.name) / "emojis.zip")
        with patch("app.presentation.emojis.QFileDialog.getSaveFileName", return_value=(package, "zip")), \
             patch("app.presentation.emojis.QMessageBox.information"):
            self.window._export_emoji_package()
        self.assertTrue(Path(package).is_file())
        self.window._delete_selected_emojis()  # no selection: keep original, then import a duplicate package
        with patch("app.presentation.emojis.QFileDialog.getOpenFileName", return_value=(package, "zip")), \
             patch("app.presentation.emojis.QMessageBox.information"):
            self.window._import_emoji_package()
        self.assertEqual(len(self.window.emojis), 2)
        self.assertTrue(all((self.window.emoji_root / r["path"]).is_file() for r in self.window.emojis))

    def test_gif_pauses_when_hidden_and_releases_players_on_category_switch(self):
        self.window._import_emoji_files([self.gif()])
        grid = self.window.emoji_grid
        movie = next(iter(grid._movies.values()))
        self.assertEqual(movie.state(), QMovie.MovieState.NotRunning)
        self.show_emojis()
        spy = QSignalSpy(movie.frameChanged)
        QTest.qWait(160)
        self.assertGreater(len(spy), 0)
        self.window._switch_page(3)
        self.app.processEvents()
        self.assertEqual(movie.state(), QMovie.MovieState.Paused)
        paused_count = len(spy)
        QTest.qWait(220)
        self.assertEqual(len(spy), paused_count)
        self.window._switch_page(7)
        QTest.qWait(220)
        self.assertEqual(movie.state(), QMovie.MovieState.Running)
        self.assertGreater(len(spy), paused_count)
        with patch("app.presentation.emojis.QInputDialog.getText", return_value=("其他", True)):
            self.window._new_emoji_category()
        self.assertEqual(grid._movies, {})
        QTest.qWait(50)
        self.assertEqual(grid.findChildren(QMovie), [])
        self.window._refresh_emoji_categories("default")
        self.assertEqual(len(grid._movies), 1)
        self.assert_animation_advances(grid)

    def test_deleting_playing_gif_releases_file_and_animation(self):
        self.window._import_emoji_files([self.gif()])
        self.show_emojis()
        grid = self.window.emoji_grid
        stored_path = self.window.emoji_root / self.window.emojis[0]["path"]
        grid.setCurrentRow(0)
        self.window._delete_selected_emojis()
        self.assertFalse(stored_path.exists())
        self.assertEqual(grid.count(), 0)
        self.assertEqual(grid._movies, {})
        QTest.qWait(150)
        self.assertEqual(grid.findChildren(QMovie), [])
        self.restart()
        self.assertEqual(self.window.emojis, [])

    def test_dragging_gif_keeps_original_file_without_flattening_to_image_mime(self):
        self.window._import_emoji_files([self.gif("animated.GIF")])
        grid = self.window.emoji_grid
        grid.setCurrentRow(0)
        with patch("app.presentation.emoji_grid.QDrag") as drag_class:
            grid.startDrag(Qt.DropAction.CopyAction)
            mime = drag_class.return_value.setMimeData.call_args.args[0]
        self.assertFalse(mime.hasImage())
        self.assertEqual(len(mime.urls()), 1)
        outgoing = Path(mime.urls()[0].toLocalFile())
        self.assertEqual(outgoing.suffix.lower(), ".gif")
        self.assertEqual(outgoing.read_bytes(), ANIMATED_GIF)
        self.assertEqual(QImageReader(str(outgoing)).imageCount(), 3)
        self.window._import_emoji_files([self.image()])
        grid.selectAll()
        with patch("app.presentation.emoji_grid.QDrag") as drag_class:
            grid.startDrag(Qt.DropAction.CopyAction)
            mime = drag_class.return_value.setMimeData.call_args.args[0]
        self.assertEqual(len(mime.urls()), 2)
        self.assertFalse(mime.hasImage())

    def test_categories_can_be_created_renamed_and_deleted_without_losing_images(self):
        source = self.image()
        self.window._import_emoji_files([source])
        with patch("app.presentation.emojis.QInputDialog.getText", return_value=("工作", True)):
            self.window._new_emoji_category()
        self.assertEqual(self.window.emoji_category_list.currentItem().text(), "工作")
        self.window._import_emoji_files([source])
        with patch("app.presentation.emojis.QInputDialog.getText", return_value=("常用", True)):
            self.window._rename_emoji_category()
        self.assertEqual(self.window.emoji_category_list.currentItem().text(), "常用")
        with patch("app.presentation.emojis.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window._delete_emoji_category()
        self.assertEqual([c["name"] for c in self.window.emoji_categories], ["默认"])
        self.assertEqual({record["category_id"] for record in self.window.emojis}, {"default"})
        self.assertEqual(self.window.emoji_grid.count(), 2)

    def test_navigation_places_emoji_page_between_settings_and_anime(self):
        sidebar = self.window.findChild(QFrame, "sidebar")
        labels = []
        for index in range(sidebar.layout().count()):
            widget = sidebar.layout().itemAt(index).widget()
            if widget is not None and hasattr(widget, "text") and widget.text():
                labels.append(widget.text())
        self.assertLess(labels.index("表情包"), labels.index("看番提醒"))
        self.assertLess(labels.index("看番提醒"), labels.index("设置"))
        self.window._switch_page(7)
        self.assertIsNotNone(self.window.emoji_grid)
        self.assertTrue(self.window.nav_buttons[7].isChecked())

    def test_running_gif_does_not_lock_original_during_backup_restore(self):
        self.window._import_emoji_files([self.gif()])
        self.show_emojis()
        backup = str(Path(self.folder.name) / "playing-gif.zip")
        self.store.export_data(backup)
        # Restoration overwrites the same file that the visible player was loaded from.
        self.store.import_data(backup)
        stored_path = self.window.emoji_root / self.window.emojis[0]["path"]
        self.assertEqual(stored_path.read_bytes(), ANIMATED_GIF)
        self.assert_animation_advances(self.window.emoji_grid)

    def test_emoji_files_are_included_in_zip_backup(self):
        source = self.image()
        self.window._import_emoji_files([source])
        backup = str(Path(self.folder.name) / "emoji-backup.zip")
        self.store.export_data(backup)
        restored = Store(str(Path(self.folder.name) / "restored.ini"))
        restored.import_data(backup)
        record = restored.read_json("emojis", [])[0]
        self.assertTrue((restored.asset_root("emojis") / record["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
