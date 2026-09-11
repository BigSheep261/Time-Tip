"""Modal editor for anime entries."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import uuid

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.domain.anime import CATEGORIES, WEEKDAY_NAMES, progress_number, validate_anime
from app.domain.anime_organization import anime_groups, group_name


DEFAULT_ANIME_COVER = Path(__file__).resolve().parents[2] / "assets" / "anime-default-cover.png"


class CoverCropDialog(QDialog):
    """Small manual crop tool for uploaded covers."""

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self.setObjectName("animeDialog")
        self.setModal(True)
        self.setWindowTitle("裁剪封面")
        self.source = QPixmap(source)
        self.cropped = None
        outer = QVBoxLayout(self); outer.setContentsMargins(20, 18, 20, 18); outer.setSpacing(12)
        outer.addWidget(QLabel("调整裁剪区域，保存后会作为番剧封面。", objectName="animeDialogHint"))
        self.preview = QLabel(objectName="animeDialogCover"); self.preview.setFixedSize(220, 220); self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter); outer.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignCenter)
        form = QFormLayout(); self.crop_x = QSpinBox(); self.crop_y = QSpinBox(); self.crop_width = QSpinBox(); self.crop_height = QSpinBox()
        for field in (self.crop_x, self.crop_y, self.crop_width, self.crop_height): field.setRange(0, 10000)
        self.crop_width.setValue(self.source.width()); self.crop_height.setValue(self.source.height()); self.crop_x.setValue(0); self.crop_y.setValue(0)
        form.addRow("左边距", self.crop_x); form.addRow("上边距", self.crop_y); form.addRow("裁剪宽度", self.crop_width); form.addRow("裁剪高度", self.crop_height); outer.addLayout(form)
        for field in (self.crop_x, self.crop_y, self.crop_width, self.crop_height): field.valueChanged.connect(self._render)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton"); buttons.button(QDialogButtonBox.StandardButton.Save).setText("使用此封面")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton"); buttons.rejected.connect(self.reject); buttons.accepted.connect(self._accept); outer.addWidget(buttons)
        self._render()

    def _rect(self):
        x = min(max(self.crop_x.value(), 0), max(self.source.width() - 1, 0))
        y = min(max(self.crop_y.value(), 0), max(self.source.height() - 1, 0))
        w = max(1, min(self.crop_width.value(), self.source.width() - x))
        h = max(1, min(self.crop_height.value(), self.source.height() - y))
        return x, y, w, h

    def _render(self):
        if self.source.isNull(): return
        rect = self._rect(); cropped = self.source.copy(*rect)
        self.preview.setPixmap(cropped.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _accept(self):
        self.cropped = self.source.copy(*self._rect()); self.accept()


class AnimeDialog(QDialog):
    """A non-blocking editor that keeps the main window available while open."""

    submitted = pyqtSignal(dict)

    def __init__(self, item=None, parent=None, groups=()):
        super().__init__(parent)
        self.item = dict(item or {})
        self.setObjectName("animeDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle("编辑番剧" if item else "添加番剧")
        self.setMinimumSize(590, 680)
        self.resize(620, 720)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(14)

        header = QVBoxLayout()
        header.setSpacing(3)
        header.addWidget(QLabel("番剧信息", objectName="animeDialogTitle"))
        header.addWidget(QLabel("设置放送安排和观看进度，保存后可继续使用主界面。", objectName="animeDialogHint"))
        outer.addLayout(header)

        card = QFrame(objectName="animeDialogCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(13)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(card, 1)

        self.name = QLineEdit(self.item.get("title", ""))
        self.name.setPlaceholderText("例如：葬送的芙莉莲")
        form.addRow("名称", self.name)

        self.category = QComboBox()
        for key, label in CATEGORIES:
            self.category.addItem(label, key)
        self.category.setCurrentIndex(max(0, self.category.findData(self.item.get("category", "watching"))))
        form.addRow("分类", self.category)

        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.group.setAccessibleName("自定义分组，可选择或输入")
        self.group.addItems(anime_groups([self.item], groups))
        self.group.setCurrentText(group_name(self.item.get("group")))
        self.group.lineEdit().setPlaceholderText("选择已有分组，或输入新分组")
        self.group.lineEdit().setClearButtonEnabled(True)
        self.group.lineEdit().setMaxLength(80)
        form.addRow("自定义分组", self.group)

        today = date.today()
        start = QDate.fromString(self.item.get("start_date", today.isoformat()), "yyyy-MM-dd")
        end = QDate.fromString(self.item.get("end_date", (today + timedelta(days=84)).isoformat()), "yyyy-MM-dd")
        self.start_date = QDateEdit(start if start.isValid() else QDate.currentDate())
        self.start_date.setCalendarPopup(True)
        form.addRow("放送开始", self.start_date)
        self.end_date = QDateEdit(end if end.isValid() else QDate.currentDate().addDays(84))
        self.end_date.setCalendarPopup(True)
        form.addRow("放送结束", self.end_date)

        self.weekday = QComboBox()
        for index, day_name in enumerate(WEEKDAY_NAMES):
            self.weekday.addItem("周" + day_name, index)
        days = self.item.get("air_days", [0])
        self.weekday.setCurrentIndex(days[0] if days and isinstance(days[0], int) else 0)
        form.addRow("每周更新日", self.weekday)

        self._schedule_fields = [self.start_date, self.end_date, self.weekday]
        self.category.currentIndexChanged.connect(self._toggle_schedule_fields)
        self._toggle_schedule_fields()

        self.episodes = QSpinBox()
        self.episodes.setRange(1, 999)
        self.episodes.setValue(int(self.item.get("episode_count", 12)))
        self.episodes.valueChanged.connect(self._limit_progress)
        form.addRow("总集数", self.episodes)

        progress_row = QHBoxLayout()
        self.progress = QSpinBox()
        self.progress.setObjectName("animeProgressInput")
        self.progress.setRange(0, self.episodes.value())
        self.progress.setPrefix("第 ")
        self.progress.setSuffix(" 话")
        self.progress.setValue(progress_number(self.item))
        self.progress.setFixedWidth(92)
        progress_row.addWidget(self.progress, 1)
        minus = QPushButton("−", objectName="animeStepButton")
        plus = QPushButton("＋", objectName="animeStepButton")
        minus.setFixedSize(38, 38)
        plus.setFixedSize(38, 38)
        minus.clicked.connect(self.progress.stepDown)
        plus.clicked.connect(self.progress.stepUp)
        progress_row.setSpacing(8)
        progress_row.addWidget(minus)
        progress_row.addWidget(plus)
        form.addRow("观看进度", progress_row)

        self.folder = QLineEdit(self.item.get("folder", ""))
        self.folder.setPlaceholderText("可选：关联本地视频文件夹")
        browse = QPushButton("选择文件夹", objectName="secondaryButton")
        browse.clicked.connect(self._choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("本地文件夹", folder_row)

        self.cover = self.item.get("cover", "")
        self.cover_label = QLabel(objectName="animeDialogCover")
        self.cover_label.setFixedSize(132, 176)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._render_cover()
        upload = QPushButton("上传封面", objectName="secondaryButton")
        upload.clicked.connect(self._choose_cover)
        cover_row = QHBoxLayout()
        cover_row.setSpacing(14)
        cover_row.addWidget(self.cover_label)
        cover_actions = QVBoxLayout()
        cover_actions.setSpacing(6)
        cover_actions.addWidget(upload, 0, Qt.AlignmentFlag.AlignLeft)
        cover_actions.addWidget(QLabel("未上传时使用 TimeTip 默认封面。", objectName="animeDialogHint"))
        cover_actions.addStretch()
        cover_row.addLayout(cover_actions, 1)
        form.addRow("番剧封面", cover_row)

        self.error_label = QLabel(objectName="animeDialogError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        outer.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save_button:
            save_button.setObjectName("primaryButton")
            save_button.setText("保存番剧")
        if cancel_button:
            cancel_button.setObjectName("secondaryButton")
            cancel_button.setText("取消")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _limit_progress(self, value):
        self.progress.setRange(0, value)
        self.progress.setValue(min(self.progress.value(), value))

    def _toggle_schedule_fields(self):
        visible = self.category.currentData() != "backlog"
        for field in self._schedule_fields:
            field.setVisible(visible)
            label = self._form_label(field)
            if label:
                label.setVisible(visible)

    def _form_label(self, field):
        parent = field.parentWidget()
        return parent.layout().labelForField(field) if parent and parent.layout() else None

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择番剧文件夹", self.folder.text() or "")
        if folder:
            self.folder.setText(folder)

    def _choose_cover(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择番剧封面", "", "图片 (*.png *.jpg *.jpeg *.webp)")
        if path:
            crop = CoverCropDialog(path, self)
            if crop.exec() == QDialog.DialogCode.Accepted and crop.cropped:
                target = Path(tempfile.gettempdir()) / f"timetip-cover-{uuid.uuid4().hex}.png"
                crop.cropped.save(str(target), "PNG")
                self.cover = str(target)
                self._render_cover()

    def _render_cover(self):
        source = Path(self.cover) if self.cover and Path(self.cover).is_file() else DEFAULT_ANIME_COVER
        if source.is_file():
            pixmap = QPixmap(str(source)).scaled(
                self.cover_label.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.cover_label.setPixmap(pixmap)
            self.cover_label.setText("")
        else:
            self.cover_label.setText("TimeTip\n番剧封面")

    def values(self):
        backlog = self.category.currentData() == "backlog"
        return {
            "id": self.item.get("id", ""),
            "title": self.name.text().strip(),
            "category": self.category.currentData(),
            "group": group_name(self.group.currentText()),
            "start_date": self.start_date.date().toString("yyyy-MM-dd") if not backlog else "",
            "end_date": self.end_date.date().toString("yyyy-MM-dd") if not backlog else "",
            "air_days": [self.weekday.currentData()] if not backlog else [],
            "episode_count": self.episodes.value(),
            "progress": self.progress.value(),
            "folder": self.folder.text().strip(),
            "cover": self.cover,
        }

    def _submit(self):
        values = self.values()
        try:
            validate_anime(values)
        except ValueError as error:
            self.error_label.setText(str(error))
            self.error_label.show()
            return
        self.error_label.hide()
        self.submitted.emit(values)
        self.accept()
