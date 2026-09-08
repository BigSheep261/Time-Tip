"""Launch an isolated sample workspace for manual Windows UI verification."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QDateTime
from PyQt6.QtWidgets import QApplication
from timetip import STYLESHEET, Store, TimeTipWindow


if __name__ == "__main__":
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    path = Path(__file__).resolve().parents[1] / "build" / "ui-preview.ini"
    path.parent.mkdir(exist_ok=True)
    fresh = not path.exists()
    window = TimeTipWindow(Store(str(path)))
    window.setWindowTitle("TimeTip · 功能验证")
    if fresh:
        for title, days in [("下一站，去看海", 10), ("项目交付", 3)]:
            window.new_countdown()
            window.countdown_name.setText(title)
            window.target_edit.setDateTime(QDateTime(datetime.now() + timedelta(days=days)))
            window.save_target()
        window.add_memo()
        window.memo_title.setText("今天的小计划")
        window.memo_edit.setPlainText("读完手边的书\n整理旅行清单\n记得给家人打电话")
        window.save_memo()
        window.monthly_salary.setValue(22000)
        window.save_salary_settings()
    window.quitting = True
    window.tray.hide()
    window.show()
    sys.exit(app.exec())
