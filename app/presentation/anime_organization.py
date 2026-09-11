"""Native card reordering and a custom-group editor."""
from __future__ import annotations

from PyQt6.QtCore import QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDrag, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from app.domain.anime_organization import UNGROUPED, anime_groups, group_name


class AnimeDragHandle(QWidget):
    """Paint grip dots without depending on a font's symbol coverage."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 36)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().text())
        painter.setOpacity(0.5)
        for x in (5, 12):
            for y in (9, 16, 23):
                painter.drawEllipse(x, y, 3, 3)
        painter.end()


class AnimeListWidget(QListWidget):
    """Move records explicitly: Qt's item-widget drop handling varies by version."""

    orderRequested = pyqtSignal(list)
    MIME_TYPE = "application/x-timetip-anime"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("animeListPanel")
        self._drop_row = None
        self._drag_position = None
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._scroll_drag)
        self.setAutoScroll(False)
        self.setAutoScrollMargin(40)
        self.setDragDropOverwriteMode(False)
        self.setAccessibleName("番剧卡片列表")

    def ids(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not self.dragEnabled() or item is None:
            return
        mime = QMimeData()
        mime.setData(self.MIME_TYPE, str(item.data(Qt.ItemDataRole.UserRole)).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        card = self.itemWidget(item)
        if card:
            drag.setPixmap(card.grab().scaledToWidth(min(360, card.width()), Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.MoveAction)
        drag.deleteLater()
        self._scroll_timer.stop()
        self._drag_position = None
        self._drop_row = None
        self.viewport().update()

    def _can_drop(self, event):
        return (self.dragEnabled() and event.source() is self
                and event.mimeData().hasFormat(self.MIME_TYPE))

    def dragEnterEvent(self, event):
        if self._can_drop(event):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def _insertion_row(self, position):
        item = self.itemAt(position)
        if item:
            return self.row(item) + int(position.y() >= self.visualItemRect(item).center().y())
        for row in range(self.count()):
            if position.y() < self.visualItemRect(self.item(row)).center().y():
                return row
        return self.count()

    def dragMoveEvent(self, event):
        if not self._can_drop(event):
            event.ignore()
            return
        self._drag_position = event.position().toPoint()
        self._drop_row = self._insertion_row(self._drag_position)
        self._scroll_timer.start()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.viewport().update()

    def _scroll_drag(self):
        if self._drag_position is None or not self.dragEnabled():
            self._scroll_timer.stop()
            return
        y = self._drag_position.y()
        delta = -20 if y < 40 else 20 if y > self.viewport().height() - 40 else 0
        if delta:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + delta)
            self._drop_row = self._insertion_row(self._drag_position)
            self.viewport().update()

    def dragLeaveEvent(self, event):
        self._scroll_timer.stop()
        self._drag_position = None
        self._drop_row = None
        super().dragLeaveEvent(event)
        self.viewport().update()

    def dropEvent(self, event):
        self._scroll_timer.stop()
        self._drag_position = None
        if not self._can_drop(event):
            event.ignore()
            return
        item_id = bytes(event.mimeData().data(self.MIME_TYPE)).decode("utf-8")
        ids = self.ids()
        if item_id not in ids:
            event.ignore()
            return
        target = self._insertion_row(event.position().toPoint())
        source = ids.index(item_id)
        ids.pop(source)
        ids.insert(target - int(source < target), item_id)
        self._drop_row = None
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self.viewport().update()
        if ids != self.ids():
            self.orderRequested.emit(ids)

    def move_current(self, offset):
        source = self.currentRow()
        target = source + offset
        if not self.dragEnabled() or source < 0 or not 0 <= target < self.count():
            return
        ids = self.ids()
        ids.insert(target, ids.pop(source))
        self.orderRequested.emit(ids)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.AltModifier and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move_current(-1 if event.key() == Qt.Key.Key_Up else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_row is None or not self.count():
            return
        row = min(self._drop_row, self.count() - 1)
        rect = self.visualItemRect(self.item(row))
        y = rect.top() - 3 if self._drop_row < self.count() else rect.bottom() + 3
        painter = QPainter(self.viewport())
        painter.setPen(QPen(self.palette().highlight().color(), 3))
        painter.drawLine(rect.left(), y, rect.right(), y)
        painter.end()


class AnimeGroupsDialog(QDialog):
    """Edit a draft so Cancel leaves both groups and assignments untouched."""

    def __init__(self, items, groups, parent=None):
        super().__init__(parent)
        self.items = [dict(item) for item in items]
        self.groups = anime_groups(items, groups)
        self.setObjectName("animeDialog")
        self.setWindowTitle("管理番剧分组")
        self.resize(480, 460)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(12)
        outer.addWidget(QLabel("自定义分组", objectName="animeDialogTitle"))
        hint = QLabel("新建分组后，可在番剧编辑窗口中选择。\n删除分组会将其中番剧移至“未分组”，番剧本身会保留。", objectName="animeDialogHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        self.list = QListWidget(objectName="cleanList")
        self.list.setAccessibleName("自定义分组列表")
        outer.addWidget(self.list, 1)
        outer.addWidget(QLabel("分组名称"))
        self.name = QLineEdit()
        self.name.setAccessibleName("分组名称")
        self.name.setPlaceholderText("例如：2026 秋季、收藏、待补番")
        self.name.setMaxLength(80)
        outer.addWidget(self.name)
        actions = QHBoxLayout()
        for label, method in (("新建分组", self.add_group), ("重命名", self.rename_group), ("删除分组", self.delete_group)):
            button = QPushButton(label, objectName="secondaryButton")
            button.clicked.connect(method)
            actions.addWidget(button)
        outer.addLayout(actions)
        self.feedback = QLabel("", objectName="animeDialogError")
        self.feedback.setWordWrap(True)
        self.feedback.hide()
        outer.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存分组")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.list.currentItemChanged.connect(self._selected)
        self._refresh()

    def _feedback(self, text):
        self.feedback.setText(text)
        self.feedback.setVisible(bool(text))

    def _selected(self, item, previous=None):
        self.name.setText(item.data(Qt.ItemDataRole.UserRole) if item else "")

    def _refresh(self, selected=None):
        self.list.clear()
        for name in self.groups:
            count = sum(group_name(item.get("group")) == name for item in self.items)
            row = QListWidgetItem(f"{name}  ·  {count} 部")
            row.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(row)
            if name == selected:
                self.list.setCurrentItem(row)

    def _new_name(self, old=None):
        name = self.name.text().strip()
        if not name:
            self._feedback("请填写分组名称。")
        elif name == UNGROUPED:
            self._feedback("“未分组”是系统分组，请使用其他名称。")
        elif any(name.casefold() == group.casefold() for group in self.groups if group != old):
            self._feedback("该分组已存在，请使用其他名称。")
        else:
            self._feedback("")
            return name
        return None

    def add_group(self):
        name = self._new_name()
        if name:
            self.groups.append(name)
            self._refresh(name)

    def _editable_group(self):
        item = self.list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if name is None or name == UNGROUPED:
            self._feedback("请选择一个自定义分组；“未分组”不能重命名或删除。")
            return None
        return name

    def rename_group(self):
        old = self._editable_group()
        if old is None:
            return
        name = self._new_name(old)
        if name:
            self.groups[self.groups.index(old)] = name
            for item in self.items:
                if group_name(item.get("group")) == old:
                    item["group"] = name
            self._refresh(name)

    def delete_group(self):
        old = self._editable_group()
        if old is None:
            return
        self.groups.remove(old)
        for item in self.items:
            if group_name(item.get("group")) == old:
                item["group"] = UNGROUPED
        self._refresh(UNGROUPED)
        self._feedback("分组已从草稿中移除，点击“保存分组”生效。")
