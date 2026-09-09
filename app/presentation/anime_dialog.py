"""Modal editor for anime entries."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import uuid

from PyQt6.QtCore import QDate, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
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
    QWidget,
)

from app.domain.anime import CATEGORIES, WEEKDAY_NAMES, progress_number, validate_anime


DEFAULT_ANIME_COVER = Path(__file__).resolve().parents[2] / "assets" / "anime-default-cover.png"


class CoverCropCanvas(QWidget):
    """Image canvas with a draggable, resizable crop rectangle."""

    def __init__(self, source: QPixmap, parent=None):
        super().__init__(parent)
        self.source = source
        self.selection = QRect(0, 0, max(1, source.width()), max(1, source.height()))
        self._drag_mode = None
        self._anchor = None
        self._start_selection = None
        self.setMinimumSize(360, 280)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _image_rect(self):
        if self.source.isNull():
            return QRect()
        scale = min(self.width() / self.source.width(), self.height() / self.source.height())
        width = max(1, round(self.source.width() * scale))
        height = max(1, round(self.source.height() * scale))
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def _view_selection(self):
        image = self._image_rect()
        if image.isNull():
            return QRect()
        sx, sy = image.width() / self.source.width(), image.height() / self.source.height()
        return QRect(round(image.left() + self.selection.left() * sx), round(image.top() + self.selection.top() * sy),
                     max(1, round(self.selection.width() * sx)), max(1, round(self.selection.height() * sy)))

    def _source_point(self, point):
        image = self._image_rect()
        if image.isNull():
            return None
        x = round((point.x() - image.left()) * self.source.width() / image.width())
        y = round((point.y() - image.top()) * self.source.height() / image.height())
        return max(0, min(self.source.width(), x)), max(0, min(self.source.height(), y))

    def _hit_test(self, point):
        rect = self._view_selection()
        if rect.isNull():
            return None
        margin = 9
        near_left = abs(point.x() - rect.left()) <= margin
        near_right = abs(point.x() - rect.right()) <= margin
        near_top = abs(point.y() - rect.top()) <= margin
        near_bottom = abs(point.y() - rect.bottom()) <= margin
        if near_left and near_top: return "top-left"
        if near_right and near_top: return "top-right"
        if near_left and near_bottom: return "bottom-left"
        if near_right and near_bottom: return "bottom-right"
        if near_top and rect.left() <= point.x() <= rect.right(): return "top"
        if near_bottom and rect.left() <= point.x() <= rect.right(): return "bottom"
        if near_left and rect.top() <= point.y() <= rect.bottom(): return "left"
        if near_right and rect.top() <= point.y() <= rect.bottom(): return "right"
        if rect.contains(point): return "move"
        return None

    def _set_cursor(self, mode):
        cursors = {"top-left": Qt.CursorShape.SizeFDiagCursor, "bottom-right": Qt.CursorShape.SizeFDiagCursor,
                   "top-right": Qt.CursorShape.SizeBDiagCursor, "bottom-left": Qt.CursorShape.SizeBDiagCursor,
                   "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
                   "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
                   "move": Qt.CursorShape.SizeAllCursor}
        self.setCursor(cursors.get(mode, Qt.CursorShape.ArrowCursor))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.source.isNull():
            return
        self._drag_mode = self._hit_test(event.position().toPoint())
        if self._drag_mode:
            self._anchor = self._source_point(event.position().toPoint())
            self._start_selection = QRect(self.selection)
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if not self._drag_mode:
            self._set_cursor(self._hit_test(point))
            return
        current = self._source_point(point)
        if not current or not self._anchor or not self._start_selection:
            return
        dx, dy = current[0] - self._anchor[0], current[1] - self._anchor[1]
        start = self._start_selection
        minimum = min(16, max(1, min(self.source.width(), self.source.height())))
        if self._drag_mode == "move":
            x = max(0, min(self.source.width() - start.width(), start.x() + dx))
            y = max(0, min(self.source.height() - start.height(), start.y() + dy))
            self.selection = QRect(x, y, start.width(), start.height())
        else:
            left, top, right, bottom = start.left(), start.top(), start.right(), start.bottom()
            if "left" in self._drag_mode: left = max(0, min(right - minimum + 1, start.left() + dx))
            if "right" in self._drag_mode: right = min(self.source.width() - 1, max(left + minimum - 1, start.right() + dx))
            if "top" in self._drag_mode: top = max(0, min(bottom - minimum + 1, start.top() + dy))
            if "bottom" in self._drag_mode: bottom = min(self.source.height() - 1, max(top + minimum - 1, start.bottom() + dy))
            self.selection = QRect(left, top, right - left + 1, bottom - top + 1)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_mode = self._anchor = self._start_selection = None
        self._set_cursor(self._hit_test(event.position().toPoint()))
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151827"))
        if self.source.isNull():
            painter.end(); return
        image = self._image_rect()
        painter.drawPixmap(image, self.source)
        selected = self._view_selection()
        overlay = QColor(8, 10, 18, 165)
        for outside in (QRect(image.left(), image.top(), image.width(), max(0, selected.top() - image.top())),
                        QRect(image.left(), selected.bottom() + 1, image.width(), max(0, image.bottom() - selected.bottom())),
                        QRect(image.left(), selected.top(), max(0, selected.left() - image.left()), selected.height()),
                        QRect(selected.right() + 1, selected.top(), max(0, image.right() - selected.right()), selected.height())):
            if outside.width() > 0 and outside.height() > 0: painter.fillRect(outside, overlay)
        accent = self.palette().color(self.palette().ColorRole.Highlight)
        painter.setPen(QPen(accent, 2)); painter.drawRect(selected)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        handles = [(selected.left(), selected.top()), (selected.center().x(), selected.top()), (selected.right(), selected.top()),
                   (selected.left(), selected.center().y()), (selected.right(), selected.center().y()),
                   (selected.left(), selected.bottom()), (selected.center().x(), selected.bottom()), (selected.right(), selected.bottom())]
        for x, y in handles: painter.drawRect(x - 4, y - 4, 8, 8)
        painter.end()

    def reset(self):
        self.selection = QRect(0, 0, self.source.width(), self.source.height())
        self.update()

    def cropped_pixmap(self):
        return self.source.copy(self.selection) if not self.source.isNull() else QPixmap()


class CoverCropDialog(QDialog):
    """Visual crop tool for uploaded covers."""

    def __init__(self, source: str, parent=None):
        super().__init__(parent)
        self.setObjectName("animeDialog")
        self.setModal(True)
        self.setWindowTitle("裁剪封面")
        self.setMinimumSize(480, 430)
        self.resize(680, 560)
        self.source = QPixmap(source)
        self.cropped = None
        outer = QVBoxLayout(self); outer.setContentsMargins(20, 18, 20, 18); outer.setSpacing(12)
        outer.addWidget(QLabel("拖动选框边缘或四角调整范围，拖动选框内部移动位置。", objectName="animeDialogHint"))
        self.canvas = CoverCropCanvas(self.source, self)
        outer.addWidget(self.canvas, 1)
        action_row = QHBoxLayout(); action_row.setSpacing(8)
        reset = QPushButton("重置选框", objectName="secondaryButton"); reset.clicked.connect(self.canvas.reset); action_row.addWidget(reset); action_row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton"); buttons.button(QDialogButtonBox.StandardButton.Save).setText("使用此封面")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton"); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消"); buttons.rejected.connect(self.reject); buttons.accepted.connect(self._accept); action_row.addWidget(buttons); outer.addLayout(action_row)
        if self.source.isNull():
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
            outer.insertWidget(1, QLabel("无法读取这张图片，请重新选择封面。", objectName="animeDialogHint"))

    def _accept(self):
        self.cropped = self.canvas.cropped_pixmap(); self.accept()


class AnimeDialog(QDialog):
    """A non-blocking editor that keeps the main window available while open."""

    submitted = pyqtSignal(dict)

    def __init__(self, item=None, parent=None):
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
