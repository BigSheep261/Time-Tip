"""Shared application icon and frameless title-bar controls."""
from __future__ import annotations


from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout

from app.presentation.theme import APP_NAME, PRIMARY, get_theme


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


