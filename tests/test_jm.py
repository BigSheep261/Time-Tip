import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from app.infrastructure.jmcomic_service import JMComicService
from app.infrastructure.store import Store
from app.presentation.window import TimeTipWindow


class JMFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.window = TimeTipWindow(Store(str(Path(self.folder.name) / "settings.ini")))
        self.window.timer.stop()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.quitting = True
        self.window.close()
        self.window.tray.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def test_jm_navigation_is_hidden_until_five_unlock_clicks(self):
        self.assertFalse(self.window.jm_nav_button.isVisible())
        for _ in range(4):
            self.window._unlock_jm_mode()
            self.app.processEvents()
        self.assertFalse(self.window.jm_nav_button.isVisible())
        self.window._unlock_jm_mode()
        self.app.processEvents()
        self.assertTrue(self.window.jm_nav_button.isVisible())
        self.assertEqual(self.window.pages.currentIndex(), 8)

    def test_local_favorites_persist_without_remote_login(self):
        self.window._jm_toggle_favorite({"id": "123", "title": "测试漫画", "tags": ["测试"]})
        self.assertEqual(self.window.store.read_json("jm_favorites", [])[0]["id"], "123")
        self.window._jm_toggle_favorite({"id": "123", "title": "测试漫画", "tags": ["测试"]})
        self.assertEqual(self.window.store.read_json("jm_favorites", []), [])

    def test_service_dependency_check_is_lazy(self):
        self.assertIsInstance(JMComicService.available(), bool)


if __name__ == "__main__":
    unittest.main()
