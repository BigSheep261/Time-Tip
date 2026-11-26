"""Sticker categories with long-press sorting and animated rows."""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QSignalBlocker, Qt, QTimer, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QListWidget, QStyle, QStyleOptionViewItem


class EmojiCategoryList(QListWidget):
    reordered = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cleanList")
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setAccessibleDescription("按住分类 5 秒后可上下拖动排序")
        self._pressed = None
        self._dragging = False
        self._destination = -1
        self._pointer = None
        self._offsets = {}
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setTimerType(Qt.TimerType.PreciseTimer)
        self._hold.setInterval(5000)
        self._hold.timeout.connect(self._start_reordering)
        self._autoscroll = QTimer(self, interval=25)
        self._autoscroll.timeout.connect(self._scroll_for_drag)
        self.verticalScrollBar().valueChanged.connect(self._update_destination)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(145)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._animate_rows)
        self._animation_start = {}
        self._animation_end = {}

    def clear(self):
        self._cancel_reordering()
        super().clear()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._pointer = event.position().toPoint()
            self._pressed = self.itemAt(self._pointer)
            if self._pressed is not None:
                self._press_position = self._pointer
                self._grab_offset = self._pointer.y() - self.visualItemRect(self._pressed).top()
                self._hold.start()

    def mouseMoveEvent(self, event):
        self._pointer = event.position().toPoint()
        if self._dragging:
            if event.buttons() & Qt.MouseButton.LeftButton:
                if not self._autoscroll.isActive():
                    self._autoscroll.start()
                self._update_destination()
            else:
                self._cancel_reordering()
            event.accept()
            return
        if self._hold.isActive() and (
            (self._pointer - self._press_position).manhattanLength() >= QApplication.startDragDistance()
            or self.itemAt(self._pointer) is not self._pressed
        ):
            self._cancel_reordering()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        item = self._pressed
        if self._dragging:
            self._pointer = event.position().toPoint()
            self._update_destination()
        destination = self._destination
        self._cancel_reordering()
        super().mouseReleaseEvent(event)
        if item is None or destination < 0 or self.row(item) == destination:
            return
        scroll = self.verticalScrollBar().value()
        with QSignalBlocker(self):
            self.takeItem(self.row(item))
            self.insertItem(destination, item)
            self.setCurrentItem(item)
            self.doItemsLayout()
            self.verticalScrollBar().setValue(scroll)
        self.reordered.emit([self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count())])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._pressed is not None:
            self._cancel_reordering()
            event.accept()
            return
        super().keyPressEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.UngrabMouse, QEvent.Type.WindowDeactivate):
            self._cancel_reordering()
        return super().viewportEvent(event)

    def _start_reordering(self):
        if self.itemAt(self._pointer) is not self._pressed:
            self._cancel_reordering()
            return
        self._dragging = True
        self._destination = self.row(self._pressed)
        self.viewport().setCursor(Qt.CursorShape.SizeVerCursor)
        self.viewport().update()

    def _cancel_reordering(self):
        self._hold.stop()
        self._autoscroll.stop()
        self._animation.stop()
        self._pressed = None
        self._destination = -1
        self._offsets.clear()
        if self._dragging:
            self._dragging = False
            self.viewport().unsetCursor()
            self.viewport().update()

    def _dragged_rect(self):
        rect = self.visualItemRect(self._pressed)
        max_top = max(0, self.viewport().height() - rect.height())
        rect.moveTop(max(0, min(max_top, self._pointer.y() - self._grab_offset)))
        return rect

    def _update_destination(self):
        if not self._dragging:
            return
        origin = self.row(self._pressed)
        original = self.visualItemRect(self._pressed)
        center = self._pointer.y() - self._grab_offset + original.center().y() - original.top()
        destination = origin
        if center < original.center().y():
            while destination > 0 and center <= self._row_center(destination - 1):
                destination -= 1
        else:
            while destination < self.count() - 1 and center >= self._row_center(destination + 1):
                destination += 1
        if destination != self._destination:
            self._destination = destination
            self._slide_rows(origin, destination)
        self.viewport().update()

    def _row_center(self, row):
        return self.visualItemRect(self.item(row)).center().y()

    def _slide_rows(self, origin, destination):
        self._animation.stop()
        step = 1 if destination > origin else -1
        self._animation_end = {
            row: self._row_center(row - step) - self._row_center(row)
            for row in range(origin + step, destination + step, step)
        }
        self._animation_start = self._offsets.copy()
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.start()

    def _animate_rows(self, amount):
        self._offsets = {}
        for row in self._animation_start.keys() | self._animation_end.keys():
            start = self._animation_start.get(row, 0)
            end = self._animation_end.get(row, 0)
            offset = round(start + (end - start) * amount)
            if offset:
                self._offsets[row] = offset
        self.viewport().update()

    def _scroll_for_drag(self):
        scrollbar = self.verticalScrollBar()
        edge = 24
        if self._pointer.y() < edge:
            scrollbar.setValue(scrollbar.value() - 9)
        elif self._pointer.y() >= self.viewport().height() - edge:
            scrollbar.setValue(scrollbar.value() + 9)

    def paintEvent(self, event):
        if not self._dragging:
            super().paintEvent(event)
            return
        painter = QPainter(self.viewport())
        for row in range(self.count()):
            item = self.item(row)
            if item is not self._pressed:
                rect = self.visualItemRect(item).translated(0, self._offsets.get(row, 0))
                if rect.intersects(event.rect()):
                    self._paint_row(painter, item, rect)
        self._paint_row(painter, self._pressed, self._dragged_rect())
        painter.end()

    def _paint_row(self, painter, item, rect):
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = rect
        if item.isSelected():
            option.state |= QStyle.StateFlag.State_Selected
        self.itemDelegate().paint(painter, option, self.indexFromItem(item))
