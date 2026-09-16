"""Category selection shared by emoji package import and export."""
from __future__ import annotations

from collections import Counter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QListWidget,
    QListWidgetItem, QVBoxLayout,
)


class EmojiCategorySelectionDialog(QDialog):
    def __init__(self, categories, emojis, action="导出", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"选择{action}的表情包分类")
        self.setModal(True)
        self.resize(440, 420)
        layout = QVBoxLayout(self)
        hint = QLabel(f"勾选要{action}的分类文件夹，可选择一个、多个或全部分类。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.select_all = QCheckBox("全选")
        layout.addWidget(self.select_all)
        self.category_list = QListWidget(objectName="cleanList")
        self.category_list.setAccessibleName(f"选择{action}的分类文件夹")
        counts = Counter(record["category_id"] for record in emojis)
        for category in categories:
            item = QListWidgetItem(f"{category['name']}（{counts[category['id']]} 张）")
            item.setData(Qt.ItemDataRole.UserRole, category["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.category_list.addItem(item)
        layout.addWidget(self.category_list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText(f"{action}所选分类")
        self.confirm_button.setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.select_all.clicked.connect(self._toggle_all)
        self.category_list.itemChanged.connect(self._sync_selection)
        self._sync_selection()

    def selected_category_ids(self):
        return {self.category_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.category_list.count())
                if self.category_list.item(row).checkState() == Qt.CheckState.Checked}

    def _toggle_all(self, checked):
        self.category_list.blockSignals(True)
        for row in range(self.category_list.count()):
            self.category_list.item(row).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.category_list.blockSignals(False)
        self._sync_selection()

    def _sync_selection(self, item=None):
        count = len(self.selected_category_ids())
        self.select_all.blockSignals(True)
        partial = 0 < count < self.category_list.count()
        self.select_all.setTristate(partial)
        self.select_all.setCheckState(Qt.CheckState.PartiallyChecked if partial else
                                     Qt.CheckState.Checked if count else Qt.CheckState.Unchecked)
        self.select_all.blockSignals(False)
        self.confirm_button.setEnabled(count > 0)
