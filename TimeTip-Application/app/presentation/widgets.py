from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.domain.layout import WIDGET_SIZES, pack_widgets


class ElidedLabel(QLabel):
    """Keep arbitrary user titles from imposing a minimum window width."""
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        lines = [self.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, max(0, self.width()))
                 for line in self.full_text.split("\n")]
        super().setText("\n".join(lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class DashboardTile(QFrame):
    changed = pyqtSignal(str, str, object)
    opened = pyqtSignal(str)

    def __init__(self, key, title, size=(2, 1), tone="plain", parent=None):
        super().__init__(parent)
        self.key = key
        self.span = size
        self._editing = False
        self._drag_start: QPoint | None = None
        self._dragging = False
        self.setObjectName("widgetCard")
        self.setProperty("tone", tone)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.title_label = ElidedLabel(title)
        self.title_label.setObjectName("widgetTitle")
        header.addWidget(self.title_label, 1)
        self.menu_button = QPushButton("···")
        self.menu_button.setObjectName("widgetMenu")
        self.menu_button.setFixedSize(30, 28)
        self.menu_button.setToolTip("调整组件大小、顺序或显示状态")
        self.menu_button.setAccessibleName(f"调整{title}组件")
        self.menu_button.clicked.connect(self.show_menu)
        header.addWidget(self.menu_button)
        layout.addLayout(header)
        layout.addStretch(1)
        self.value_label = ElidedLabel()
        self.value_label.setObjectName("widgetValue")
        layout.addWidget(self.value_label)
        self.hint_label = ElidedLabel()
        self.hint_label.setObjectName("widgetHint")
        layout.addWidget(self.hint_label)
        self.detail_label = QLabel()
        self.detail_label.setObjectName("widgetDetail")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setMinimumWidth(0)
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail_label)
        layout.addStretch(1)
        self.open_button = QPushButton("查看详情  →")
        self.open_button.setObjectName("widgetLink")
        self.open_button.clicked.connect(lambda: self.opened.emit(self.key))
        layout.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignLeft)
        for label in (self.title_label, self.value_label, self.hint_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._install_drag_filter(self)
        self.set_editing(False)

    def set_editing(self, editing):
        self._editing = bool(editing)
        self.menu_button.setVisible(editing)
        self.setCursor(Qt.CursorShape.OpenHandCursor if editing else Qt.CursorShape.ArrowCursor)

    def _install_drag_filter(self, widget):
        """Let a tile start dragging even when the press lands on its labels."""
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if not self._editing or watched is self.menu_button or watched is self.open_button:
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._dragging = False
            return False
        if event.type() == QEvent.Type.MouseMove and self._drag_start is not None:
            current = event.globalPosition().toPoint()
            if not self._dragging and (current - self._drag_start).manhattanLength() >= 6:
                self._dragging = True
                grid = self.parentWidget()
                if hasattr(grid, "begin_tile_drag"):
                    grid.begin_tile_drag(self, self._drag_start)
            if self._dragging:
                grid = self.parentWidget()
                if hasattr(grid, "drag_tile"):
                    grid.drag_tile(self, current)
                return True
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            self._drag_start = None
            self._dragging = False
            if was_dragging:
                grid = self.parentWidget()
                if hasattr(grid, "end_tile_drag"):
                    grid.end_tile_drag(self, event.globalPosition().toPoint())
                return True
        return super().eventFilter(watched, event)

    def update_spec(self, title, size, tone):
        self.span = tuple(size)
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
        self.title_label.setText(title)

    def show_menu(self):
        menu = QMenu(self)
        menu.addSection("组件大小 · 宽 × 高")
        for size in WIDGET_SIZES:
            action = menu.addAction(f"{size[0]} × {size[1]}")
            action.setCheckable(True)
            action.setChecked(self.span == size)
            action.triggered.connect(lambda checked=False, s=size: self.changed.emit(self.key, "size", s))
        menu.addSeparator()
        menu.addAction("向前移动", lambda: self.changed.emit(self.key, "move", -1))
        menu.addAction("向后移动", lambda: self.changed.emit(self.key, "move", 1))
        menu.addAction("从概览隐藏", lambda: self.changed.emit(self.key, "visible", False))
        menu.exec(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 260
        self.value_label.setStyleSheet(f"font-size: {20 if compact else (36 if self.height() > 240 else 28)}px; font-weight: 700;")
        self.detail_label.setVisible(self.height() > 240)
        # Two lines preserve the full countdown in a 1 × 1 tile.
        value = self.value_label.full_text
        if self.key.startswith("countdown:") and "天 " in value:
            self.value_label.setText(value.replace("天 ", "天\n") if compact else value)


class WidgetGrid(QWidget):
    tileMoved = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiles = []
        self.columns = 4
        self.editing = False
        self._drag_tile = None
        self._drag_origin = QPoint()
        self._animations = {}
        self._skip_animation = False
        self.setMinimumWidth(0)
        self.empty_label = QLabel("概览还没有组件\n前往「设置」勾选要显示的内容。", self)
        self.empty_label.setObjectName("cardHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_tiles(self, tiles):
        if not self.tiles:
            self._skip_animation = True
        next_tiles = set(tiles)
        for tile, animation in list(self._animations.items()):
            if tile not in next_tiles:
                animation.stop()
                animation.deleteLater()
                self._animations.pop(tile, None)
        self.tiles = tiles
        self.empty_label.setVisible(not tiles)
        for tile in tiles:
            tile.setParent(self)
            tile.show()
        self.reflow()

    def set_editing(self, editing):
        self.editing = bool(editing)

    def begin_tile_drag(self, tile, global_pos):
        if not self.editing or tile not in self.tiles:
            return
        self._drag_tile = tile
        self._drag_origin = global_pos - self.mapToGlobal(tile.pos())
        tile.raise_()
        tile.setCursor(Qt.CursorShape.ClosedHandCursor)

    def drag_tile(self, tile, global_pos):
        if tile is not self._drag_tile:
            return
        tile.move(self.mapFromGlobal(global_pos - self._drag_origin))

    def end_tile_drag(self, tile, global_pos):
        if tile is not self._drag_tile:
            return
        tile.setCursor(Qt.CursorShape.OpenHandCursor if self.editing else Qt.CursorShape.ArrowCursor)
        self._drag_tile = None
        target = len(self.tiles) - 1
        found_target = False
        center = global_pos - self.mapToGlobal(QPoint(0, 0))
        for index, other in enumerate(self.tiles):
            if other is tile:
                continue
            if center.y() < other.geometry().center().y() or (
                    abs(center.y() - other.geometry().center().y()) < other.height() / 2
                    and center.x() < other.geometry().center().x()):
                target = index
                found_target = True
                break
        source = self.tiles.index(tile)
        if found_target and target > source:
            target -= 1
        if target != source:
            self.tileMoved.emit(tile.key, target)
        else:
            self.reflow()

    def reflow(self):
        self.columns = 4 if self.width() >= 780 else 2
        gap, unit = 14, 184
        cell = (self.width() - gap * (self.columns - 1)) / self.columns
        placements = pack_widgets([tile.span for tile in self.tiles], self.columns)
        height = 0
        for tile, (row, col, width, rows) in zip(self.tiles, placements):
            x, y = round(col * (cell + gap)), row * (unit + gap)
            right = round((col + width) * (cell + gap) - gap)
            target = QRect(x, y, right - x, rows * unit + (rows - 1) * gap)
            height = max(height, y + target.height())
            if tile is self._drag_tile:
                continue
            animation = self._animations.pop(tile, None)
            if animation is not None:
                animation.stop()
            if self._skip_animation or tile.geometry() == target:
                tile.setGeometry(target)
                continue
            animation = QPropertyAnimation(tile, b"geometry", self)
            animation.setDuration(220)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(tile.geometry())
            animation.setEndValue(target)
            self._animations[tile] = animation
            animation.finished.connect(lambda t=tile: self._animations.pop(t, None))
            animation.start()
        self.setMinimumHeight(height)
        if not self.tiles:
            self.setMinimumHeight(160)
            self.empty_label.setGeometry(0, 0, self.width(), 160)
        self._skip_animation = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # A window resize can make the old geometry wider than the new viewport;
        # apply that layout immediately while keeping user initiated changes animated.
        self._skip_animation = True
        self.reflow()


class ResizeHandle(QWidget):
    """Native resize affordances on every edge of a frameless window."""
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)
        self.setToolTip("拖动调整窗口大小")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self.edges)
            event.accept()

class Card(QFrame):
    def __init__(self, object_name: str = "card", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

