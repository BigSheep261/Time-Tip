"""Emoji/sticker library page and local category management."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImageReader
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.emoji_grid import EmojiGrid
from app.presentation.widgets import Card


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
DEFAULT_EMOJI_CATEGORY = {"id": "default", "name": "默认"}


class EmojiPageMixin:
    def _load_emoji_data(self):
        self.emoji_root = self.store.asset_root("emojis")
        raw_categories = self.store.read_json("emoji_categories", [])
        self.emoji_categories = []
        if isinstance(raw_categories, list):
            for source in raw_categories:
                if not isinstance(source, dict):
                    continue
                category_id = str(source.get("id", "")).strip()
                name = str(source.get("name", "")).strip()
                if category_id and name and not any(c["id"] == category_id for c in self.emoji_categories):
                    self.emoji_categories.append({"id": category_id, "name": name[:40]})
        if not any(c["id"] == "default" for c in self.emoji_categories):
            self.emoji_categories.insert(0, DEFAULT_EMOJI_CATEGORY.copy())
        raw_emojis = self.store.read_json("emojis", [])
        self.emojis = []
        if isinstance(raw_emojis, list):
            category_ids = {c["id"] for c in self.emoji_categories}
            for source in raw_emojis:
                if not isinstance(source, dict):
                    continue
                record_id = str(source.get("id", "")).strip()
                relative = str(source.get("path", "")).replace("\\", "/")
                if not record_id or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                    continue
                category_id = str(source.get("category_id", "default"))
                if category_id not in category_ids:
                    category_id = "default"
                absolute = (self.emoji_root / relative).resolve()
                if not absolute.is_file() or not absolute.is_relative_to(self.emoji_root.resolve()):
                    continue
                self.emojis.append({"id": record_id, "path": relative, "category_id": category_id})
        if self.store.read_json("emoji_categories", None) != self.emoji_categories:
            self.store.write_json("emoji_categories", self.emoji_categories)
        if self.store.read_json("emojis", None) != self.emojis:
            self.store.write_json("emojis", self.emojis)

    def _emoji_page(self) -> QWidget:
        self._load_emoji_data()
        self.active_emoji_category = "default"
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(QLabel("表情包", objectName="pageTitle"))
        subtitle = QLabel("把常用图片集中管理；可以拖入添加，也可以直接拖出到聊天窗口。", objectName="pageSubtitle")
        subtitle.setWordWrap(True)
        title.addWidget(subtitle)
        header.addLayout(title, 1)
        add_images = QPushButton("添加图片", objectName="secondaryButton")
        add_images.setMinimumHeight(44)
        add_images.clicked.connect(self._choose_emoji_files)
        header.addWidget(add_images)
        new_category = QPushButton("新建分类", objectName="primaryButton")
        new_category.setMinimumHeight(44)
        new_category.clicked.connect(self._new_emoji_category)
        header.addWidget(new_category)
        layout.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(14)
        side = Card()
        side.setMaximumWidth(210)
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("分类文件夹", objectName="fieldLabel"))
        self.emoji_category_list = QListWidget(objectName="cleanList")
        self.emoji_category_list.setAccessibleName("表情包分类文件夹")
        self.emoji_category_list.currentItemChanged.connect(self._emoji_category_changed)
        side_layout.addWidget(self.emoji_category_list, 1)
        category_buttons = QHBoxLayout()
        self.rename_emoji_category_button = QPushButton("重命名", objectName="secondaryButton")
        self.rename_emoji_category_button.clicked.connect(self._rename_emoji_category)
        category_buttons.addWidget(self.rename_emoji_category_button)
        self.delete_emoji_category_button = QPushButton("删除", objectName="secondaryButton")
        self.delete_emoji_category_button.clicked.connect(self._delete_emoji_category)
        category_buttons.addWidget(self.delete_emoji_category_button)
        side_layout.addLayout(category_buttons)
        content.addWidget(side)

        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        self.emoji_grid = EmojiGrid()
        self.emoji_grid.filesDropped.connect(self._import_emoji_files)
        self.emoji_grid.imageDropped.connect(self._import_emoji_image)
        self.emoji_grid.itemSelectionChanged.connect(self._update_emoji_actions)
        card_layout.addWidget(self.emoji_grid, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("拖入图片添加；选中图片后可拖出到聊天窗口。", objectName="cardHint"), 1)
        self.delete_emoji_button = QPushButton("删除所选", objectName="secondaryButton")
        self.delete_emoji_button.clicked.connect(self._delete_selected_emojis)
        footer.addWidget(self.delete_emoji_button)
        card_layout.addLayout(footer)
        content.addWidget(card, 1)
        layout.addLayout(content, 1)
        self._refresh_emoji_categories("default")
        return page

    def _category_by_id(self, category_id):
        return next((c for c in self.emoji_categories if c["id"] == category_id), DEFAULT_EMOJI_CATEGORY)

    def _refresh_emoji_categories(self, selected_id=None):
        self.emoji_category_list.blockSignals(True)
        self.emoji_category_list.clear()
        for category in self.emoji_categories:
            item = QListWidgetItem(category["name"])
            item.setData(Qt.ItemDataRole.UserRole, category["id"])
            self.emoji_category_list.addItem(item)
        chosen = selected_id or "default"
        for row in range(self.emoji_category_list.count()):
            if self.emoji_category_list.item(row).data(Qt.ItemDataRole.UserRole) == chosen:
                self.emoji_category_list.setCurrentRow(row)
                break
        self.emoji_category_list.blockSignals(False)
        self._emoji_category_changed(self.emoji_category_list.currentItem())

    def _emoji_category_changed(self, current, previous=None):
        if current is not None:
            self.active_emoji_category = current.data(Qt.ItemDataRole.UserRole)
        self._refresh_emoji_grid()
        is_default = self.active_emoji_category == "default"
        self.rename_emoji_category_button.setEnabled(not is_default)
        self.delete_emoji_category_button.setEnabled(not is_default)

    def _refresh_emoji_grid(self):
        self.emoji_grid.clear_images()
        for record in self.emojis:
            if record["category_id"] != self.active_emoji_category:
                continue
            path = (self.emoji_root / record["path"]).resolve()
            if path.is_file():
                display_record = {**record, "absolute_path": str(path)}
                self.emoji_grid.add_image(str(path), display_record)
        self._update_emoji_actions()

    def _update_emoji_actions(self):
        self.delete_emoji_button.setEnabled(bool(self.emoji_grid.selectedItems()))

    def _choose_emoji_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加表情包图片", "", "图片文件 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if paths:
            self._import_emoji_files(paths)

    def _import_emoji_files(self, paths):
        category_id = self.active_emoji_category
        category_root = self.emoji_root / category_id
        category_root.mkdir(parents=True, exist_ok=True)
        added = 0
        for source_name in paths:
            source = Path(source_name)
            if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if QImageReader(str(source)).read().isNull():
                continue
            record_id = uuid.uuid4().hex
            destination = category_root / (record_id + source.suffix.lower())
            try:
                shutil.copy2(source, destination)
            except OSError:
                continue
            self.emojis.append({"id": record_id, "path": destination.relative_to(self.emoji_root).as_posix(), "category_id": category_id})
            added += 1
        if added:
            self.store.write_json("emojis", self.emojis)
            self._refresh_emoji_grid()

    def _import_emoji_image(self, image):
        if image is None or image.isNull():
            return
        category_root = self.emoji_root / self.active_emoji_category
        category_root.mkdir(parents=True, exist_ok=True)
        record_id = uuid.uuid4().hex
        destination = category_root / (record_id + ".png")
        if not image.save(str(destination), "PNG"):
            return
        self.emojis.append({"id": record_id, "path": destination.relative_to(self.emoji_root).as_posix(),
                            "category_id": self.active_emoji_category})
        self.store.write_json("emojis", self.emojis)
        self._refresh_emoji_grid()

    def _new_emoji_category(self):
        name, accepted = QInputDialog.getText(self, "新建分类文件夹", "分类名称")
        name = name.strip()
        if not accepted or not name:
            return
        if any(c["name"] == name for c in self.emoji_categories):
            return
        category = {"id": uuid.uuid4().hex, "name": name[:40]}
        self.emoji_categories.append(category)
        (self.emoji_root / category["id"]).mkdir(parents=True, exist_ok=True)
        self.store.write_json("emoji_categories", self.emoji_categories)
        self._refresh_emoji_categories(category["id"])

    def _rename_emoji_category(self):
        category = self._category_by_id(self.active_emoji_category)
        name, accepted = QInputDialog.getText(self, "重命名分类文件夹", "分类名称", text=category["name"])
        name = name.strip()
        if not accepted or not name or name == category["name"]:
            return
        if any(c["id"] != category["id"] and c["name"] == name for c in self.emoji_categories):
            return
        category["name"] = name[:40]
        self.store.write_json("emoji_categories", self.emoji_categories)
        self._refresh_emoji_categories(category["id"])

    def _delete_emoji_category(self):
        if self.active_emoji_category == "default":
            return
        category = self._category_by_id(self.active_emoji_category)
        answer = QMessageBox.question(self, "删除分类文件夹", f"删除“{category['name']}”后，图片会移动到默认分类。继续吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        for record in self.emojis:
            if record["category_id"] == category["id"]:
                record["category_id"] = "default"
        self.emoji_categories = [c for c in self.emoji_categories if c["id"] != category["id"]]
        self.store.write_json("emoji_categories", self.emoji_categories)
        self.store.write_json("emojis", self.emojis)
        self._refresh_emoji_categories("default")

    def _delete_selected_emojis(self):
        selected = {item.data(Qt.ItemDataRole.UserRole)["id"] for item in self.emoji_grid.selectedItems()}
        if not selected:
            return
        # Stop animation callbacks before removing the displayed items and their source files.
        self.emoji_grid.clear_images()
        remaining = []
        for record in self.emojis:
            if record["id"] in selected:
                try:
                    (self.emoji_root / record["path"]).unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                remaining.append(record)
        self.emojis = remaining
        self.store.write_json("emojis", self.emojis)
        self._refresh_emoji_grid()
