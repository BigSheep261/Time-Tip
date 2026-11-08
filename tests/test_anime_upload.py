"""Real-file and Qt regressions for manual anime video imports."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication

from app.infrastructure.anime_files import move_anime_video
from app.presentation.anime_upload import AnimeUploadDialog
from app.presentation.anime_widgets import AnimeCard, AnimeFolderDialog


class VideoMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "番剧"
        self.folder.mkdir()
        self.source = self.root / "第01集.MKV"
        self.source.write_bytes(b"video content")

    def tearDown(self):
        self.temp.cleanup()

    def test_move_video_and_episode_browser_detects_it(self):
        destination = move_anime_video(self.source, self.folder)
        self.assertFalse(self.source.exists())
        self.assertEqual(destination.read_bytes(), b"video content")
        self.assertEqual(AnimeFolderDialog._video_files(self.folder), [destination])

    def test_same_name_preserves_both_files(self):
        destination = self.folder / self.source.name
        destination.write_bytes(b"existing video")
        with self.assertRaises(FileExistsError):
            move_anime_video(self.source, self.folder)
        self.assertEqual(self.source.read_bytes(), b"video content")
        self.assertEqual(destination.read_bytes(), b"existing video")

    def test_already_in_target_is_not_removed(self):
        with self.assertRaisesRegex(ValueError, "已在目标"):
            move_anime_video(self.source, self.root)
        self.assertEqual(self.source.read_bytes(), b"video content")

    def test_nonvideo_and_missing_target_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "目标文件夹不存在"):
            move_anime_video(self.source, self.folder / "missing")
        text = self.root / "notes.txt"
        text.write_text("notes")
        with self.assertRaisesRegex(ValueError, "本地视频"):
            move_anime_video(text, self.folder)
        self.assertTrue(text.exists())

    def test_cross_drive_fallback_copies_then_removes_source(self):
        with patch.object(Path, "rename", side_effect=OSError("different drive")):
            destination = move_anime_video(self.source, self.folder)
        self.assertEqual(destination.read_bytes(), b"video content")
        self.assertFalse(self.source.exists())

    def test_failed_copy_keeps_source_and_removes_partial_target(self):
        def fail_copy(reader, writer, **kwargs):
            writer.write(b"partial")
            raise OSError("disk full")

        with patch.object(Path, "rename", side_effect=OSError("different drive")), patch(
            "app.infrastructure.anime_files.shutil.copyfileobj", side_effect=fail_copy
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                move_anime_video(self.source, self.folder)
        self.assertEqual(self.source.read_bytes(), b"video content")
        self.assertFalse((self.folder / self.source.name).exists())

    def test_failed_source_removal_keeps_original(self):
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == self.source:
                raise PermissionError("source locked")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "rename", side_effect=OSError("different drive")), patch.object(
            Path, "unlink", unlink
        ):
            with self.assertRaisesRegex(PermissionError, "source locked"):
                move_anime_video(self.source, self.folder)
        self.assertEqual(self.source.read_bytes(), b"video content")
        self.assertFalse((self.folder / self.source.name).exists())

    def test_target_appearing_during_move_is_not_overwritten(self):
        destination = self.folder / self.source.name
        original_open = Path.open

        def target_appears(path, mode="r", *args, **kwargs):
            if path == self.source and mode == "rb":
                with original_open(destination, "wb") as writer:
                    writer.write(b"new arrival")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "rename", side_effect=OSError("different drive")), patch.object(
            Path, "open", target_appears
        ):
            with self.assertRaises(FileExistsError):
                move_anime_video(self.source, self.folder)
        self.assertEqual(destination.read_bytes(), b"new arrival")
        self.assertTrue(self.source.exists())


class UploadDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "番剧"
        self.folder.mkdir()
        self.source = self.root / "第01集.mkv"
        self.source.write_bytes(b"video content")
        self.dialog = AnimeUploadDialog({"title": "测试番剧", "folder": str(self.folder)})

    def tearDown(self):
        if self.dialog.worker:
            self.dialog.worker.wait(5000)
            self.app.processEvents()
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def test_card_requires_configured_folder(self):
        card = AnimeCard({"title": "test"})
        self.assertFalse(card.upload_button.isEnabled())
        configured = AnimeCard({"title": "test", "folder": str(self.folder)})
        self.assertTrue(configured.upload_button.isEnabled())

    def test_picker_multiselect_deduplicates_and_removes_queue_only(self):
        other = self.root / "02.mp4"
        other.write_bytes(b"other")
        with patch("app.presentation.anime_upload.QFileDialog.getOpenFileNames",
                   return_value=([str(self.source), str(other), str(self.source)], "")):
            self.dialog.choose_button.click()
        self.assertEqual(self.dialog.file_list.count(), 2)
        self.dialog.file_list.item(0).setSelected(True)
        self.dialog.remove_button.click()
        self.assertEqual(len(self.dialog._pending), 1)
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_local_drop_queues_without_moving_and_remote_drop_is_ignored(self):
        area = self.dialog.drop_area
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.source))])
        enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(area, enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(area, drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(self.dialog.file_list.count(), 1)
        self.assertTrue(self.source.exists())
        mime.setUrls([QUrl("https://example.com/episode.mkv")])
        enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(area, enter)
        self.assertFalse(enter.isAccepted())

    def test_background_batch_reports_partial_success_and_can_retry(self):
        other = self.root / "02.mp4"
        other.write_bytes(b"other")
        (self.folder / other.name).write_bytes(b"existing")
        self.dialog.add_files([str(self.source), str(other)])
        self.dialog.show()
        self.dialog.start_move()
        self.dialog.reject()
        self.assertTrue(self.dialog.isVisible())
        self.assertFalse(self.dialog.choose_button.isEnabled())
        self.assertTrue(self.dialog.open_button.isEnabled())
        self.assertTrue(self.dialog.worker.wait(5000))
        self.app.processEvents()
        self.assertFalse(self.dialog.busy)
        self.assertEqual(self.dialog.moved_count, 1)
        self.assertEqual(len(self.dialog._pending), 1)
        self.assertIn("成功 1 个，未移动 1 个", self.dialog.feedback.text())
        self.assertFalse(self.source.exists())
        self.assertTrue(other.exists())
        (self.folder / other.name).unlink()
        self.dialog.start_move()
        self.assertTrue(self.dialog.worker.wait(5000))
        self.app.processEvents()
        self.assertEqual(self.dialog.moved_count, 2)
        self.assertFalse(self.dialog.move_button.isEnabled())

    def test_open_folder_uses_local_directory_url_and_reports_failure(self):
        with patch("app.presentation.anime_upload.QDesktopServices.openUrl", return_value=True) as opened:
            self.dialog.open_button.click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.folder)
        with patch("app.presentation.anime_upload.QDesktopServices.openUrl", return_value=False):
            self.dialog.open_button.click()
            self.assertIn("无法打开目录", self.dialog.feedback.text())

    def test_missing_folder_does_not_start_worker(self):
        self.dialog.add_files([str(self.source)])
        self.folder.rmdir()
        self.dialog.start_move()
        self.assertFalse(self.dialog.busy)
        self.assertIn("不存在", self.dialog.feedback.text())
        self.assertTrue(self.source.exists())


if __name__ == "__main__":
    unittest.main()
