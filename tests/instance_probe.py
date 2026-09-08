"""Isolated child process for single-instance integration tests."""
import json
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget
from app.infrastructure.single_instance import SingleInstanceGuard

folder, channel, token = sys.argv[1:4]
app = QApplication([])
guard = SingleInstanceGuard(channel, lock_dir=folder)
result = Path(folder) / (token + '.json')
if guard.existing:
    result.write_text(json.dumps(dict(role='secondary', activated=guard.activated, pid=os.getpid())))
    sys.exit(0 if guard.activated else 2)
window = QWidget()
window.hide()
result.write_text(json.dumps(dict(role='primary', pid=os.getpid())))

def show():
    window.showNormal()
    window.raise_()
    window.activateWindow()
    (Path(folder) / 'activation.json').write_text(json.dumps(dict(pid=os.getpid(), visible=window.isVisible(), minimized=window.isMinimized())))

guard.show_requested.connect(show)
guard.quit_requested.connect(app.quit)
app.aboutToQuit.connect(guard.close)
QTimer.singleShot(20000, app.quit)
app.exec()
