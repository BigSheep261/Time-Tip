"""Memo page: rich text, ordered records, portable backups and save metadata."""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QTextCharFormat, QTextDocument
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from app.infrastructure.memo_transfer import export_memos, read_memos
from app.presentation.memo_editor import MemoFormatBar
from app.presentation.widgets import Card


def memo_timestamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def display_timestamp(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return "暂无记录"


class MemoPageMixin:
    def _memo_page(self) -> QWidget:
        self._memo_dirty = False
        self._memo_edited_at = ""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(QLabel("备忘录", objectName="pageTitle"), 1)
        self.memo_import_button = QPushButton("导入备忘录", objectName="secondaryButton")
        self.memo_import_button.setMinimumHeight(44)
        self.memo_import_button.setToolTip("从 JSON 文件追加备忘录，保留现有记录")
        self.memo_import_button.clicked.connect(self.import_memos)
        header.addWidget(self.memo_import_button)
        self.memo_export_button = QPushButton("导出备忘录", objectName="secondaryButton")
        self.memo_export_button.setMinimumHeight(44)
        menu = QMenu(self.memo_export_button)
        self.memo_export_current = menu.addAction("导出当前这条…", lambda: self.export_memos(current_only=True))
        self.memo_export_all = menu.addAction("导出全部备忘录…", lambda: self.export_memos(current_only=False))
        self.memo_export_button.setMenu(menu)
        header.addWidget(self.memo_export_button)
        layout.addLayout(header)
        subtitle = QLabel("一个想法，一条记录。支持富文本编辑，停止输入后自动保存。", objectName="pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        self.memo_transfer_feedback = QLabel(objectName="cardHint")
        self.memo_transfer_feedback.setWordWrap(True)
        self.memo_transfer_feedback.hide()
        layout.addWidget(self.memo_transfer_feedback)
        content = QHBoxLayout()
        content.setSpacing(14)
        left = Card()
        left.setMaximumWidth(260)
        left_layout = QVBoxLayout(left)
        new = QPushButton("＋ 新建备忘录", objectName="primaryButton")
        new.setMinimumHeight(44)
        new.clicked.connect(self.add_memo)
        left_layout.addWidget(new)
        hint = QLabel("按住条目上下拖拽排序", objectName="cardHint")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        self.memo_list = QListWidget(objectName="cleanList")
        self.memo_list.setMinimumWidth(160)
        self.memo_list.setAccessibleName("备忘录列表，可上下拖拽排序")
        self.memo_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.memo_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.memo_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.memo_list.setDropIndicatorShown(True)
        self.memo_list.setDragDropOverwriteMode(False)
        self.memo_list.model().rowsMoved.connect(self._memo_rows_moved)
        self.memo_list.currentItemChanged.connect(self._memo_selected)
        left_layout.addWidget(self.memo_list, 1)
        self.delete_memo_button = QPushButton("删除这条备忘录", objectName="secondaryButton")
        self.delete_memo_button.clicked.connect(self.delete_memo)
        left_layout.addWidget(self.delete_memo_button)
        self.undo_memo_button = QPushButton("撤销删除", objectName="secondaryButton")
        self.undo_memo_button.clicked.connect(self.undo_delete_memo)
        self.undo_memo_button.hide()
        left_layout.addWidget(self.undo_memo_button)
        content.addWidget(left, 1)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(8)
        card_layout.addWidget(QLabel("标题", objectName="fieldLabel"))
        self.memo_title = QLineEdit()
        self.memo_title.setPlaceholderText("给这条记录起个名字")
        self.memo_title.setMaxLength(120)
        self.memo_title.textChanged.connect(self._memo_changed)
        card_layout.addWidget(self.memo_title)
        self.memo_edit = QTextEdit()
        self.memo_edit.setAcceptRichText(True)
        self.memo_edit.setAccessibleName("备忘录富文本内容")
        self.memo_edit.document().setDefaultFont(QFont("Microsoft YaHei UI", 11))
        self.memo_edit.setPlaceholderText("点击「新建备忘录」开始记录……")
        self.memo_format = MemoFormatBar(self.memo_edit)
        card_layout.addWidget(self.memo_format)
        self.memo_edit.textChanged.connect(self._memo_changed)
        self.memo_timer = QTimer(self)
        self.memo_timer.setSingleShot(True)
        self.memo_timer.timeout.connect(self.save_memo)
        card_layout.addWidget(self.memo_edit, 1)
        bottom = QHBoxLayout()
        self.memo_status = QLabel("新建一条备忘录开始记录", objectName="cardHint")
        self.memo_status.setWordWrap(True)
        bottom.addWidget(self.memo_status, 1)
        self.memo_save_button = QPushButton("立即保存", objectName="primaryButton")
        self.memo_save_button.setMinimumHeight(44)
        self.memo_save_button.clicked.connect(lambda: self.save_memo(force=True))
        bottom.addWidget(self.memo_save_button)
        card_layout.addLayout(bottom)
        self.memo_saved_at_label = QLabel(objectName="cardHint")
        self.memo_edited_at_label = QLabel(objectName="cardHint")
        card_layout.addWidget(self.memo_saved_at_label)
        card_layout.addWidget(self.memo_edited_at_label)
        content.addWidget(card, 3)
        layout.addLayout(content, 1)
        return page

    def _refresh_memo_list(self, selected_id=None):
        self.memo_list.blockSignals(True)
        self.memo_list.clear()
        for memo in self.memos:
            item = QListWidgetItem(memo["title"] or "未命名备忘录")
            item.setData(Qt.ItemDataRole.UserRole, memo["id"])
            item.setToolTip(memo["title"] + "\n拖拽可调整顺序")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.memo_list.addItem(item)
        self._select_list_id(self.memo_list, selected_id)
        self.memo_list.blockSignals(False)
        self._load_memo_editor(selected_id)

    def _load_memo_editor(self, item_id):
        self.memo_timer.stop()
        self.active_memo_id = item_id
        memo = next((m for m in self.memos if m["id"] == item_id), None)
        self._memo_dirty = False
        self._memo_edited_at = memo.get("edited_at", "") if memo else ""
        for edit in (self.memo_title, self.memo_edit):
            edit.blockSignals(True)
            edit.setEnabled(memo is not None)
        self.memo_title.setText(memo["title"] if memo else "")
        self.memo_edit.setCurrentCharFormat(QTextCharFormat())
        if memo and isinstance(memo.get("html"), str) and memo["html"]:
            self.memo_edit.setHtml(memo["html"])
        else:
            self.memo_edit.setPlainText(memo["text"] if memo else "")
        if memo and memo.get("html"):
            cursor = self.memo_edit.textCursor()
            cursor.setPosition(0)
            cursor.movePosition(cursor.MoveOperation.NextCharacter)
            cursor.movePosition(cursor.MoveOperation.PreviousCharacter)
            self.memo_edit.setTextCursor(cursor)
        for edit in (self.memo_title, self.memo_edit):
            edit.blockSignals(False)
        self.memo_format.setEnabled(memo is not None)
        self.memo_format.sync_format(self.memo_edit.currentCharFormat())
        self.delete_memo_button.setEnabled(memo is not None)
        self.memo_save_button.setEnabled(memo is not None)
        self.memo_export_current.setEnabled(memo is not None)
        self.memo_export_all.setEnabled(bool(self.memos))
        self.memo_export_button.setEnabled(bool(self.memos))
        self.memo_status.setText("已保存" if memo else "新建一条备忘录开始记录")
        self._update_memo_times(memo)

    def _update_memo_times(self, memo):
        self.memo_saved_at_label.setText("上次保存：" + display_timestamp(memo.get("saved_at", "") if memo else ""))
        self.memo_edited_at_label.setText("上次编辑：" + display_timestamp(self._memo_edited_at if memo else ""))

    def _memo_selected(self, current, previous=None):
        item_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        if item_id == self.active_memo_id:
            return
        if not self.save_memo():
            self.memo_list.blockSignals(True)
            self._select_list_id(self.memo_list, self.active_memo_id)
            self.memo_list.blockSignals(False)
            return
        self._load_memo_editor(item_id)

    def add_memo(self):
        if not self.save_memo():
            return
        now = memo_timestamp()
        item = {"id": uuid.uuid4().hex, "title": "新备忘录", "text": "", "edited_at": now, "saved_at": now}
        if not self._persist_memos([*self.memos, item]):
            return
        self._refresh_memo_list(item["id"])
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.memo_title.setFocus()
        self.memo_title.selectAll()

    def delete_memo(self):
        if not self.active_memo_id or not self.save_memo():
            return
        index = next(i for i, m in enumerate(self.memos) if m["id"] == self.active_memo_id)
        deleted = (index, self.memos[index], self.widget_config.get("memo:" + self.active_memo_id, {}).copy())
        if not self._persist_memos([m for m in self.memos if m["id"] != self.active_memo_id]):
            return
        self.deleted_memo = deleted
        self.widget_config.pop("memo:" + self.active_memo_id, None)
        self.store.write_json("widgets", self.widget_config)
        selected = self.memos[min(index, len(self.memos) - 1)]["id"] if self.memos else None
        self._refresh_memo_list(selected)
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.undo_memo_button.show()

    def undo_delete_memo(self):
        if not self.deleted_memo or not self.save_memo():
            return
        index, item, config = self.deleted_memo
        restored = self.memos.copy()
        restored.insert(index, item)
        if not self._persist_memos(restored):
            return
        self.widget_config["memo:" + item["id"]] = config
        self.store.write_json("widgets", self.widget_config)
        self._refresh_memo_list(item["id"])
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.deleted_memo = None
        self.undo_memo_button.hide()

    def _memo_changed(self) -> None:
        if self.active_memo_id:
            self._memo_dirty = True
            self._memo_edited_at = memo_timestamp()
            memo = next(m for m in self.memos if m["id"] == self.active_memo_id)
            self._update_memo_times(memo)
            self.memo_status.setText("有修改，等待自动保存…")
            self.memo_timer.start(500)

    def _persist_memos(self, records):
        try:
            self.store.write_json("memos", records)
        except (OSError, sqlite3.Error) as error:
            self.memo_status.setText("保存失败，请重试：" + str(error))
            return False
        self.memos = records
        return True

    def save_memo(self, force=False) -> bool:
        self.memo_timer.stop()
        memo = next((m for m in self.memos if m["id"] == self.active_memo_id), None)
        if memo is None or not (self._memo_dirty or force):
            return True
        title, text = self.memo_title.text(), self.memo_edit.toPlainText()
        updated = {**memo, "title": title, "text": text, "html": self.memo_edit.toHtml(),
                   "saved_at": memo_timestamp(), "edited_at": self._memo_edited_at}
        if not self._persist_memos([updated if m["id"] == memo["id"] else m for m in self.memos]):
            return False
        self._memo_dirty = False
        for row in range(self.memo_list.count()):
            item = self.memo_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == memo["id"]:
                item.setText(title or "未命名备忘录")
                item.setToolTip(title + "\n拖拽可调整顺序")
        tile = self.tiles.get("memo:" + memo["id"])
        if tile:
            tile.title_label.setText(title or "未命名备忘录")
        if title != memo["title"]:
            self._refresh_widget_settings()
        self._render_dashboard(datetime.now())
        self.memo_status.setText("已保存")
        self._update_memo_times(updated)
        return True

    def _memo_rows_moved(self, *args):
        # Keep the editor and its selection intact while only changing list order.
        if not self.save_memo():
            return
        by_id = {m["id"]: m for m in self.memos}
        ordered = [by_id[self.memo_list.item(row).data(Qt.ItemDataRole.UserRole)]
                   for row in range(self.memo_list.count())]
        if not self._persist_memos(ordered):
            self._refresh_memo_list(self.active_memo_id)
            self.memo_status.setText("排序保存失败，已恢复原顺序")
            return
        self.memo_status.setText("顺序已保存")

    def _memo_transfer_message(self, text):
        self.memo_transfer_feedback.setText(text)
        self.memo_transfer_feedback.show()

    def export_memos(self, current_only=False):
        if not self.save_memo():
            return
        records = [m for m in self.memos if m["id"] == self.active_memo_id] if current_only else self.memos
        if not records:
            return
        name = re.sub(r'[\\/:*?"<>|]', "_", records[0]["title"]).strip(" .")[:80] if current_only else "TimeTip-备忘录"
        path, _ = QFileDialog.getSaveFileName(self, "导出当前备忘录" if current_only else "导出全部备忘录",
                                             (name or "备忘录") + ".json", "备忘录文件 (*.json)")
        if not path:
            return
        # A native file dialog runs its own event loop; capture the latest saved state.
        if not self.save_memo():
            return
        records = [m for m in self.memos if m["id"] == self.active_memo_id] if current_only else self.memos
        try:
            export_memos(path, records)
            self._memo_transfer_message(f"已导出 {len(records)} 条备忘录：{path}")
        except (OSError, ValueError) as error:
            self._memo_transfer_message("导出失败：" + str(error))

    def import_memos(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入备忘录（追加到现有列表）", "", "备忘录 / TimeTip JSON 文件 (*.json)")
        if not path:
            return
        try:
            records = read_memos(path)
            if not records:
                self._memo_transfer_message("文件中没有备忘录可导入。")
                return
            now = memo_timestamp()
            for record in records:
                record.update(id=uuid.uuid4().hex, saved_at=now)
                if record.get("html"):
                    document = QTextDocument()
                    document.setHtml(record["html"])
                    record["text"] = document.toPlainText()
            if not self.save_memo() or not self._persist_memos([*self.memos, *records]):
                return
            self._refresh_memo_list(records[0]["id"])
            self._rebuild_dashboard()
            self._refresh_widget_settings()
            self._memo_transfer_message(f"已导入 {len(records)} 条备忘录，已追加到列表末尾。")
        except (OSError, ValueError) as error:
            self._memo_transfer_message("导入失败：" + str(error))
