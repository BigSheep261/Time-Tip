"""Fixed-height list widgets for the JM page."""
from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import QLabel, QListWidget, QSizePolicy


class MarqueeLabel(QLabel):
    """Scroll overflowing plain text without increasing the layout minimum width."""

    def __init__(self, text="", parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setToolTip(text)
        self.setMinimumWidth(0)
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._offset = 0
        self._pause = 30
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self._reset_scroll()

    def _overflow(self):
        return max(0, self.fontMetrics().horizontalAdvance(self.text()) - self.contentsRect().width())

    def _reset_scroll(self):
        self._offset = 0
        self._pause = 30
        if self.isVisible() and self._overflow() > 0:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance(self):
        # Off-screen list items need no animation; hiding the page stops its timers.
        if self.visibleRegion().isEmpty():
            return
        if self._pause:
            self._pause -= 1
            return
        end = self._overflow()
        if self._offset >= end:
            self._offset = 0
            self._pause = 30
        else:
            self._offset = min(end, self._offset + 1)
            if self._offset == end:
                self._pause = 30
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reset_scroll()

    def showEvent(self, event):
        super().showEvent(event)
        self._reset_scroll()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "_timer") and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._reset_scroll()

    def paintEvent(self, event):
        if not self._overflow():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setClipRect(self.contentsRect())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        rect = self.contentsRect().adjusted(-self._offset, 0, self._overflow(), 0)
        painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                         | Qt.TextFlag.TextSingleLine, self.text())


class JMListWidget(QListWidget):
    def __init__(self, height):
        super().__init__(objectName="cleanList")
        # Each row owns its padding. The shared cleanList padding otherwise
        # reduces the row's usable area and squeezes its controls.
        self.setStyleSheet("#cleanList::item { padding: 0px; margin: 0px; }")
        self.setSpacing(6)
        self.setFixedHeight(height)
        self.setMinimumWidth(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setUniformItemSizes(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Update embedded row widgets immediately when the main window shrinks.
        self.doItemsLayout()

    def sizeHint(self):
        return QSize(320, self.height())
