from __future__ import annotations

import uuid
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta

from PyQt6.QtCore import QByteArray, QDate, QEasingCurve, QPoint, QPropertyAnimation, QSize, QTime, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPixmap, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QBoxLayout,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSpinBox,
    QProgressBar,
    QStackedWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QSystemTrayIcon,
)

from app.domain.salary import DEFAULT_SALARY, salary_snapshot, validate_salary
from app.domain.layout import WIDGET_SIZES
from app.domain.countdowns import countdown_snapshot
from app.domain.anime import LOCAL_CATEGORIES, anime_for_date, anime_days_text, episode_label, episode_dates, normalize_tags, validate_anime
from app.domain.anime_organization import anime_groups, group_name, reorder_anime
from app.domain.dates import format_dashboard_date, DATE_FORMATS
from app.presentation.anime_dialog import AnimeDialog, DEFAULT_ANIME_COVER
from app.presentation.anime_organization import AnimeDragHandle, AnimeGroupsDialog, AnimeListWidget
from app.presentation.countdowns import CountdownPageMixin
from app.presentation.memos import MemoPageMixin
from app.presentation.emojis import EmojiPageMixin
from app.presentation.jm_manga import JMMangaPageMixin
from app.presentation.widgets import Card, DashboardTile, ResizeHandle, WidgetGrid
from app.infrastructure.store import Store
from app.infrastructure import startup
from app.infrastructure.updater import Updater
from app.version import DISPLAY_VERSION
from app.presentation.theme import (APP_NAME, PRIMARY, apply_theme, available_themes,
                                     get_theme, set_feedback_state)


def make_app_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(PRIMARY))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 18, 18)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Arial", 25, QFont.Weight.Bold))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()
    return QIcon(pix)


class ThemeLogo(QAbstractButton):
    """Animated theme-aware logo used by the title bar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("连续点击三次切换日间 / 夜间模式")
        self.setAccessibleName("主题切换 Logo")
        self._theme = get_theme("light")
        self._pulse = 1.0
        self._rotation = 0.0
        self._animation = None

    @pyqtProperty(float)
    def pulse(self):
        return self._pulse

    @pulse.setter
    def pulse(self, value):
        self._pulse = float(value)
        self.update()

    @pyqtProperty(float)
    def rotation(self):
        return self._rotation

    @rotation.setter
    def rotation(self, value):
        self._rotation = float(value)
        self.update()

    def set_theme(self, theme):
        self._theme = theme
        self._pulse = 1.0
        self._start_animation()
        self.update()

    def _start_animation(self):
        from PyQt6.QtCore import QParallelAnimationGroup
        if self._animation is not None:
            self._animation.stop()
        group = QParallelAnimationGroup(self)
        pulse = QPropertyAnimation(self, b"pulse", group)
        pulse.setDuration(460); pulse.setStartValue(1.0); pulse.setKeyValueAt(0.45, 1.16); pulse.setEndValue(1.0)
        pulse.setEasingCurve(QEasingCurve.Type.OutBack)
        rotate = QPropertyAnimation(self, b"rotation", group)
        # A full turn keeps the familiar T upright when the motion settles.
        rotate.setDuration(520); rotate.setStartValue(self._rotation); rotate.setEndValue(self._rotation + 360)
        rotate.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(pulse); group.addAnimation(rotate)
        self._animation = group
        group.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = 34 * self._pulse
        painter.translate(int(self.width() / 2), int(self.height() / 2))
        painter.rotate(self._rotation)
        painter.translate(int(-size / 2), int(-size / 2))
        primary = QColor(self._theme.colors["primary_button"])
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(primary)
        painter.drawRoundedRect(0, 0, int(size), int(size), 11, 11)
        painter.setPen(QColor(self._theme.colors["on_primary"]))
        painter.setFont(QFont("Arial", max(15, round(21 * self._pulse)), QFont.Weight.Bold))
        painter.drawText(0, 0, int(size), int(size), Qt.AlignmentFlag.AlignCenter, "T")
        # A small sun/moon badge makes the state legible even while the animation rests.
        badge = QColor(self._theme.colors["on_primary"])
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(badge)
        painter.drawEllipse(int(size - 11), 3, 8, 8)
        if self._theme.is_dark:
            painter.setBrush(primary)
            painter.drawEllipse(int(size - 8), 2, 8, 8)
        painter.end()


class TitleBar(QFrame):
    moved = pyqtSignal(QPoint)

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self._drag_pos: QPoint | None = None
        self.setFixedHeight(62)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 18, 8)
        layout.setSpacing(10)
        self.logo = ThemeLogo()
        self._logo_clicks = 0
        self._logo_timer = QTimer(self)
        self._logo_timer.setSingleShot(True)
        self._logo_timer.setInterval(650)
        self._logo_timer.timeout.connect(self._reset_logo_clicks)
        self.logo.clicked.connect(self._logo_clicked)
        layout.addWidget(self.logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel("你的节奏，由你掌握")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch()
        for text, tip, slot in [("—", "最小化", window.showMinimized), ("□", "最大化 / 还原", window.toggle_maximized), ("×", "关闭到托盘", window.close)]:
            button = QPushButton(text)
            button.setObjectName("windowButton")
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setFixedSize(34, 34)
            button.clicked.connect(slot)
            layout.addWidget(button)

    def _reset_logo_clicks(self):
        self._logo_clicks = 0

    def _logo_clicked(self):
        self._logo_clicks += 1
        if self._logo_clicks >= 3:
            self._reset_logo_clicks()
            self.window.toggle_theme()
        else:
            self._logo_timer.start()

    def set_theme(self, theme):
        self.logo.set_theme(theme)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window.windowHandle() and self.window.windowHandle().startSystemMove():
                return
            self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.toggle_maximized()


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


class TimeTipWindow(JMMangaPageMixin, EmojiPageMixin, MemoPageMixin, CountdownPageMixin, QMainWindow):
    def __init__(self, store: Store | None = None) -> None:
        super().__init__()
        self.store = store or Store()
        # Apply the persisted theme before constructing widgets so every child starts
        # with the right palette; later changes reuse the same window and widgets.
        self.theme = apply_theme(QApplication.instance(), self.store.get("theme", "light"))
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.setMinimumSize(860, 620)
        self.resize(1220, 830)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.last_reminder_check = set()
        self.pomodoro_running = False
        self.pomodoro_mode = "work"
        self.pomodoro_remaining = 25 * 60
        self.pomodoro_deadline = None
        self.store.migrate_collections()
        self.countdowns = self.store.load_collection("countdowns")
        self.memos = self.store.load_collection("memos")
        self.anime = self.store.anime()
        self.active_countdown_id = None
        self.active_memo_id = None
        self.deleted_countdown = None
        self.deleted_memo = None
        self.widget_config = self.store.read_json("widgets", {})
        if not isinstance(self.widget_config, dict):
            self.widget_config = {}
        self.tiles = {}
        saved_salary = self.store.read_json("salary", {})
        self.salary_config = {**DEFAULT_SALARY, **saved_salary} if isinstance(saved_salary, dict) else DEFAULT_SALARY.copy()
        try:
            validate_salary(self.salary_config)
        except (ValueError, TypeError, KeyError):
            self.salary_config = DEFAULT_SALARY.copy()
        self.quitting = False
        self._jm_unlock_clicks = 0
        self._jm_unlock_timer = QTimer(self)
        self._jm_unlock_timer.setSingleShot(True)
        self._jm_unlock_timer.setInterval(1600)
        self._jm_unlock_timer.timeout.connect(self._reset_jm_unlock_clicks)
        self.updater = Updater(self)
        self.updater.update_available.connect(self._on_update_available)
        self.updater.no_update.connect(self._on_no_update)
        self.updater.download_progress.connect(self._on_update_progress)
        self.updater.download_ready.connect(self._on_update_downloaded)
        self.updater.failed.connect(self._on_update_failed)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("显示 TimeTip", self.restore_window)
        menu.addAction("退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.restore_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self._build_ui()
        self._load_settings()
        self._setup_resize()
        self._start_timers()
        self._tick()

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def set_theme(self, theme_id: str) -> None:
        """Switch the theme in place; timers, pages, edits and window state survive."""
        self.theme = apply_theme(QApplication.instance(), theme_id)
        self.store.set("theme", self.theme.id)
        if hasattr(self, "title_bar"):
            self.title_bar.set_theme(self.theme)
        if hasattr(self, "theme_combo"):
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.theme.id)))
            self.theme_combo.blockSignals(False)
            self.theme_description.setText(self.theme.description)
        # Date marks use the accent color and therefore need repainting too.
        if hasattr(self, "calendar"):
            self._update_summary()

    def toggle_theme(self) -> None:
        ids = [theme.id for theme in available_themes()]
        current = ids.index(self.theme.id) if self.theme.id in ids else 0
        self.set_theme(ids[(current + 1) % len(ids)])

    def _reset_jm_unlock_clicks(self) -> None:
        self._jm_unlock_clicks = 0

    def _unlock_jm_mode(self) -> None:
        if self.jm_nav_button.isVisible():
            self.jm_unlock_feedback.setText("JM漫画下载模块已显示在左侧导航栏。")
            return
        self._jm_unlock_clicks += 1
        self._jm_unlock_timer.start()
        remaining = max(0, 5 - self._jm_unlock_clicks)
        if remaining:
            self.jm_unlock_feedback.setText(f"再点击 {remaining} 次显示 JM漫画下载模块。")
            return
        self._reset_jm_unlock_clicks()
        self.jm_nav_button.setVisible(True)
        self.jm_unlock_feedback.setText("JM漫画下载模块已显示在左侧导航栏。")
        self.jm_unlock_button.setText("已解锁")
        self._switch_page(8)

    def save_theme(self) -> None:
        if hasattr(self, "theme_combo") and self.theme_combo.currentData():
            self.set_theme(self.theme_combo.currentData())

    def refresh_theme_options(self) -> None:
        """Refresh settings after an extension registers a new theme at runtime."""
        if not hasattr(self, "theme_combo"):
            return
        current = self.theme.id
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        for theme in available_themes():
            self.theme_combo.addItem(theme.label, theme.id)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(current)))
        self.theme_combo.blockSignals(False)
        self.theme_description.setText(self.theme.description)

    def _setup_resize(self):
        E, C = Qt.Edge, Qt.CursorShape
        specs = [(E.LeftEdge, C.SizeHorCursor), (E.RightEdge, C.SizeHorCursor),
                 (E.TopEdge, C.SizeVerCursor), (E.BottomEdge, C.SizeVerCursor),
                 (E.LeftEdge | E.TopEdge, C.SizeFDiagCursor), (E.RightEdge | E.TopEdge, C.SizeBDiagCursor),
                 (E.LeftEdge | E.BottomEdge, C.SizeBDiagCursor), (E.RightEdge | E.BottomEdge, C.SizeFDiagCursor)]
        self.resize_handles = [ResizeHandle(self, edges, cursor) for edges, cursor in specs]
        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.timeout.connect(self.save_window_geometry)
        geometry = self.store.get("window_geometry")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii", errors="ignore")))
        self._position_handles()

    def _position_handles(self):
        if not hasattr(self, "resize_handles"):
            return
        w, h, edge, corner = self.width(), self.height(), 6, 16
        rects = [(0, corner, edge, h - corner * 2), (w-edge, corner, edge, h-corner*2),
                 (corner, 0, w-corner*2, edge), (corner, h-edge, w-corner*2, edge),
                 (0, 0, corner, corner), (w-corner, 0, corner, corner),
                 (0, h-corner, corner, corner), (w-corner, h-corner, corner, corner)]
        for handle, rect in zip(self.resize_handles, rects):
            handle.setGeometry(*rect)
            handle.setVisible(not self.isMaximized())
            handle.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_handles()
        if hasattr(self, "calendar_content_layout"):
            self.calendar_content_layout.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 1100 else QBoxLayout.Direction.TopToBottom)
        if hasattr(self, "geometry_timer"):
            self.geometry_timer.start(500)

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "geometry_timer"):
            self.geometry_timer.start(500)

    def save_window_geometry(self):
        self.store.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))

    def restore_window(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        if not self.save_memo():
            return
        if hasattr(self, "jm_shutdown"):
            self.jm_shutdown()
        self.quitting = True
        self.save_window_geometry()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if not self.save_memo():
            event.ignore()
            return
        self.save_window_geometry()
        if not self.quitting and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def notify(self, text: str) -> None:
        QApplication.beep()
        if self.tray.isVisible():
            self.tray.showMessage(APP_NAME, text, QSystemTrayIcon.MessageIcon.Information, 7000)
        else:
            box = QMessageBox(QMessageBox.Icon.Information, APP_NAME, text, parent=self)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()
            self.notification_box = box

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        self.title_bar.set_theme(self.theme)
        root_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 0, 18, 18)
        body_layout.setSpacing(14)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(152)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(10, 14, 10, 14)
        side_layout.setSpacing(7)
        side_label = QLabel("工作台")
        side_label.setObjectName("sectionLabel")
        side_layout.addWidget(side_label)
        self.nav_buttons: list[QPushButton] = []
        nav_by_index = {}
        for text, page_index in [("概览", 0), ("日历提醒", 1), ("番茄钟", 2), ("备忘录", 3), ("倒计时", 4), ("设置", 5), ("表情包", 7), ("看番提醒", 6), ("JM漫画下载", 8)]:
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(44)
            button.clicked.connect(lambda _checked, i=page_index: self._switch_page(i))
            nav_by_index[page_index] = button
        # Keep page-index order for state updates while placing 设置 at the end.
        for page_index in (0, 1, 2, 3, 4, 7, 6, 5):
            side_layout.addWidget(nav_by_index[page_index])
        self.jm_nav_button = nav_by_index[8]
        self.jm_nav_button.setVisible(False)
        side_layout.addWidget(self.jm_nav_button)
        # Keep the public legacy list stable for existing integrations; JM is
        # an opt-in navigation item tracked separately until it is unlocked.
        self.nav_buttons = [nav_by_index[index] for index in range(8)]
        self._all_nav_buttons = self.nav_buttons + [self.jm_nav_button]
        side_layout.addStretch()
        hint = QLabel(f"私人效率工具 {DISPLAY_VERSION}\n数据仅保存在本机")
        hint.setObjectName("sideHint")
        side_layout.addWidget(hint)
        body_layout.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._dashboard_page())
        self.pages.addWidget(self._scroll_page(self._calendar_page()))
        self.pages.addWidget(self._scroll_page(self._focus_page()))
        self.pages.addWidget(self._memo_page())
        self.pages.addWidget(self._countdowns_page())
        self.pages.addWidget(self._settings_page())
        self.pages.addWidget(self._anime_page())
        self.pages.addWidget(self._emoji_page())
        self.pages.addWidget(self._scroll_page(self._jm_page()))
        body_layout.addWidget(self.pages, 1)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self.nav_buttons[0].setChecked(True)

    def _scroll_page(self, page):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        welcome = QVBoxLayout()
        welcome.addWidget(QLabel("概览", objectName="pageTitle"))
        self.day_label = QLabel("", objectName="pageSubtitle")
        welcome.addWidget(self.day_label)
        header.addLayout(welcome, 1)
        add_countdown = QPushButton("＋ 倒计时", objectName="secondaryButton")
        add_countdown.clicked.connect(lambda: (self._switch_page(4), self.new_countdown()))
        header.addWidget(add_countdown)
        self.edit_layout_button = QPushButton("编辑布局", objectName="secondaryButton")
        self.edit_layout_button.setCheckable(True)
        self.edit_layout_button.toggled.connect(self._toggle_layout_editing)
        header.addWidget(self.edit_layout_button)
        layout.addLayout(header)
        self.layout_hint = QLabel("拖动组件调整位置，点击右上角 ··· 调整大小、顺序或隐藏；隐藏的组件可在设置中恢复。", objectName="pageSubtitle")
        self.layout_hint.setWordWrap(True)
        self.layout_hint.hide()
        layout.addWidget(self.layout_hint)
        self.grid = WidgetGrid()
        self.grid.tileMoved.connect(lambda key, target: self._change_widget(key, "move_to", target))
        self.dashboard_scroll = self._scroll_page(self.grid)
        layout.addWidget(self.dashboard_scroll, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("按你的节奏，安排每一格。", objectName="cardHint"))
        footer.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("拖动调整窗口大小")
        footer.addWidget(self.size_grip)
        layout.addLayout(footer)
        return page

    def _widget_specs(self):
        specs = [("countdown:" + item["id"], item["title"], (2, 2) if i == 0 else (2, 1), "purple") for i, item in enumerate(self.countdowns)]
        specs += [("salary", "今日已赚", (2, 1), "green"), ("clock", "现在", (1, 1), "plain"),
                  ("focus", "番茄钟", (1, 1), "plain"), ("reminders", "日历提醒", (2, 1), "plain")]
        specs += [("memo:" + item["id"], item["title"] or "未命名备忘录", (2, 1), "plain") for item in self.memos]
        if self.anime:
            specs.append(("anime", "番剧更新", (2, 1), "plain"))
        return specs

    def _widget_state(self, key, size):
        state = self.widget_config.get(key, {})
        if not isinstance(state, dict):
            state = {}
        if not isinstance(state.get("size"), (list, tuple)) or tuple(state["size"]) not in WIDGET_SIZES:
            state["size"] = list(size)
        state.setdefault("visible", True)
        state.setdefault("order", 10000)
        if not isinstance(state["order"], (float, int)):
            state["order"] = 10000
        self.widget_config[key] = state
        return state

    def _ordered_specs(self):
        specs = self._widget_specs()
        return sorted(specs, key=lambda spec: self._widget_state(spec[0], spec[2])["order"])

    def _rebuild_dashboard(self):
        # Reuse existing tiles so reorder and resize operations animate in place.
        previous = self.tiles
        self.tiles = {}
        for key, title, default_size, tone in self._ordered_specs():
            state = self._widget_state(key, default_size)
            if not state["visible"]:
                continue
            tile = previous.pop(key, None)
            if tile is None:
                tile = DashboardTile(key, title, tuple(state["size"]), tone)
                tile.changed.connect(self._change_widget)
                tile.opened.connect(self._open_widget)
            else:
                tile.update_spec(title, tuple(state["size"]), tone)
            tile.set_editing(self.edit_layout_button.isChecked())
            self.tiles[key] = tile
        for tile in previous.values():
            tile.hide()
            tile.deleteLater()
        self.grid.set_tiles(list(self.tiles.values()))
        self._render_dashboard(datetime.now())

    def _toggle_layout_editing(self, editing):
        self.edit_layout_button.setText("完成布局" if editing else "编辑布局")
        self.layout_hint.setVisible(editing)
        self.grid.set_editing(editing)
        for tile in self.tiles.values():
            tile.set_editing(editing)

    def _change_widget(self, key, action, value):
        state = self.widget_config[key]
        if action == "size" and tuple(value) in WIDGET_SIZES:
            state["size"] = list(value)
        elif action == "visible":
            state["visible"] = bool(value)
        elif action == "move":
            keys = [spec[0] for spec in self._ordered_specs()]
            index = keys.index(key)
            target = max(0, min(len(keys) - 1, index + value))
            keys[index], keys[target] = keys[target], keys[index]
            for order, item_key in enumerate(keys):
                self.widget_config[item_key]["order"] = order
        elif action == "move_to":
            keys = [spec[0] for spec in self._ordered_specs()]
            if key in keys:
                keys.remove(key)
                target = max(0, min(len(keys), int(value)))
                keys.insert(target, key)
                for order, item_key in enumerate(keys):
                    self.widget_config[item_key]["order"] = order
        self.store.write_json("widgets", self.widget_config)
        self._rebuild_dashboard()
        self._refresh_widget_settings()

    def _open_widget(self, key):
        if key.startswith("countdown:"):
            self._switch_page(4)
            self._select_list_id(self.countdown_list, key.split(":", 1)[1])
        elif key.startswith("memo:"):
            self._switch_page(3)
            self._select_list_id(self.memo_list, key.split(":", 1)[1])
        else:
            self._switch_page({"salary": 5, "clock": 1, "focus": 2, "reminders": 1, "anime": 6}[key])

    def _render_dashboard(self, now):
        for key, tile in self.tiles.items():
            if key == "clock":
                tile.value_label.setText(now.strftime("%H:%M:%S"))
                tile.hint_label.setText(now.strftime("%m月%d日") + " · 星期" + "一二三四五六日"[now.weekday()])
                tile.detail_label.setText("此刻，也是一个新的开始。")
                tile.open_button.setText("查看日历  →")
            elif key == "salary":
                try:
                    result = salary_snapshot(self.salary_config, now)
                    tile.value_label.setText(f"¥ {result['earned']:,.2f}")
                    tile.title_label.setText("今日已赚" if result["day"] == now.date() else result["day"].strftime("%m月%d日班次已赚"))
                    tile.hint_label.setText(result["status"] + " · " + result["detail"])
                    tile.detail_label.setText(f"本班次预计 ¥ {result['daily']:,.2f}\n每秒 ¥ {result['per_second']:.4f} · 本月 {result['workdays']} 个工作日")
                except (ValueError, TypeError, KeyError):
                    tile.value_label.setText("开启工资时钟")
                    tile.hint_label.setText("填写月薪与工作时间")
                    tile.detail_label.setText("看见每一秒的付出。仅在设置的工作时段累计。")
                tile.open_button.setText("工资设置  →")
            elif key == "focus":
                m, sec = divmod(max(0, self.pomodoro_remaining), 60)
                tile.value_label.setText(f"{m:02d}:{sec:02d}")
                tile.hint_label.setText(("专注" if self.pomodoro_mode == "work" else "休息") + ("中" if self.pomodoro_running else " · 待开始"))
                tile.detail_label.setText(f"专注 {self.work_spin.value()} 分钟，休息 {self.break_spin.value()} 分钟。")
                tile.open_button.setText("进入番茄钟  →")
            elif key == "reminders":
                reminders = self.store.reminders()
                pending = [r for r in reminders if not r.get("notified")]
                tile.value_label.setText(f"{len(pending)} 条待提醒")
                next_item = min(pending, key=lambda r: r["date"] + r.get("time", "09:00"), default=None)
                tile.hint_label.setText(next_item["text"] if next_item else "所有安排，心中有数")
                tile.detail_label.setText((next_item["date"] + "  " + next_item.get("time", "09:00")) if next_item else "在日历中添加接下来的安排。")
            elif key.startswith("countdown:"):
                item = next((item for item in self.countdowns if key == "countdown:" + item["id"]), None)
                if item:
                    snapshot = countdown_snapshot(item, now)
                    value = snapshot["text"]
                    if tile.width() < 260:
                        value = value.replace("天 ", "天\n")
                    tile.value_label.setText(value)
                    tile.hint_label.setText(snapshot["hint"])
                    tile.detail_label.setText(snapshot["detail"])
            elif key == "anime":
                today = anime_for_date(self.anime, now.date())
                cover = next((a.get("cover") for a in today if a.get("cover")), next((a.get("cover") for a in self.anime if a.get("cover")), ""))
                default_cover = DEFAULT_ANIME_COVER
                cover_path = Path(cover) if cover and Path(cover).is_file() else default_cover
                pixmap = QPixmap(str(cover_path)) if cover_path.is_file() else make_app_icon().pixmap(96, 96)
                tile.value_label.setPixmap(pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                tile.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tile.hint_label.setText("、".join(a["title"] for a in today) if today else "今天没有番剧更新")
                tile.detail_label.setText("\n".join(f'{a["title"]} · {episode_label(a)}' for a in today) or "在看番提醒页添加追番。")
                tile.open_button.setText("管理看番提醒  →")
            elif key.startswith("memo:"):
                item = next((item for item in self.memos if key == "memo:" + item["id"]), None)
                if item:
                    tile.value_label.setStyleSheet("font-size: 19px; font-weight: 600;")
                    lines = item["text"].strip().splitlines()
                    tile.value_label.setText(lines[0] if lines else "记下一点灵感")
                    tile.hint_label.setText(f"{len(item['text'])} 字 · 自动保存")
                    tile.detail_label.setText("\n".join(lines[1:6])[:300] or "点击下方继续记录。")
                    tile.open_button.setText("打开备忘录  →")

    def _calendar_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        title = QLabel("日历提醒")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        sub = QLabel("选中日期，添加只属于你的提醒。")
        sub.setObjectName("pageSubtitle")
        layout.addWidget(sub)
        content = QVBoxLayout()
        self.calendar_content_layout = content
        content.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 1100 else QBoxLayout.Direction.TopToBottom)
        content.setSpacing(14)
        cal_card = Card()
        cal_layout = QVBoxLayout(cal_card)
        cal_layout.setContentsMargins(14, 14, 14, 14)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.selectionChanged.connect(lambda: self._calendar_selected(self.calendar.selectedDate()))
        cal_layout.addWidget(self.calendar)
        content.addWidget(cal_card, 3)
        form = Card()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(18, 18, 18, 18)
        self.selected_date_label = QLabel("")
        self.selected_date_label.setObjectName("cardTitle")
        form_layout.addWidget(self.selected_date_label)
        field_label = QLabel("提醒内容")
        field_label.setObjectName("fieldLabel")
        form_layout.addWidget(field_label)
        self.reminder_input = QLineEdit()
        self.reminder_input.setPlaceholderText("例如：给妈妈打电话")
        self.reminder_input.setMinimumHeight(42)
        form_layout.addWidget(self.reminder_input)
        form_layout.addWidget(QLabel("提醒时间（电脑本地时间）", objectName="fieldLabel"))
        self.reminder_time = QTimeEdit(QTime(9, 0))
        self.reminder_time.setDisplayFormat("HH:mm")
        self.reminder_time.setMinimumHeight(38)
        form_layout.addWidget(self.reminder_time)
        form_layout.addWidget(QLabel("提醒模式", objectName="fieldLabel"))
        self.reminder_mode = QComboBox()
        self.reminder_mode.addItem("需要电脑提醒", "notify")
        self.reminder_mode.addItem("仅在日历显示", "calendar")
        self.reminder_mode.setMinimumHeight(38)
        form_layout.addWidget(self.reminder_mode)
        add = QPushButton("添加提醒")
        add.setObjectName("primaryButton")
        add.setMinimumHeight(42)
        add.clicked.connect(self.add_reminder)
        form_layout.addWidget(add)
        form_layout.addSpacing(12)
        list_label = QLabel("已有提醒")
        list_label.setObjectName("fieldLabel")
        form_layout.addWidget(list_label)
        self.reminder_list = QListWidget()
        self.reminder_list.setWordWrap(True)
        self.reminder_list.setObjectName("cleanList")
        form_layout.addWidget(self.reminder_list, 1)
        remove = QPushButton("删除选中提醒")
        remove.setObjectName("secondaryButton")
        remove.clicked.connect(self.remove_reminder)
        form_layout.addWidget(remove)
        content.addWidget(form, 2)
        layout.addLayout(content, 1)
        return page

    def _focus_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        title = QLabel("番茄钟")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("把时间切成专注而轻盈的片段。")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)
        timer_card = Card("focusCard")
        timer_layout = QVBoxLayout(timer_card)
        timer_layout.setContentsMargins(26, 28, 26, 28)
        self.focus_mode_label = QLabel("专注时段")
        self.focus_mode_label.setObjectName("eyebrow")
        self.focus_mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.focus_mode_label)
        self.focus_time_label = QLabel("25:00")
        self.focus_time_label.setObjectName("focusTime")
        self.focus_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.focus_time_label)
        controls = QHBoxLayout()
        controls.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_start = QPushButton("开始专注")
        self.focus_start.setObjectName("primaryButton")
        self.focus_start.setMinimumSize(130, 44)
        self.focus_start.clicked.connect(self.toggle_focus)
        reset = QPushButton("重置")
        reset.setObjectName("secondaryButton")
        reset.setMinimumSize(90, 44)
        reset.clicked.connect(self.reset_focus)
        controls.addWidget(self.focus_start)
        controls.addSpacing(10)
        controls.addWidget(reset)
        timer_layout.addLayout(controls)
        layout.addWidget(timer_card)
        settings_card = Card()
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(20, 18, 20, 18)
        settings_layout.addWidget(QLabel("时长设置", objectName="cardTitle"))
        row = QHBoxLayout()
        row.addWidget(QLabel("专注分钟"))
        self.work_spin = QSpinBox()
        self.work_spin.setRange(1, 120)
        self.work_spin.setValue(25)
        row.addWidget(self.work_spin)
        row.addSpacing(22)
        row.addWidget(QLabel("休息分钟"))
        self.break_spin = QSpinBox()
        self.break_spin.setRange(1, 60)
        self.break_spin.setValue(5)
        row.addWidget(self.break_spin)
        row.addStretch()
        save = QPushButton("应用设置")
        save.setObjectName("secondaryButton")
        save.clicked.connect(self.apply_focus_settings)
        row.addWidget(save)
        settings_layout.addLayout(row)
        layout.addWidget(settings_card)
        layout.addStretch()
        return page

    def _page_header(self, layout, title, subtitle):
        layout.addWidget(QLabel(title, objectName="pageTitle"))
        label = QLabel(subtitle, objectName="pageSubtitle")
        label.setWordWrap(True)
        layout.addWidget(label)

    def save_date_format(self):
        if not hasattr(self, "date_format_combo"):
            return
        self.date_format = self.date_format_combo.currentData() or "full_cn"
        self.store.set("date_format", self.date_format)
        if hasattr(self, "day_label"):
            self.day_label.setText(format_dashboard_date(datetime.now(), self.date_format))

    def export_data(self):
        if not self.save_memo():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 TimeTip 数据", "TimeTip-backup.zip", "TimeTip 数据包 (*.zip);;JSON 文件 (*.json)")
        if not path: return
        try:
            self.store.export_data(path); self.data_transfer_feedback.setText("数据已导出：" + path)
        except (OSError, ValueError) as error: self.data_transfer_feedback.setText("导出失败：" + str(error))

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 TimeTip 数据", "", "TimeTip 数据包 (*.zip *.json);;所有文件 (*.*)")
        if not path: return
        if not self.save_memo():
            return
        try:
            self.store.import_data(path)
            self.countdowns = self.store.load_collection("countdowns"); self.memos = self.store.load_collection("memos"); self.anime = self.store.anime()
            saved_salary = self.store.read_json("salary", {}); self.salary_config = {**DEFAULT_SALARY, **saved_salary} if isinstance(saved_salary, dict) else DEFAULT_SALARY.copy()
            self._load_settings(); self.data_transfer_feedback.setText("数据已导入，界面已刷新。")
        except (OSError, ValueError, TypeError) as error: self.data_transfer_feedback.setText("导入失败：" + str(error))

    def check_for_updates(self) -> None:
        if not hasattr(self, "update_feedback"):
            return
        self.update_feedback.setText("正在检查更新…")
        set_feedback_state(self.update_feedback, "info")
        self.updater.check()

    def _on_update_available(self, metadata: dict) -> None:
        version = str(metadata.get("version", "")).lstrip("vV").strip()
        notes = str(metadata.get("release_notes", "暂无更新说明。")).strip() or "暂无更新说明。"
        source = str(metadata.get("source_label", metadata.get("source", "未知来源")))
        source_ip = str(metadata.get("source_ip", self.updater.metadata_url.split("/")[2] if "/" in self.updater.metadata_url else "未知"))
        client_ip = str(metadata.get("client_ip", "未知"))
        self.update_source.setText(f"更新源 IP：{source_ip} · 客户端 IP：{client_ip} · 安装包来源：{source}")
        self.update_feedback.setText(f"发现新版本 V{version}，已确认更新源可用。")
        set_feedback_state(self.update_feedback, "success")
        answer = QMessageBox.question(
            self,
            "TimeTip 更新",
            f"发现新版本 V{version}。\n\n{notes}\n\n现在下载并安装吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.update_progress.setVisible(True)
            self.update_progress.setValue(0)
            self.update_download_button.setEnabled(False)
            self.updater.download()

    def _on_no_update(self, metadata: dict) -> None:
        source = str(metadata.get("source_label", metadata.get("source", "未知来源")))
        source_ip = str(metadata.get("source_ip", "未知"))
        client_ip = str(metadata.get("client_ip", "未知"))
        self.update_source.setText(f"更新源 IP：{source_ip} · 客户端 IP：{client_ip} · 安装包来源：{source}")
        self.update_feedback.setText(f"当前已是最新版本 {DISPLAY_VERSION}。")
        set_feedback_state(self.update_feedback, "success")

    def _on_update_progress(self, received: int, total: int) -> None:
        self.update_progress.setVisible(True)
        if total > 0:
            self.update_progress.setRange(0, 100)
            self.update_progress.setValue(min(100, int(received * 100 / total)))
            self.update_feedback.setText(f"正在下载更新… {received / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB")
        else:
            self.update_progress.setRange(0, 0)
            self.update_feedback.setText(f"正在下载更新… {received / 1024 / 1024:.1f} MB")

    def _on_update_downloaded(self, path: str) -> None:
        try:
            Updater.launch_installer(path)
            self.update_progress.setVisible(False)
            self.update_download_button.setEnabled(True)
            self.update_feedback.setText("安装器已启动，下载成功，TimeTip 将退出并完成更新。")
            QTimer.singleShot(300, self.quit_app)
        except OSError as error:
            self._on_update_failed(str(error))

    def _on_update_failed(self, message: str) -> None:
        if hasattr(self, "update_progress"):
            self.update_progress.setVisible(False)
        if hasattr(self, "update_download_button"):
            self.update_download_button.setEnabled(True)
        if hasattr(self, "update_feedback"):
            set_feedback_state(self.update_feedback, "error")
            self.update_feedback.setText("更新失败：" + message)

    def _save_update_auto_check(self, enabled: bool) -> None:
        self.store.set("update_auto_check", "1" if enabled else "0")

    def _anime_page(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(8, 14, 8, 8); layout.setSpacing(14)
        self._page_header(layout, "看番提醒", "按开始日期、每周更新日和集数自动计算每一话日期；只在日历显示。")

        toolbar = QHBoxLayout(); toolbar.setSpacing(8)
        self.anime_search = QLineEdit(); self.anime_search.setPlaceholderText("搜索番剧名称或文件夹…"); self.anime_search.setClearButtonEnabled(True); self.anime_search.setMinimumWidth(220); self.anime_search.setAccessibleName("搜索番剧")
        self.anime_search.textChanged.connect(lambda: self._refresh_anime_list()); toolbar.addWidget(self.anime_search, 1)
        add = QPushButton("＋ 添加番剧", objectName="primaryButton"); add.clicked.connect(lambda: self.edit_anime(None)); toolbar.addWidget(add)
        layout.addLayout(toolbar)
        toolbar = QHBoxLayout(); toolbar.setSpacing(8)
        self.anime_category_filter = QComboBox(); self.anime_category_filter.setAccessibleName("番剧分类筛选"); self.anime_category_filter.addItem("全部分类", "all")
        for key, label in (("backlog", "补番"), ("watching", "追番"), ("completed", "已看完")): self.anime_category_filter.addItem(label, key)
        self.anime_category_filter.currentIndexChanged.connect(lambda: self._refresh_anime_list()); toolbar.addWidget(self.anime_category_filter)
        self.anime_group_filter = QComboBox(); self.anime_group_filter.setAccessibleName("番剧分组筛选")
        self.anime_group_filter.setMaximumWidth(180)
        self.anime_group_filter.currentIndexChanged.connect(lambda: self._refresh_anime_list()); toolbar.addWidget(self.anime_group_filter)
        self.anime_sort = QComboBox(); self.anime_sort.setAccessibleName("番剧排序"); self.anime_sort.addItem("手动排序", "default"); self.anime_sort.addItem("名称 A–Z", "title"); self.anime_sort.addItem("更新日期", "date"); self.anime_sort.currentIndexChanged.connect(lambda: self._refresh_anime_list()); toolbar.addWidget(self.anime_sort)
        toolbar.addStretch()
        manage = QPushButton("管理分组", objectName="secondaryButton"); manage.clicked.connect(self.manage_anime_groups); toolbar.addWidget(manage)
        layout.addLayout(toolbar)

        self.anime_list = AnimeListWidget()
        self.anime_list.setMinimumHeight(250)
        self.anime_list.setSpacing(10)
        self.anime_list.setUniformItemSizes(True)
        self.anime_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.anime_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.anime_list.setDragEnabled(True)
        self.anime_list.setAcceptDrops(True)
        self.anime_list.setDropIndicatorShown(True)
        self.anime_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.anime_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.anime_list.model().rowsMoved.connect(self._anime_rows_moved)
        # Rebuild after QDrag.exec returns, when the source card is no longer in use.
        self.anime_list.orderRequested.connect(self._save_anime_order, Qt.ConnectionType.QueuedConnection)
        layout.addWidget(self.anime_list, 1)
        self.anime_empty = QLabel("", objectName="cardHint"); self.anime_empty.setWordWrap(True); layout.addWidget(self.anime_empty)
        order_actions = QHBoxLayout()
        self.anime_order_hint = QLabel("", objectName="cardHint"); self.anime_order_hint.setWordWrap(True); order_actions.addWidget(self.anime_order_hint, 1)
        self.anime_move_up = QPushButton("上移", objectName="secondaryButton"); self.anime_move_up.setToolTip("Alt + ↑"); self.anime_move_up.clicked.connect(lambda: self.anime_list.move_current(-1)); order_actions.addWidget(self.anime_move_up)
        self.anime_move_down = QPushButton("下移", objectName="secondaryButton"); self.anime_move_down.setToolTip("Alt + ↓"); self.anime_move_down.clicked.connect(lambda: self.anime_list.move_current(1)); order_actions.addWidget(self.anime_move_down)
        self.anime_list.currentRowChanged.connect(self._update_anime_move_buttons)
        layout.addLayout(order_actions)
        self.anime_feedback = QLabel("添加后会自动在对应日期的日历上显示。", objectName="cardHint"); layout.addWidget(self.anime_feedback)
        # Compatibility fields remain hidden for older integrations; all visible editing uses AnimeDialog.
        self.anime_name = QLineEdit(self); self.anime_update = QTimeEdit(self); self.anime_folder = QLineEdit(self); self.anime_progress = QLineEdit(self); self.anime_day_checks = [QCheckBox(self) for _ in range(7)]
        for widget in [self.anime_name, self.anime_update, self.anime_folder, self.anime_progress, *self.anime_day_checks]: widget.hide()
        layout.addStretch(); return self._scroll_page(page)

    def _refresh_anime_list(self, selected_id=None):
        if not hasattr(self, "anime_list"): return
        current = self.anime_list.currentItem()
        if selected_id is None and current is not None: selected_id = current.data(Qt.ItemDataRole.UserRole)
        self._refreshing_anime = True
        self.anime_list.blockSignals(True); self.anime_list.clear()
        query = self.anime_search.text().strip().casefold() if hasattr(self, "anime_search") else ""
        category = self.anime_category_filter.currentData() if hasattr(self, "anime_category_filter") else "all"
        group = self.anime_group_filter.currentData() if hasattr(self, "anime_group_filter") else "all"
        if hasattr(self, "anime_group_filter"):
            current_group = self.anime_group_filter.currentData()
            groups = self._anime_group_names()
            self.anime_group_filter.blockSignals(True)
            self.anime_group_filter.clear(); self.anime_group_filter.addItem("全部分组", None)
            for name in groups: self.anime_group_filter.addItem(name, name)
            self.anime_group_filter.setCurrentIndex(max(0, self.anime_group_filter.findData(current_group)))
            self.anime_group_filter.blockSignals(False)
            group = self.anime_group_filter.currentData()
        items = [item for item in self.anime if (not query or query in str(item.get("title", "")).casefold() or query in str(item.get("folder", "")).casefold() or any(query in tag.casefold() for tag in normalize_tags(item.get("tags", [])))) and (category in (None, "all") or item.get("category", "watching") == category) and (group is None or group_name(item.get("group")) == group)]
        sort_mode = self.anime_sort.currentData() if hasattr(self, "anime_sort") else "default"
        if sort_mode == "title": items.sort(key=lambda item: str(item.get("title", "")).casefold())
        elif sort_mode == "date": items.sort(key=lambda item: str(item.get("start_date", "")), reverse=True)
        manual = sort_mode == "default"
        self.anime_list.setDragEnabled(manual)
        self.anime_list.setAcceptDrops(manual)
        self.anime_order_hint.setText("拖动卡片调整顺序 · 双击查看详情 · Alt + ↑ / ↓ 上下移动" if manual else "当前按名称或日期排序；切换“手动排序”后可拖动卡片。")
        self.anime_empty.setText("暂无番剧，点击“添加番剧”开始整理。" if not self.anime else "没有符合筛选条件的番剧，可切换分类、分组或清空搜索。")
        self.anime_empty.setVisible(not items)
        for item in items:
            card = AnimeCard(item)
            card.drag_handle.setVisible(manual)
            card.setToolTip("拖动调整顺序；双击查看详情" if manual else "双击查看详情；切换手动排序后可拖动")
            card.edit_button.clicked.connect(lambda _checked=False, anime_id=item["id"]: self.edit_anime(anime_id))
            card.delete_button.clicked.connect(lambda _checked=False, anime_id=item["id"]: self.delete_anime_id(anime_id))
            card.opened.connect(lambda anime_id=item["id"]: self.open_anime_details(anime_id))
            row = QListWidgetItem(); row.setData(Qt.ItemDataRole.UserRole, item["id"]); row.setToolTip(item.get("folder", "")); row.setSizeHint(card.sizeHint()); self.anime_list.addItem(row); self.anime_list.setItemWidget(row, card)
        self._select_list_id(self.anime_list, selected_id); self.anime_list.blockSignals(False); self._refreshing_anime = False
        self._update_anime_move_buttons()

    def _update_anime_move_buttons(self, *_):
        row = self.anime_list.currentRow()
        manual = self.anime_list.dragEnabled()
        self.anime_move_up.setEnabled(manual and row > 0)
        self.anime_move_down.setEnabled(manual and 0 <= row < self.anime_list.count() - 1)

    def _anime_group_names(self):
        saved = self.store.read_json("anime_groups", [])
        return anime_groups(self.anime, saved if isinstance(saved, list) else [])

    def manage_anime_groups(self):
        dialog = AnimeGroupsDialog(self.anime, self._anime_group_names(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.anime = dialog.items
            self.store.save_anime(self.anime)
            self.store.write_json("anime_groups", dialog.groups)
            self._refresh_anime_list()
            self.anime_feedback.setText("分组已保存，番剧的分组归属已同步更新。")

    def _save_anime_order(self, visible_ids):
        if self.anime_sort.currentData() != "default":
            return
        current_ids = self.anime_list.ids()
        if set(visible_ids) != set(current_ids):
            return
        try:
            reordered = reorder_anime(self.anime, visible_ids)
        except ValueError as error:
            self.anime_feedback.setText(str(error))
            return
        self.store.save_anime(reordered)
        self.anime = reordered
        scroll = self.anime_list.verticalScrollBar().value()
        self._refresh_anime_list()
        self.anime_list.verticalScrollBar().setValue(scroll)
        self.anime_feedback.setText("顺序已保存，筛选外的番剧位置保持不变。")

    def _anime_rows_moved(self, parent, start, end, destination, row):
        """Persist the new manual card order after an internal drag."""
        if getattr(self, "_refreshing_anime", False):
            return
        visible_ids = [self.anime_list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.anime_list.count())]
        QTimer.singleShot(0, lambda: self._save_anime_order(visible_ids))

    def edit_anime(self, anime_id=None):
        item = next((a for a in self.anime if a["id"] == anime_id), None)
        dialog = AnimeDialog(item, self, groups=self._anime_group_names())
        if item is None and self.anime_group_filter.currentData() is not None:
            dialog.group.setCurrentText(self.anime_group_filter.currentData())
        self._anime_dialog = dialog
        dialog.submitted.connect(lambda values: self._commit_anime_dialog(dialog, item, values))
        result = dialog.exec()
        self._clear_anime_dialog(dialog)
        return result == QDialog.DialogCode.Accepted

    def _commit_anime_dialog(self, dialog, item, values):
        values["id"] = item["id"] if item else uuid.uuid4().hex
        known_groups = self._anime_group_names()
        requested_group = group_name(values.get("group"))
        values["group"] = next((name for name in known_groups if name.casefold() == requested_group.casefold()), requested_group)
        known_groups = anime_groups([values], known_groups)
        try: validate_anime(values)
        except ValueError as error: self.anime_feedback.setText(str(error)); return False
        if values.get("cover"): values["cover"] = self.store.save_cover(values["cover"], values["id"])
        existing = next((a for a in self.anime if a["id"] == values["id"]), None)
        if existing: existing.clear(); existing.update(values)
        else: self.anime.append(values)
        self.store.save_anime(self.anime)
        self.store.write_json("anime_groups", known_groups)
        self._refresh_anime_list(values["id"]); self._rebuild_dashboard(); self._update_summary(); self.anime_feedback.setText("已保存，放送日期会自动标记到日历。")

    def _clear_anime_dialog(self, dialog):
        if getattr(self, "_anime_dialog", None) is dialog:
            self._anime_dialog = None

    def new_anime(self): return self.edit_anime(None)
    def save_anime(self):
        # Backward-compatible programmatic save path for older preview integrations.
        item = {"id": getattr(self, "active_anime_id", None) or uuid.uuid4().hex, "title": self.anime_name.text().strip(), "category": "watching", "group": "未分组", "start_date": "2026-01-01", "end_date": "2027-12-31", "air_days": [i for i, c in enumerate(self.anime_day_checks) if c.isChecked()] or [0], "episode_count": 12, "progress": self.anime_progress.text().strip() or "第 0 话", "folder": self.anime_folder.text().strip(), "cover": "", "legacy_compat": True}
        try: validate_anime(item)
        except ValueError as error: self.anime_feedback.setText(str(error)); return False
        self.anime.append(item); self.store.save_anime(self.anime); self.active_anime_id = item["id"]; self._refresh_anime_list(item["id"]); self._rebuild_dashboard(); self._update_summary(); return True
    def browse_anime_folder(self): return None
    def _anime_selected(self, current, previous=None): return None
    def open_anime_details(self, anime_id):
        item = next((a for a in self.anime if a["id"] == anime_id), None)
        if not item: return
        dialog = AnimeFolderDialog(item, self)
        dialog.progressSaved.connect(lambda value, anime_id=anime_id: self._save_anime_progress(anime_id, value))
        dialog.exec()

    def _save_anime_progress(self, anime_id, progress):
        item = next((a for a in self.anime if a["id"] == anime_id), None)
        if not item: return
        item["progress"] = progress
        self.store.save_anime(self.anime)
        self._refresh_anime_list(anime_id); self._rebuild_dashboard(); self._update_summary()

    def delete_anime_id(self, anime_id):
        self.anime = [a for a in self.anime if a["id"] != anime_id]
        self.store.save_anime(self.anime); self._refresh_anime_list(); self._rebuild_dashboard(); self._update_summary()

    def delete_anime(self):
        item = self.anime_list.currentItem()
        if not item: return
        self.delete_anime_id(item.data(Qt.ItemDataRole.UserRole))

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(16)
        self._page_header(layout, "设置", "管理你的时间、工资计算方式与概览布局。所有设置仅保存在本机。")
        date_card = Card()
        date_row = QHBoxLayout(date_card)
        date_row.setContentsMargins(20, 14, 20, 14)
        date_row.addWidget(QLabel("概览日期格式", objectName="cardTitle"))
        self.date_format_combo = QComboBox()
        for key, example in DATE_FORMATS:
            self.date_format_combo.addItem(example, key)
        self.date_format_combo.currentIndexChanged.connect(self.save_date_format)
        date_row.addWidget(self.date_format_combo, 1)
        layout.addWidget(date_card)
        theme_card = Card()
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(20, 14, 20, 14)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("界面主题", objectName="cardTitle"))
        self.theme_combo = QComboBox()
        self.theme_combo.setAccessibleName("界面主题")
        self.theme_combo.currentIndexChanged.connect(self.save_theme)
        theme_row.addWidget(self.theme_combo, 1)
        theme_layout.addLayout(theme_row)
        self.theme_description = QLabel("", objectName="cardHint")
        self.theme_description.setWordWrap(True)
        theme_layout.addWidget(self.theme_description)
        layout.addWidget(theme_card)
        self.refresh_theme_options()
        jm_card = Card()
        jm_layout = QVBoxLayout(jm_card)
        jm_layout.setContentsMargins(20, 14, 20, 14)
        jm_row = QHBoxLayout()
        jm_row.addWidget(QLabel("里模式", objectName="cardTitle"))
        self.jm_unlock_button = QPushButton("里模式", objectName="primaryButton")
        self.jm_unlock_button.setToolTip("连续点击五次显示 JM漫画下载模块")
        self.jm_unlock_button.clicked.connect(self._unlock_jm_mode)
        jm_row.addWidget(self.jm_unlock_button)
        jm_row.addStretch()
        jm_layout.addLayout(jm_row)
        self.jm_unlock_feedback = QLabel("连续点击五次后显示 JM漫画下载模块。", objectName="cardHint")
        self.jm_unlock_feedback.setWordWrap(True)
        jm_layout.addWidget(self.jm_unlock_feedback)
        layout.addWidget(jm_card)
        startup_card = Card()
        startup_layout = QVBoxLayout(startup_card)
        startup_layout.setContentsMargins(20, 14, 20, 14)
        startup_row = QHBoxLayout()
        self.startup_check = QCheckBox("开机自动启动 TimeTip")
        self.startup_check.setAccessibleName("开机自启")
        self.startup_check.toggled.connect(self._toggle_startup)
        startup_row.addWidget(self.startup_check)
        startup_row.addStretch()
        startup_layout.addLayout(startup_row)
        self.startup_feedback = QLabel("登录 Windows 后自动打开 TimeTip。", objectName="cardHint")
        self.startup_feedback.setWordWrap(True)
        startup_layout.addWidget(self.startup_feedback)
        layout.addWidget(startup_card)
        update_card = Card()
        update_layout = QVBoxLayout(update_card)
        update_layout.setContentsMargins(20, 14, 20, 14)
        update_row = QHBoxLayout()
        update_row.addWidget(QLabel("软件更新", objectName="cardTitle"))
        self.update_download_button = QPushButton("检查更新", objectName="secondaryButton")
        self.update_download_button.clicked.connect(self.check_for_updates)
        update_row.addWidget(self.update_download_button)
        self.update_auto_check = QCheckBox("启动时自动检查更新")
        self.update_auto_check.setAccessibleName("自动检查更新")
        self.update_auto_check.toggled.connect(self._save_update_auto_check)
        update_row.addWidget(self.update_auto_check)
        update_layout.addLayout(update_row)
        self.update_feedback = QLabel("点击“检查更新”获取最新版本信息。", objectName="cardHint")
        self.update_feedback.setWordWrap(True)
        update_layout.addWidget(self.update_feedback)
        self.update_source = QLabel("更新源 IP：尚未检查 · 安装包来源：尚未确认", objectName="cardHint")
        self.update_source.setWordWrap(True)
        update_layout.addWidget(self.update_source)
        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setVisible(False)
        update_layout.addWidget(self.update_progress)
        layout.addWidget(update_card)
        transfer_card = Card()
        transfer_row = QHBoxLayout(transfer_card); transfer_row.setContentsMargins(20, 14, 20, 14)
        transfer_row.addWidget(QLabel("数据备份", objectName="cardTitle"))
        export_button = QPushButton("导出数据", objectName="secondaryButton"); export_button.clicked.connect(self.export_data); transfer_row.addWidget(export_button)
        import_button = QPushButton("导入数据", objectName="secondaryButton"); import_button.clicked.connect(self.import_data); transfer_row.addWidget(import_button)
        self.data_transfer_feedback = QLabel("SQLite 数据库位于安装目录的 data 文件夹。", objectName="cardHint"); transfer_row.addWidget(self.data_transfer_feedback, 1)
        layout.addWidget(transfer_card)
        summary = Card()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(20, 18, 20, 18)
        row = QHBoxLayout()
        row.addWidget(QLabel("倒计时总览", objectName="cardTitle"), 1)
        manage = QPushButton("管理倒计时  →", objectName="secondaryButton")
        manage.clicked.connect(lambda: self._switch_page(4))
        row.addWidget(manage)
        summary_layout.addLayout(row)
        self.settings_summary = QLabel("", objectName="cardHint")
        summary_layout.addWidget(self.settings_summary)
        self.settings_countdown_list = QListWidget(objectName="cleanList")
        self.settings_countdown_list.setMinimumHeight(100)
        self.settings_countdown_list.setMaximumHeight(200)
        self.settings_countdown_list.itemDoubleClicked.connect(lambda item: self._open_widget("countdown:" + item.data(Qt.ItemDataRole.UserRole)))
        summary_layout.addWidget(self.settings_countdown_list)
        layout.addWidget(summary)
        salary = Card()
        form = QVBoxLayout(salary)
        form.setContentsMargins(20, 18, 20, 18)
        form.setSpacing(12)
        form.addWidget(QLabel("每日工资", objectName="cardTitle"))
        note = QLabel("月薪 ÷ 当月所选工作日数 = 每日工资；按有效工作秒数累计。午休、下班和休息日不增长。", objectName="cardHint")
        note.setWordWrap(True)
        form.addWidget(note)
        fields = QGridLayout()
        fields.setHorizontalSpacing(16)
        fields.setVerticalSpacing(8)
        self.monthly_salary = QDoubleSpinBox()
        self.monthly_salary.setRange(0, 100000000)
        self.monthly_salary.setDecimals(2)
        self.monthly_salary.setGroupSeparatorShown(True)
        self.monthly_salary.setPrefix("¥ ")
        self.monthly_salary.setSingleStep(1000)
        self.shift_start = QTimeEdit(QTime(9, 0))
        self.shift_end = QTimeEdit(QTime(18, 0))
        for edit in (self.shift_start, self.shift_end):
            edit.setDisplayFormat("HH:mm")
        for col, (title, widget) in enumerate([("月薪（元）", self.monthly_salary), ("上班时间", self.shift_start), ("下班时间", self.shift_end)]):
            label = QLabel(title, objectName="fieldLabel")
            label.setBuddy(widget)
            fields.addWidget(label, 0, col)
            fields.addWidget(widget, 1, col)
            fields.setColumnStretch(col, 1)
        form.addLayout(fields)
        form.addWidget(QLabel("每周工作日", objectName="fieldLabel"))
        weekdays = QHBoxLayout()
        self.weekday_checks = []
        for index, title in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"]):
            check = QCheckBox(title)
            check.setChecked(index < 5)
            weekdays.addWidget(check)
            self.weekday_checks.append(check)
        weekdays.addStretch()
        form.addLayout(weekdays)
        pause_row = QHBoxLayout()
        self.salary_break_check = QCheckBox("扣除午休 / 休息时间")
        self.salary_break_check.setChecked(True)
        pause_row.addWidget(self.salary_break_check)
        self.salary_break_start = QTimeEdit(QTime(12, 0))
        self.salary_break_end = QTimeEdit(QTime(13, 0))
        for edit in (self.salary_break_start, self.salary_break_end):
            edit.setDisplayFormat("HH:mm")
            self.salary_break_check.toggled.connect(edit.setEnabled)
        pause_row.addWidget(self.salary_break_start)
        pause_row.addWidget(QLabel("至"))
        pause_row.addWidget(self.salary_break_end)
        pause_row.addStretch()
        form.addLayout(pause_row)
        hint = QLabel("支持跨午夜班次，工资归属上班日期。工作日按星期计算，法定节假日及调休暂不自动识别。", objectName="cardHint")
        hint.setWordWrap(True)
        form.addWidget(hint)
        self.salary_feedback = QLabel("填写后保存，即可在概览查看实时工资。", objectName="cardHint")
        self.salary_feedback.setWordWrap(True)
        form.addWidget(self.salary_feedback)
        save = QPushButton("保存工资设置", objectName="primaryButton")
        save.clicked.connect(self.save_salary_settings)
        form.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(salary)
        widget_card = Card()
        widget_layout = QVBoxLayout(widget_card)
        widget_layout.setContentsMargins(20, 18, 20, 18)
        widget_layout.setSpacing(12)
        widget_layout.addWidget(QLabel("概览组件", objectName="cardTitle"))
        hint = QLabel("勾选要显示的组件，并选择宽 × 高。宽窗口使用 4 列，窄窗口自动收为 2 列；布局自动保存。", objectName="cardHint")
        hint.setWordWrap(True)
        widget_layout.addWidget(hint)
        self.widget_settings_container = QWidget()
        self.widget_settings_layout = QVBoxLayout(self.widget_settings_container)
        self.widget_settings_layout.setContentsMargins(0, 0, 0, 0)
        widget_layout.addWidget(self.widget_settings_container)
        layout.addWidget(widget_card)
        layout.addStretch()
        return self._scroll_page(page)

    def _toggle_startup(self, enabled: bool) -> bool:
        try:
            startup.set_startup_enabled(enabled)
        except startup.StartupError as error:
            self.startup_check.blockSignals(True)
            self.startup_check.setChecked(not enabled)
            self.startup_check.blockSignals(False)
            set_feedback_state(self.startup_feedback, "error")
            self.startup_feedback.setText(str(error))
            return False
        set_feedback_state(self.startup_feedback, "success")
        self.startup_feedback.setText("已开启：登录 Windows 后自动启动。" if enabled else "已关闭开机自启。")
        return True

    def _refresh_widget_settings(self):
        while self.widget_settings_layout.count():
            child = self.widget_settings_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for key, title, size, tone in self._ordered_specs():
            state = self._widget_state(key, size)
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(title[:35] + ("…" if len(title) > 35 else ""))
            check.setToolTip(title)
            check.setChecked(bool(state["visible"]))
            check.toggled.connect(lambda value, k=key: self._change_widget(k, "visible", value))
            line.addWidget(check, 1)
            combo = QComboBox()
            combo.setAccessibleName(title + "组件大小")
            for size in WIDGET_SIZES:
                combo.addItem(f"{size[0]} × {size[1]}", size)
            combo.setCurrentIndex(WIDGET_SIZES.index(tuple(state["size"])))
            combo.currentIndexChanged.connect(lambda index, k=key: self._change_widget(k, "size", WIDGET_SIZES[index]))
            line.addWidget(combo)
            self.widget_settings_layout.addWidget(row)

    def save_salary_settings(self):
        config = {"monthly": self.monthly_salary.value(), "start": self.shift_start.time().toString("HH:mm"),
                  "end": self.shift_end.time().toString("HH:mm"), "weekdays": [i for i, c in enumerate(self.weekday_checks) if c.isChecked()],
                  "break_enabled": self.salary_break_check.isChecked(), "break_start": self.salary_break_start.time().toString("HH:mm"),
                  "break_end": self.salary_break_end.time().toString("HH:mm")}
        try:
            validate_salary(config)
        except ValueError as error:
            set_feedback_state(self.salary_feedback, "error")
            self.salary_feedback.setText(str(error))
            return False
        self.salary_config = config
        self.store.write_json("salary", config)
        result = salary_snapshot(config, datetime.now())
        set_feedback_state(self.salary_feedback, "success")
        self.salary_feedback.setText(f"已保存 · 本月 {result['workdays']} 个工作日 · 每日 ¥ {result['daily']:,.2f} · 每秒 ¥ {result['per_second']:.4f}")
        self._render_dashboard(datetime.now())
        return True

    def _load_settings(self) -> None:
        self.set_theme(self.store.get("theme", self.theme.id))
        for key, spin, default in [("work", self.work_spin, 25), ("break", self.break_spin, 5)]:
            try:
                spin.setValue(int(self.store.get(key, str(default))))
            except ValueError:
                spin.setValue(default)
        self.pomodoro_remaining = self.work_spin.value() * 60
        config = self.salary_config
        self.monthly_salary.setValue(float(config["monthly"]))
        self.shift_start.setTime(QTime.fromString(config["start"], "HH:mm"))
        self.shift_end.setTime(QTime.fromString(config["end"], "HH:mm"))
        self.salary_break_check.setChecked(config["break_enabled"])
        self.salary_break_start.setTime(QTime.fromString(config["break_start"], "HH:mm"))
        self.salary_break_end.setTime(QTime.fromString(config["break_end"], "HH:mm"))
        for index, check in enumerate(self.weekday_checks):
            check.setChecked(index in config["weekdays"])
        self.date_format = self.store.get("date_format", "full_cn")
        self.date_format_combo.setCurrentIndex(max(0, self.date_format_combo.findData(self.date_format)))
        self.startup_check.blockSignals(True)
        self.startup_check.setChecked(startup.is_startup_enabled())
        self.startup_check.blockSignals(False)
        auto_check = self.store.get("update_auto_check", "1") == "1"
        self.update_auto_check.blockSignals(True)
        self.update_auto_check.setChecked(auto_check)
        self.update_auto_check.blockSignals(False)
        if auto_check and getattr(sys, "frozen", False):
            QTimer.singleShot(1200, self.check_for_updates)
        self._refresh_countdown_lists()
        self._refresh_anime_list()
        self._refresh_memo_list(self.memos[0]["id"] if self.memos else None)
        self._calendar_selected(self.calendar.selectedDate())
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self._update_summary()
        self._render_focus_time()

    def _start_timers(self) -> None:
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self.timer = timer

    def _tick(self) -> None:
        now = datetime.now()
        self.day_label.setText(format_dashboard_date(now, self.date_format))
        self._update_countdown(now)
        if self.pomodoro_running:
            self.pomodoro_remaining = max(0, int((self.pomodoro_deadline - now).total_seconds() + 0.999))
            if self.pomodoro_remaining <= 0:
                self.pomodoro_mode = "break" if self.pomodoro_mode == "work" else "work"
                self.pomodoro_remaining = (self.break_spin.value() if self.pomodoro_mode == "break" else self.work_spin.value()) * 60
                self.pomodoro_deadline = now + timedelta(seconds=self.pomodoro_remaining)
                self.notify("专注时段结束，休息一下吧。" if self.pomodoro_mode == "break" else "休息结束，开始新的专注。")
            self._render_focus_time()
        self._check_reminders(now)
        self._render_dashboard(now)

    @staticmethod
    def _select_list_id(widget, item_id):
        for row in range(widget.count()):
            if widget.item(row).data(Qt.ItemDataRole.UserRole) == item_id:
                widget.setCurrentRow(row)
                return

    def _switch_page(self, index: int) -> None:
        current = self.pages.currentIndex()
        if index == current:
            return
        direction = 1 if index > current else -1
        self.pages.setCurrentIndex(index)
        page = self.pages.currentWidget()
        if page is not None:
            if hasattr(self, "_page_animation"):
                self._page_animation.stop()
            page.raise_()
            page.move(self.pages.width() * direction, 0)
            animation = QPropertyAnimation(page, b"pos", self)
            animation.setDuration(240)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(page.pos())
            animation.setEndValue(QPoint(0, 0))
            self._page_animation = animation
            animation.start()
        for i, button in enumerate(getattr(self, "_all_nav_buttons", self.nav_buttons)):
            button.setChecked(i == index)
        if index == 1:
            self._calendar_selected(self.calendar.selectedDate())

    def _calendar_selected(self, date: QDate) -> None:
        self.selected_date_label.setText(date.toString("yyyy年MM月dd日"))
        self.reminder_list.clear()
        key = date.toString("yyyy-MM-dd")
        for anime in anime_for_date(self.anime, date.toPyDate()):
            item = QListWidgetItem("番剧 · " + anime["title"] + "  ·  " + episode_label(anime))
            item.setToolTip((anime.get("folder") or "未关联本地文件夹") + "\n仅在日历显示，不会主动提醒")
            item.setData(Qt.ItemDataRole.UserRole, {"kind": "anime", "id": anime["id"]})
            self.reminder_list.addItem(item)
        for reminder in self.store.reminders():
            if reminder.get("date") == key:
                mode = reminder.get("mode", "notify")
                state = " · 已提醒" if reminder.get("notified") else ""
                label = "电脑提醒" if mode == "notify" else "仅日历"
                item = QListWidgetItem(reminder.get("time", "09:00") + "  " + reminder.get("text", "") +
                                       f" · {label}" + state)
                item.setData(Qt.ItemDataRole.UserRole, reminder)
                self.reminder_list.addItem(item)

    def add_reminder(self) -> None:
        text = self.reminder_input.text().strip()
        if not text:
            self.reminder_input.setFocus()
            return
        key = self.calendar.selectedDate().toString("yyyy-MM-dd")
        items = self.store.reminders()
        items.append({"id": uuid.uuid4().hex, "date": key, "time": self.reminder_time.time().toString("HH:mm"), "text": text, "mode": self.reminder_mode.currentData(), "notified": False})
        self.store.save_reminders(items)
        self.reminder_input.clear()
        self._calendar_selected(self.calendar.selectedDate())
        self._update_summary()

    def remove_reminder(self) -> None:
        current = self.reminder_list.currentItem()
        if not current:
            return
        target = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(target, dict) and target.get("kind") == "anime":
            return
        items = self.store.reminders()
        items.remove(target)
        self.store.save_reminders(items)
        self._calendar_selected(self.calendar.selectedDate())
        self._update_summary()

    def _check_reminders(self, now: datetime) -> None:
        items = self.store.reminders()
        due = []
        for reminder in items:
            try:
                scheduled = datetime.fromisoformat(reminder["date"] + "T" + reminder.get("time", "09:00"))
            except (ValueError, TypeError):
                continue
            if reminder.get("mode", "notify") != "notify":
                continue
            if scheduled <= now and not reminder.get("notified"):
                due.append(reminder["text"])
                reminder["notified"] = now.isoformat()
        if due:
            self.store.save_reminders(items)
            self.notify("日历提醒：" + "、".join(due))
            self._calendar_selected(self.calendar.selectedDate())

    def toggle_focus(self) -> None:
        if self.pomodoro_running:
            self.pomodoro_remaining = max(0, int((self.pomodoro_deadline - datetime.now()).total_seconds() + 0.999))
        else:
            self.pomodoro_deadline = datetime.now() + timedelta(seconds=self.pomodoro_remaining)
        self.pomodoro_running = not self.pomodoro_running
        self.work_spin.setEnabled(not self.pomodoro_running)
        self.break_spin.setEnabled(not self.pomodoro_running)
        self.focus_start.setText("暂停" if self.pomodoro_running else "继续专注")

    def reset_focus(self) -> None:
        self.pomodoro_running = False
        self.work_spin.setEnabled(True)
        self.break_spin.setEnabled(True)
        self.pomodoro_mode = "work"
        self.pomodoro_remaining = self.work_spin.value() * 60
        self.focus_start.setText("开始专注")
        self._render_focus_time()

    def apply_focus_settings(self) -> None:
        self.store.set("work", str(self.work_spin.value()))
        self.store.set("break", str(self.break_spin.value()))
        self.reset_focus()
        self._update_summary()

    def _render_focus_time(self) -> None:
        minutes, seconds = divmod(max(0, self.pomodoro_remaining), 60)
        self.focus_time_label.setText(f"{minutes:02d}:{seconds:02d}")
        self.focus_mode_label.setText("专注时段" if self.pomodoro_mode == "work" else "休息时段")

    def _update_summary(self) -> None:
        self._render_dashboard(datetime.now())
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        for reminder in self.store.reminders():
            date = QDate.fromString(reminder["date"], "yyyy-MM-dd")
            if date.isValid():
                style = QTextCharFormat()
                style.setForeground(QColor(self.theme.colors["primary"]))
                style.setFontWeight(QFont.Weight.Bold)
                style.setToolTip("有日历提醒")
                self.calendar.setDateTextFormat(date, style)
        for anime in self.anime:
            try:
                schedule = episode_dates(anime)
            except ValueError:
                schedule = []
            for day in schedule:
                qday = QDate(day.year, day.month, day.day)
                style = QTextCharFormat()
                style.setForeground(QColor(self.theme.colors["warning"]))
                style.setFontWeight(QFont.Weight.Bold)
                style.setToolTip("有番剧更新：" + anime["title"])
                self.calendar.setDateTextFormat(qday, style)
