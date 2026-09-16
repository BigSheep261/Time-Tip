"""Offline regression checks for JM layout and downloaded-file management."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app.infrastructure.jmcomic_service import JMComicService, JMDownloadResult
from app.infrastructure.store import Store
from app.presentation.jm_manga import JMMangaPageMixin
from app.presentation.jm_widgets import MarqueeLabel
from app.presentation.theme import apply_theme


class JMTestWindow(JMMangaPageMixin, QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        QVBoxLayout(self).addWidget(self._jm_page())


class JMPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        apply_theme(cls.app, "light")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(str(self.root / "settings.ini"))
        self.window = JMTestWindow(self.store)

    def tearDown(self):
        self.window.jm_wait_for_shutdown()
        self.window.hide()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def completed_pdf(self, title="测试漫画"):
        directory = self.root / "jm_downloads" / "123" / "1"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "001.jpg").write_bytes(b"image fixture")
        output = directory.parent.parent / "123_全部.pdf"
        output.write_bytes(b"pdf fixture")
        task = {"album_id": "123", "title": title, "chapter": 0, "state": "下载中"}
        self.window.jm_queue.append(task)
        self.window._jm_task_done(task, (JMDownloadResult("123", title, 1, 1, directory.parent), output))
        return self.window.jm_completed[0], output, directory

    def test_fixed_search_rows_and_marquee_at_narrow_width(self):
        self.window._jm_search_done([
            {"id": str(index), "title": "超长漫画标题" * (index + 1), "tags": ["超长标签" * 20]}
            for index in range(12)
        ])
        self.window.resize(1000, 1150)
        self.window.show()
        self.app.processEvents()
        self.window.resize(570, 1150)
        self.app.processEvents()
        results = self.window.jm_results
        widths = []
        for index in range(results.count()):
            row = results.itemWidget(results.item(index))
            self.assertEqual(row.height(), 78)
            self.assertLessEqual(row.width(), results.viewport().width())
            buttons = row.findChildren(QPushButton)
            self.assertEqual([button.width() for button in buttons], [60, 80, 88])
            self.assertTrue(all(row.rect().contains(button.geometry()) for button in buttons))
            label = row.findChild(MarqueeLabel)
            self.assertGreater(label.width(), 40)
            self.assertLessEqual(label.geometry().right(), buttons[0].geometry().left())
            widths.append(row.width())
        self.assertEqual(len(set(widths)), 1)
        self.assertEqual(results.horizontalScrollBar().maximum(), 0)
        label = results.itemWidget(results.item(0)).findChild(MarqueeLabel)
        label.setText("超长标题" * 30)
        self.assertTrue(label._timer.isActive())
        for _ in range(35):
            label._advance()
        self.assertGreater(label._offset, 0)
        label.setText("短标题")
        self.assertFalse(label._timer.isActive())
        label.setText("超长标题" * 30)
        self.window.hide()
        self.assertFalse(label._timer.isActive())
        self.assertFalse(any(button.text() == "依赖说明" for button in self.window.findChildren(QPushButton)))

    def test_completion_moves_to_history_and_survives_restart(self):
        record, output, _ = self.completed_pdf()
        self.assertEqual(self.window.jm_queue, [])
        self.assertEqual(self.window.jm_queue_tabs.tabText(0), "下载队列 (0)")
        self.assertEqual(self.window.jm_queue_tabs.tabText(1), "完成队列 (1)")
        self.assertFalse(Path(record["output"]).is_absolute())
        self.window.store = Store(str(self.root / "settings.ini"))
        self.window._jm_load_completed()
        self.assertEqual(self.window._jm_local_path(self.window.jm_completed[0]["output"]), output)
        self.completed_pdf("重下后的名称")
        self.assertEqual(len(self.window.jm_completed), 1)
        self.assertEqual(self.window.jm_completed[0]["title"], "重下后的名称")

    def test_open_buttons_resolve_file_folder_and_download_root(self):
        record, output, directory = self.completed_pdf()
        with patch("app.presentation.jm_manga.QDesktopServices.openUrl", return_value=True) as opened:
            row = self.window.jm_completed_list.itemWidget(self.window.jm_completed_list.item(0))
            buttons = {button.text(): button for button in row.findChildren(QPushButton)}
            buttons["打开"].click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), output)
            buttons["打开文件夹"].click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), directory.parent)
            self.window._jm_open_download_root()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), self.window._jm_download_root())
            opened.reset_mock()
            output.unlink()
            self.window._jm_open_completed(record)
            opened.assert_not_called()
            self.assertIn("文件已移动或删除", self.window.jm_status.full_text)

    def test_delete_pdf_confirmation_preserves_images_and_cancel_preserves_record(self):
        record, output, directory = self.completed_pdf()
        with patch("app.presentation.jm_manga.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            self.window._jm_delete_completed(record)
        self.assertTrue(output.exists())
        self.assertEqual(len(self.window.jm_completed), 1)
        with patch("app.presentation.jm_manga.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window._jm_delete_completed(record)
        self.assertFalse(output.exists())
        self.assertTrue((directory / "001.jpg").exists())
        self.assertEqual(self.store.read_json("jm_download_history", None), [])

    def test_delete_directory_removes_nested_records_but_preserves_siblings(self):
        _, output, directory = self.completed_pdf()
        sibling = directory.parent / "2"
        sibling.mkdir()
        (sibling / "001.jpg").write_bytes(b"keep")
        record = {"album_id": "123", "title": "单章", "chapter": 1, "total": 1, "output": "123/1"}
        self.window.jm_completed += [record, {**record, "output": "123/1/001.jpg"}]
        with patch("app.presentation.jm_manga.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            self.window._jm_delete_completed(record)
        self.assertFalse(directory.exists())
        self.assertTrue(sibling.exists())
        self.assertTrue(output.exists())
        self.assertEqual(len(self.window.jm_completed), 1)

    def test_active_album_and_permission_error_keep_completion(self):
        record, output, _ = self.completed_pdf()
        self.window.jm_queue.append({"album_id": "123", "state": "下载中"})
        with patch("app.presentation.jm_manga.QMessageBox.question") as asked:
            self.window._jm_delete_completed(record)
            asked.assert_not_called()
        self.window.jm_queue.clear()
        with patch("app.presentation.jm_manga.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(JMComicService, "remove_path", side_effect=PermissionError("文件被占用")):
            self.window._jm_delete_completed(record)
        self.assertTrue(output.exists())
        self.assertEqual(len(self.window.jm_completed), 1)
        self.assertIn("删除失败", self.window.jm_status.full_text)

    def test_deletion_cannot_escape_download_root_or_delete_root(self):
        root = self.window._jm_download_root()
        root.mkdir()
        outside = self.root / "keep.txt"
        outside.write_text("keep")
        for target in (root, outside, root / ".." / "keep.txt"):
            with self.assertRaises(ValueError):
                JMComicService.remove_path(target, root)
        self.assertTrue(outside.exists())
        self.store.write_json("jm_download_history", [
            {"output": "../keep.txt"}, {"output": "."}, {"output": "123.pdf", "chapter": "bad"}, None,
        ])
        self.window._jm_load_completed()
        self.assertEqual(self.window.jm_completed, [])

    def test_legacy_downloads_are_discovered_once(self):
        _, output, directory = self.completed_pdf()
        self.store.write_json("jm_download_history", None)
        self.window._jm_load_completed()
        self.assertEqual({item["output"] for item in self.window.jm_completed}, {"123", output.name})
        self.window._jm_load_completed()
        self.assertEqual(len(self.window.jm_completed), 2)
        self.assertTrue(directory.exists())

    def test_background_queue_continues_after_failure_and_moves_success(self):
        root = self.window._jm_download_root()

        class FakeService:
            def download_album(self, album_id, progress):
                if album_id == "broken":
                    raise RuntimeError("模拟下载失败")
                directory = root / album_id
                directory.mkdir(parents=True)
                (directory / "001.jpg").write_bytes(b"fixture")
                progress(1, 1, "图片")
                return JMDownloadResult(album_id, album_id, 1, 1, directory)

        with patch.object(self.window, "_jm_service", side_effect=lambda: FakeService()):
            self.window._jm_enqueue("broken", "失败任务", 0, False)
            self.window._jm_enqueue("321", "成功任务", 0, False)
            deadline = time.monotonic() + 5
            while self.window._jm_workers and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
        self.assertFalse(self.window._jm_workers)
        self.assertEqual([task["state"] for task in self.window.jm_queue], ["失败"])
        self.assertEqual([task["album_id"] for task in self.window.jm_completed], ["321"])


if __name__ == "__main__":
    unittest.main()
