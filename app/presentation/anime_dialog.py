"""Modal editor for anime entries."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path
import shutil
from PyQt6.QtCore import QDate, Qt, QTime
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget
from app.domain.anime import CATEGORIES, WEEKDAY_NAMES, episode_label

class AnimeDialog(QDialog):
    def __init__(self, item=None, parent=None):
        super().__init__(parent); self.item = dict(item or {}); self.setWindowTitle("编辑番剧" if item else "添加番剧"); self.setModal(True); self.setMinimumWidth(500)
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.name = QLineEdit(self.item.get("title", "")); self.name.setPlaceholderText("番剧名称"); form.addRow("名称", self.name)
        self.category = QComboBox(); [self.category.addItem(label, key) for key, label in CATEGORIES]; self.category.setCurrentIndex(max(0, self.category.findData(self.item.get("category", "watching")))); form.addRow("分类", self.category)
        today = date.today(); start = QDate.fromString(self.item.get("start_date", today.isoformat()), "yyyy-MM-dd"); end = QDate.fromString(self.item.get("end_date", (today + timedelta(days=84)).isoformat()), "yyyy-MM-dd")
        self.start_date = QDateEdit(start if start.isValid() else QDate.currentDate()); self.start_date.setCalendarPopup(True); form.addRow("放送开始", self.start_date)
        self.end_date = QDateEdit(end if end.isValid() else QDate.currentDate().addDays(84)); self.end_date.setCalendarPopup(True); form.addRow("放送结束", self.end_date)
        self.weekday = QComboBox(); [self.weekday.addItem("周" + d, i) for i, d in enumerate(WEEKDAY_NAMES)]; days = self.item.get("air_days", [0]); self.weekday.setCurrentIndex(days[0] if days and isinstance(days[0], int) else 0); form.addRow("每周更新日", self.weekday)
        self.episodes = QSpinBox(); self.episodes.setRange(1, 999); self.episodes.setValue(int(self.item.get("episode_count", 12))); self.episodes.valueChanged.connect(self._limit_progress); form.addRow("总集数", self.episodes)
        progress_row = QHBoxLayout(); self.progress = QSpinBox(); self.progress.setRange(0, self.episodes.value()); self.progress.setPrefix("第 "); self.progress.setSuffix(" 话"); self.progress.setValue(int(self.item.get("progress", 0))); progress_row.addWidget(self.progress); minus = QPushButton("−"); plus = QPushButton("＋"); minus.clicked.connect(self.progress.stepDown); plus.clicked.connect(self.progress.stepUp); progress_row.addWidget(minus); progress_row.addWidget(plus); form.addRow("观看进度", progress_row)
        self.folder = QLineEdit(self.item.get("folder", "")); browse = QPushButton("选择文件夹"); browse.clicked.connect(self._choose_folder); folder_row = QHBoxLayout(); folder_row.addWidget(self.folder, 1); folder_row.addWidget(browse); form.addRow("本地文件夹", folder_row)
        self.cover = self.item.get("cover", ""); self.cover_label = QLabel(); self.cover_label.setFixedSize(90, 120); self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.cover_label.setStyleSheet("background:#ECE9FF;border-radius:8px;"); self._render_cover(); upload = QPushButton("上传封面"); upload.clicked.connect(self._choose_cover); cover_row = QHBoxLayout(); cover_row.addWidget(self.cover_label); cover_row.addWidget(upload); cover_row.addStretch(); form.addRow("番剧封面", cover_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
    def _limit_progress(self, value): self.progress.setRange(0, value); self.progress.setValue(min(self.progress.value(), value))
    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择番剧文件夹", self.folder.text() or "")
        if folder: self.folder.setText(folder)
    def _choose_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择番剧封面", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if path: self.cover = path; self._render_cover()
    def _render_cover(self):
        default = Path(__file__).resolve().parents[2] / "assets" / "timetip.png"
        source = Path(self.cover) if self.cover and Path(self.cover).is_file() else default
        if source.is_file(): self.cover_label.setPixmap(QPixmap(str(source)).scaled(self.cover_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else: self.cover_label.setText("TimeTip\n番剧封面")
    def values(self):
        return {"id": self.item.get("id", ""), "title": self.name.text().strip(), "category": self.category.currentData(), "start_date": self.start_date.date().toString("yyyy-MM-dd"), "end_date": self.end_date.date().toString("yyyy-MM-dd"), "air_days": [self.weekday.currentData()], "episode_count": self.episodes.value(), "progress": self.progress.value(), "folder": self.folder.text().strip(), "cover": self.cover}
