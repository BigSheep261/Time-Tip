"""Composition root: start Qt, acquire one instance and show the window."""
import sys
import os
import hashlib
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from app.infrastructure.single_instance import SingleInstanceGuard
from app.infrastructure.store import Store
from app.presentation.window import TimeTipWindow, make_app_icon
from app.presentation.theme import APP_NAME, STYLESHEET
from app.version import APP_VERSION

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TimeTip")
    # Isolated profile for packaged integration tests; normal launches keep the existing registry.
    profile = os.environ.get("TIMETIP_TEST_PROFILE")
    channel = "TimeTip.SingleInstance"
    lock_dir = None
    if profile:
        profile = str(Path(profile).resolve())
        lock_dir = str(Path(profile).parent)
        channel += ".Test." + hashlib.sha256(profile.lower().encode()).hexdigest()[:16]
    try:
        guard = SingleInstanceGuard(channel, lock_dir=lock_dir)
    except RuntimeError as error:
        QMessageBox.warning(None, APP_NAME, str(error))
        return
    if guard.existing:
        if not guard.activated:
            QMessageBox.information(None, APP_NAME, "TimeTip 已在运行，但暂未响应。请稍后重试。")
        return
    app.setWindowIcon(make_app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    store = Store(profile)
    window = TimeTipWindow(store)
    guard.show_requested.connect(window.restore_window)
    guard.quit_requested.connect(window.quit_app)
    app.aboutToQuit.connect(window.jm_wait_for_shutdown)
    app.aboutToQuit.connect(store.close)
    app.aboutToQuit.connect(guard.close)
    window.show()
    sys.exit(app.exec())


