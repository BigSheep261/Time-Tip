"""Anime-specific cards, episode rows and local-folder dialog."""
from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget

from app.domain.anime import LOCAL_CATEGORIES, anime_days_text, normalize_tags
from app.domain.anime_organization import group_name
from app.presentation.anime_dialog import DEFAULT_ANIME_COVER
from app.presentation.anime_organization import AnimeDragHandle


from app.presentation.chrome import make_app_icon

class AnimeCard(QFrame):
    """A compact poster card used by the anime reminder list."""

    opened = pyqtSignal()

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("animeCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self._drag_start_pos = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 16, 12)
        layout.setSpacing(14)

        self.drag_handle = AnimeDragHandle()
        self.drag_handle.setObjectName("animeCardMeta")
        self.drag_handle.setFixedWidth(20)
        self.drag_handle.setToolTip("拖动卡片调整顺序，也可选中后按 Alt + ↑ / ↓")
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        layout.addWidget(self.drag_handle)
        cover = QLabel()
        cover.setObjectName("animeCover")
        cover.setFixedSize(84, 116)
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cover.setPixmap(self._cover_pixmap(item.get("cover", "")))
        layout.addWidget(cover)

        details = QVBoxLayout()
        details.setSpacing(5)
        title = QLabel(item.get("title", "未命名番剧"))
        title.setObjectName("animeCardTitle")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        title.setToolTip(item.get("title", ""))
        details.addWidget(title)
        category_names = {"backlog": "补番", "watching": "追番", "completed": "已看完"}
        chip = QLabel(category_names.get(item.get("category", "watching"), "追番"))
        chip.setObjectName("animeCategoryChip")
        chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        details.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
        group_chip = QLabel("分组：" + group_name(item.get("group")))
        group_chip.setToolTip(group_name(item.get("group")))
        group_chip.setMinimumWidth(0)
        group_chip.setObjectName("animeCategoryChip")
        group_chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        details.addWidget(group_chip, 0, Qt.AlignmentFlag.AlignLeft)
        raw_progress = item.get("progress", 0)
        try:
            progress_text = f"第 {int(raw_progress or 0)} 集"
        except (TypeError, ValueError):
            progress_text = str(raw_progress)
        try:
            total = int(item.get("episode_count", 12) or 12)
        except (TypeError, ValueError):
            total = 12
        details.addWidget(QLabel(f"{progress_text} / 共 {total} 集", objectName="animeCardMeta"))
        schedule_text = "本地清单 · 无放送安排" if item.get("category") in LOCAL_CATEGORIES else f"{anime_days_text(item)} · {item.get('start_date', '')} 起"
        details.addWidget(QLabel(schedule_text, objectName="animeCardMeta"))
        tags = normalize_tags(item.get("tags", []))
        if tags:
            tag_label = QLabel("标签：" + "、".join(tags), objectName="animeCardMeta")
            tag_label.setToolTip("、".join(tags))
            tag_label.setWordWrap(False)
            details.addWidget(tag_label)
        details.addStretch()
        layout.addLayout(details, 1)

        self.actions_host = QFrame()
        self.actions_host.setObjectName("animeCardActions")
        self.actions_host.setMinimumWidth(0)
        self.actions_host.setMaximumWidth(0)
        self.actions_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        actions = QVBoxLayout(self.actions_host)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addStretch()
        self.edit_button = QPushButton("编辑", objectName="animeEditButton")
        self.delete_button = QPushButton("删除", objectName="animeDeleteButton")
        self.edit_button.setFixedWidth(58)
        self.delete_button.setFixedWidth(58)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        layout.addWidget(self.actions_host)
        self._action_animation = QPropertyAnimation(self.actions_host, b"maximumWidth", self)
        self._action_animation.setDuration(180)
        self._action_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            list_widget = self._list_widget()
            if list_widget:
                for index in range(list_widget.count()):
                    if list_widget.itemWidget(list_widget.item(index)) is self:
                        list_widget.setCurrentRow(index)
                        list_widget.setFocus(Qt.FocusReason.MouseFocusReason)
                        break
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_start_pos is not None and event.buttons() & Qt.MouseButton.LeftButton and
                (event.position().toPoint() - self._drag_start_pos).manhattanLength() >= QApplication.startDragDistance()):
            list_widget = self._list_widget()
            if list_widget and list_widget.dragEnabled():
                self._drag_start_pos = None
                list_widget.startDrag(Qt.DropAction.MoveAction)
                event.accept()
                return
        if event.position().x() >= self.width() - 120:
            self._set_actions_visible(True)
        elif event.position().x() < self.width() - 145:
            self._set_actions_visible(False)
        if event.buttons() & Qt.MouseButton.LeftButton:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _list_widget(self):
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QListWidget):
                return parent
            parent = parent.parentWidget()
        return None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.opened.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self._set_actions_visible(False)
        super().leaveEvent(event)

    def _set_actions_visible(self, visible):
        target = 74 if visible else 0
        if self.actions_host.maximumWidth() == target:
            return
        self._action_animation.stop()
        self._action_animation.setStartValue(self.actions_host.maximumWidth())
        self._action_animation.setEndValue(target)
        self._action_animation.start()

    @staticmethod
    def _cover_pixmap(source: str) -> QPixmap:
        default = DEFAULT_ANIME_COVER
        path = Path(source) if source and Path(source).is_file() else default
        pixmap = QPixmap(str(path)) if path.is_file() else make_app_icon().pixmap(84, 116)
        if pixmap.isNull():
            pixmap = make_app_icon().pixmap(84, 116)
        pixmap = pixmap.scaled(84, 116, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        result = QPixmap(84, 116)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, 84, 116, 11, 11)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        return result


class MarqueeLabel(QLabel):
    """Scroll long filenames only while the pointer is over the row."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text
        self._offset = 0
        self._hovered = False
        self._timer = QTimer(self)
        self._timer.setInterval(36)
        self._timer.timeout.connect(self._advance)
        self.setText(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def setText(self, text):
        self._full_text = str(text)
        self._offset = 0
        super().setText(self._full_text)
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self._start_if_needed()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._timer.stop()
        self._offset = 0
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self._start_if_needed()
        super().resizeEvent(event)

    def _start_if_needed(self):
        if self._hovered and QFontMetrics(self.font()).horizontalAdvance(self._full_text) > self.width():
            self._timer.start()
        else:
            self._timer.stop()

    def _advance(self):
        text_width = QFontMetrics(self.font()).horizontalAdvance(self._full_text)
        if text_width <= self.width():
            self._timer.stop()
            return
        self._offset = (self._offset + 2) % (text_width + 42)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setClipRect(self.rect())
        text_width = QFontMetrics(self.font()).horizontalAdvance(self._full_text)
        x = 0 if text_width <= self.width() else -self._offset
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(x, 0, text_width, self.height(), Qt.AlignmentFlag.AlignVCenter, self._full_text)
        if text_width > self.width() and self._offset > text_width:
            painter.drawText(x + text_width + 42, 0, text_width, self.height(), Qt.AlignmentFlag.AlignVCenter, self._full_text)
        painter.end()


class EpisodeRow(QFrame):
    clicked = pyqtSignal(str, int)

    def __init__(self, path: Path, number: int, parent=None):
        super().__init__(parent)
        self.setObjectName("episodeRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12); shadow.setOffset(0, 2); shadow.setColor(QColor(29, 29, 31, 30))
        self.setGraphicsEffect(shadow)
        layout = QHBoxLayout(self); layout.setContentsMargins(14, 8, 14, 8); layout.setSpacing(12)
        label = QLabel(f"第 {number:02d} 集"); label.setObjectName("episodeNumber"); label.setFixedWidth(62); layout.addWidget(label)
        self.name_label = MarqueeLabel(path.stem); self.name_label.setObjectName("episodeName"); self.name_label.setToolTip(path.name); layout.addWidget(self.name_label, 1)
        self.path = str(path); self.number = number

    def sizeHint(self):
        return QSize(0, 40)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.path, self.number)
        super().mousePressEvent(event)


class AnimeFolderDialog(QDialog):
    """Modal episode browser and progress editor for a local anime folder."""

    progressSaved = pyqtSignal(int)

    VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setObjectName("animeDialog")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(item.get("title", "番剧详情"))
        self.setMinimumSize(560, 520)
        self.resize(620, 620)
        outer = QVBoxLayout(self); outer.setContentsMargins(22, 20, 22, 20); outer.setSpacing(14)
        header = QHBoxLayout()
        cover = QLabel(); cover.setObjectName("animeDialogCover"); cover.setFixedSize(86, 116); cover.setPixmap(AnimeCard._cover_pixmap(item.get("cover", ""))); header.addWidget(cover)
        intro = QVBoxLayout(); intro.addWidget(QLabel(item.get("title", "未命名番剧"), objectName="animeDialogTitle"))
        names = {"backlog": "补番", "watching": "追番", "completed": "已看完"}
        intro.addWidget(QLabel(names.get(item.get("category", "watching"), "追番"), objectName="animeCategoryChip"))
        if item.get("category") in LOCAL_CATEGORIES:
            intro.addWidget(QLabel("本地清单 · 未设置放送安排", objectName="animeDialogHint"))
        else:
            intro.addWidget(QLabel(f"放送：{item.get('start_date', '')} 至 {item.get('end_date', '')}", objectName="animeDialogHint"))
            intro.addWidget(QLabel(f"更新日：{anime_days_text(item)}", objectName="animeDialogHint"))
        intro.addStretch(); header.addLayout(intro, 1); outer.addLayout(header)

        self.episode_list = QListWidget(objectName="episodeListPanel")
        folder = Path(item.get("folder", "")) if item.get("folder") else None
        self.files = self._video_files(folder)
        if self.files:
            for index, path in enumerate(self.files, 1):
                episode = EpisodeRow(path, index)
                row = QListWidgetItem(); row.setSizeHint(QSize(0, 48)); self.episode_list.addItem(row)
                episode.clicked.connect(self._play_episode_path); self.episode_list.setItemWidget(row, episode)
            self.episode_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            outer.addWidget(QLabel(f"检测到 {len(self.files)} 个视频文件（点击集数开始播放）", objectName="animeDialogHint"))
            self.episode_list.setMinimumHeight(min(320, max(128, len(self.files) * 34)))
            outer.addWidget(self.episode_list, 1)
        else:
            empty = QLabel("未绑定本地文件夹，或文件夹内没有可识别的视频。\n你仍可以在这里查看番剧信息并设置观看进度。", objectName="animeDialogHint"); empty.setWordWrap(True); outer.addWidget(empty); outer.addStretch(1)

        total = int(item.get("episode_count", 12) or 12)
        progress_row = QHBoxLayout(); progress_row.setSpacing(8); progress_row.addWidget(QLabel("当前观看到", objectName="fieldLabel"))
        self.progress = QSpinBox(); self.progress.setObjectName("animeProgressInput"); self.progress.setRange(0, total); self.progress.setValue(min(max(self._progress_number(item), 0), self.progress.maximum())); self.progress.setFixedWidth(82); progress_row.addWidget(self.progress)
        minus = QPushButton("−", objectName="animeStepButton"); plus = QPushButton("＋", objectName="animeStepButton"); minus.setFixedSize(38, 38); plus.setFixedSize(38, 38); minus.clicked.connect(self.progress.stepDown); plus.clicked.connect(self.progress.stepUp); progress_row.addWidget(minus); progress_row.addWidget(plus)
        progress_row.addWidget(QLabel(f"/ {total} 集", objectName="animeDialogHint")); progress_row.addStretch(); outer.addLayout(progress_row)
        self.feedback = QLabel("", objectName="animeDialogHint"); outer.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton"); buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存进度")
        buttons.button(QDialogButtonBox.StandardButton.Close).setObjectName("secondaryButton"); buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.accepted.connect(self._save_progress); buttons.rejected.connect(self.reject); outer.addWidget(buttons)
        QTimer.singleShot(0, self._fit_to_content)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_episode_rows()

    def _fit_episode_rows(self):
        if not hasattr(self, "episode_list"): return
        width = max(0, self.episode_list.viewport().width())
        for index in range(self.episode_list.count()):
            row = self.episode_list.itemWidget(self.episode_list.item(index))
            if row is not None:
                row.setFixedWidth(width)

    def _fit_to_content(self):
        hint = self.sizeHint()
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        width = min(max(hint.width(), 560), available.width() - 48 if available else 760)
        height = min(max(hint.height(), 420), available.height() - 48 if available else 760)
        self.resize(width, height)

    @staticmethod
    def _progress_number(item):
        value = item.get("progress", 0)
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        return int(digits or 0)

    @classmethod
    def _video_files(cls, folder):
        if not folder or not folder.is_dir(): return []
        files = [path for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in cls.VIDEO_EXTENSIONS]
        def natural(path):
            return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]
        return sorted(files, key=natural)

    def _play_episode_path(self, path, number):
        try:
            os.startfile(path)
            self.progress.setValue(number)
            self.feedback.setText("已打开默认播放器。保存进度即可记录当前集数。")
        except OSError as error:
            self.feedback.setText(f"无法打开视频：{error}")

    def _save_progress(self):
        self.progressSaved.emit(self.progress.value())
        self.accept()


