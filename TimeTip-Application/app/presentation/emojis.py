"""Emoji/sticker library page and local category management."""
from __future__ import annotations

import sqlite3
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QSaveFile, Qt
from PyQt6.QtGui import QImageReader
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app.presentation.emoji_category_list import EmojiCategoryList
from app.presentation.emoji_grid import EmojiGrid
from app.presentation.widgets import Card
from app.infrastructure.emoji_transfer import export_emoji_package, read_emoji_package
from app.infrastructure.emoji_images import emoji_fingerprint
from app.presentation.emoji_dialog import EmojiCategorySelectionDialog


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
DEFAULT_EMOJI_CATEGORY = {"id": "default", "name": "默认"}


class EmojiPageMixin:
    def _load_emoji_data(self):
        self._emoji_fingerprint_cache = {}
        self._emoji_duplicate_ids = set()
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
        self._refresh_duplicate_ids()
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
        self.emoji_feedback = QLabel(objectName="cardHint")
        self.emoji_feedback.setWordWrap(True)
        self.emoji_feedback.hide()
        add_images = QPushButton("添加图片", objectName="secondaryButton")
        add_images.setMinimumHeight(44)
        add_images.clicked.connect(self._choose_emoji_files)
        header.addWidget(add_images)
        self.import_emoji_button = QPushButton("导入表情包", objectName="secondaryButton")
        self.import_emoji_button.setMinimumHeight(44)
        self.import_emoji_button.clicked.connect(self._import_emoji_package)
        header.addWidget(self.import_emoji_button)
        self.export_emoji_button = QPushButton("导出表情包", objectName="secondaryButton")
        self.export_emoji_button.setMinimumHeight(44)
        self.export_emoji_button.clicked.connect(self._export_emoji_package)
        header.addWidget(self.export_emoji_button)
        self.emoji_sort_button = QPushButton("调整排序", objectName="secondaryButton")
        self.emoji_sort_button.setCheckable(True)
        self.emoji_sort_button.setMinimumHeight(44)
        self.emoji_sort_button.clicked.connect(self._toggle_emoji_reordering)
        header.addWidget(self.emoji_sort_button)
        new_category = QPushButton("新建分类", objectName="primaryButton")
        new_category.setMinimumHeight(44)
        new_category.clicked.connect(self._new_emoji_category)
        header.addWidget(new_category)
        layout.addLayout(header)
        layout.addWidget(self.emoji_feedback)

        content = QHBoxLayout()
        content.setSpacing(14)
        side = Card()
        side.setMaximumWidth(210)
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(QLabel("分类文件夹", objectName="fieldLabel"))
        self.emoji_category_list = EmojiCategoryList()
        self.emoji_category_list.setAccessibleName("表情包分类文件夹")
        self.emoji_category_list.setToolTip("按住分类 5 秒后可上下拖动排序")
        self.emoji_category_list.currentItemChanged.connect(self._emoji_category_changed)
        self.emoji_category_list.reordered.connect(self._save_emoji_category_order)
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
        self.emoji_grid.reordered.connect(self._emoji_rows_reordered)
        self.emoji_grid.itemSelectionChanged.connect(self._update_emoji_actions)
        card_layout.addWidget(self.emoji_grid, 1)
        footer = QHBoxLayout()
        hint = QLabel("拖入添加，选中后可拖出。", objectName="cardHint")
        hint.setWordWrap(True)
        footer.addWidget(hint, 1)
        self.move_emoji_button = QPushButton("移动所选", objectName="secondaryButton")
        self.move_emoji_button.clicked.connect(lambda: self._choose_emoji_transfer(move=True))
        footer.addWidget(self.move_emoji_button)
        self.copy_emoji_button = QPushButton("复制所选", objectName="secondaryButton")
        self.copy_emoji_button.clicked.connect(lambda: self._choose_emoji_transfer(move=False))
        footer.addWidget(self.copy_emoji_button)
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
        duplicate_counts = defaultdict(int)
        for record in self.emojis:
            if record["id"] in self._emoji_duplicate_ids:
                duplicate_counts[record["category_id"]] += 1
        for category in self.emoji_categories:
            suffix = f"（{duplicate_counts[category['id']]} 张重复）" if duplicate_counts[category["id"]] else ""
            item = QListWidgetItem(category["name"] + suffix)
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

    def _save_emoji_category_order(self, ordered_ids):
        categories = {category["id"]: category for category in self.emoji_categories}
        if len(ordered_ids) != len(categories) or set(ordered_ids) != categories.keys():
            self._refresh_emoji_categories(self.active_emoji_category)
            return
        reordered = [categories[category_id] for category_id in ordered_ids]
        try:
            self.store.write_json("emoji_categories", reordered)
        except (OSError, sqlite3.Error) as error:
            self._refresh_emoji_categories(self.active_emoji_category)
            self._show_emoji_feedback(f"保存分类顺序失败：{error}")
            return
        self.emoji_categories = reordered

    def _refresh_emoji_grid(self):
        self.emoji_grid.clear_images()
        for record in self.emojis:
            if record["category_id"] != self.active_emoji_category:
                continue
            path = (self.emoji_root / record["path"]).resolve()
            if path.is_file():
                display_record = {**record, "absolute_path": str(path)}
                self.emoji_grid.add_image(str(path), display_record)
        self.emoji_grid.highlight_duplicates(self._emoji_duplicate_ids)
        self._update_emoji_actions()

    def _fingerprint_for_path(self, path: Path):
        try:
            stat = path.stat()
            key = path.resolve().as_posix()
            cached = self._emoji_fingerprint_cache.get(key)
            stamp = (stat.st_mtime_ns, stat.st_size)
            if cached and cached[0] == stamp:
                return cached[1]
            value = emoji_fingerprint(path.read_bytes())
            self._emoji_fingerprint_cache[key] = (stamp, value)
            return value
        except OSError:
            return None

    def _refresh_duplicate_ids(self):
        seen = {}
        duplicates = set()
        for record in self.emojis:
            fingerprint = self._fingerprint_for_path(self.emoji_root / record["path"])
            if not fingerprint:
                continue
            previous = seen.setdefault(record["category_id"], {})
            if fingerprint in previous:
                duplicates.add(previous[fingerprint])
                duplicates.add(record["id"])
            else:
                previous[fingerprint] = record["id"]
        self._emoji_duplicate_ids = duplicates

    def _show_emoji_feedback(self, text):
        self.emoji_feedback.setText(text)
        self.emoji_feedback.show()

    def _category_fingerprint_index(self, category_id):
        result = {}
        for record in self.emojis:
            if record["category_id"] != category_id:
                continue
            fingerprint = self._fingerprint_for_path(self.emoji_root / record["path"])
            if fingerprint:
                result.setdefault(fingerprint, record["id"])
        return result

    def _add_emoji_bytes(self, data, suffix, category_id, fingerprints):
        fingerprint = emoji_fingerprint(data)
        if not fingerprint:
            return None, None
        duplicate_id = fingerprints.get(fingerprint)
        if duplicate_id:
            return None, duplicate_id
        record_id = uuid.uuid4().hex
        destination = self.emoji_root / category_id / (record_id + suffix)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        except OSError:
            return None, None
        self.emojis.append({"id": record_id, "path": destination.relative_to(self.emoji_root).as_posix(),
                            "category_id": category_id})
        fingerprints[fingerprint] = record_id
        return record_id, None

    def _update_emoji_actions(self):
        has_selection = bool(self.emoji_grid.selectedItems())
        can_transfer = has_selection and len(self.emoji_categories) > 1
        self.move_emoji_button.setEnabled(can_transfer)
        self.copy_emoji_button.setEnabled(can_transfer)
        self.delete_emoji_button.setEnabled(has_selection)

    def _choose_emoji_transfer(self, *, move):
        selected = {item.data(Qt.ItemDataRole.UserRole)["id"] for item in self.emoji_grid.selectedItems()}
        source_id = self.active_emoji_category
        if not selected or len(self.emoji_categories) < 2:
            return

        action = "移动" if move else "复制"
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{action}所选图片")
        layout = QVBoxLayout(dialog)
        label = QLabel(f"将 {len(selected)} 张图片{action}到")
        layout.addWidget(label)
        destinations = QComboBox()
        for category in self.emoji_categories:
            if category["id"] != source_id:
                destinations.addItem(category["name"], category["id"])
        label.setBuddy(destinations)
        layout.addWidget(destinations)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(action)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._transfer_emojis(selected, source_id, destinations.currentData(), move=move)

    def _transfer_emojis(self, selected, source_id, target_id, *, move):
        if source_id == target_id or not any(category["id"] == target_id for category in self.emoji_categories):
            return
        root = self.emoji_root.resolve()
        target_root = (root / target_id).resolve()
        if root not in target_root.parents:
            self._show_emoji_feedback("目标分类的存储路径无效。")
            return

        action = "移动" if move else "复制"
        fingerprints = self._category_fingerprint_index(target_id)
        transferred = []
        copied_paths = []
        moved_sources = {}
        duplicates = 0
        failed = 0
        for index, record in enumerate(self.emojis):
            if record["id"] not in selected or record["category_id"] != source_id:
                continue
            try:
                source = (root / record["path"]).resolve()
                if not source.is_relative_to(root):
                    raise OSError("Invalid emoji path")
                data = source.read_bytes()
                fingerprint = emoji_fingerprint(data)
                if not fingerprint:
                    raise OSError("Invalid emoji image")
                if fingerprint in fingerprints:
                    duplicates += 1
                    continue
                file_id = uuid.uuid4().hex
                destination = target_root / (file_id + source.suffix.lower())
                target_root.mkdir(parents=True, exist_ok=True)
                output = QSaveFile(str(destination))
                if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise OSError(output.errorString())
                if output.write(data) != len(data):
                    output.cancelWriting()
                    raise OSError(output.errorString())
                if not output.commit():
                    raise OSError(output.errorString())
            except OSError:
                failed += 1
                continue

            new_id = record["id"] if move else file_id
            transferred.append({"id": new_id, "path": destination.relative_to(root).as_posix(),
                                "category_id": target_id})
            fingerprints[fingerprint] = new_id
            copied_paths.append(destination)
            if move:
                moved_sources[index] = source

        if transferred:
            remaining = [record for index, record in enumerate(self.emojis) if index not in moved_sources]
            updated = remaining + transferred
            try:
                self.store.write_json("emojis", updated)
            except (OSError, sqlite3.Error) as error:
                self._remove_emoji_files(copied_paths)
                self._show_emoji_feedback(f"{action}失败：{error}")
                return
            self.emojis = updated
            if moved_sources:
                retained_paths = {(root / record["path"]).resolve() for record in remaining}
                self._remove_emoji_files(set(moved_sources.values()) - retained_paths)
            self._refresh_duplicate_ids()
            self._refresh_emoji_categories(self.active_emoji_category)

        feedback = [f"已{action} {len(transferred)} 张图片到“{self._category_by_id(target_id)['name']}”"]
        if duplicates:
            feedback.append(f"{duplicates} 张在目标分类已有相同图片，已跳过")
        if failed:
            feedback.append(f"{failed} 张因文件无法读取或写入而未处理")
        self._show_emoji_feedback("，".join(feedback) + "。")

    def _remove_emoji_files(self, paths):
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _toggle_emoji_reordering(self, enabled: bool):
        self.emoji_grid.set_reordering(enabled)
        self.emoji_sort_button.setText("完成排序" if enabled else "调整排序")

    def _emoji_rows_reordered(self, ordered_ids):
        current_ids = [record["id"] for record in self.emojis
                       if record["category_id"] == self.active_emoji_category]
        if len(ordered_ids) != len(current_ids) or set(ordered_ids) != set(current_ids):
            return
        by_id = {record["id"]: record for record in self.emojis}
        reordered = [by_id[item_id] for item_id in ordered_ids]
        iterator = iter(reordered)
        self.emojis = [
            next(iterator) if record["category_id"] == self.active_emoji_category else record
            for record in self.emojis
        ]
        self.store.write_json("emojis", self.emojis)

    def _export_emoji_package(self):
        dialog = EmojiCategorySelectionDialog(self.emoji_categories, self.emojis, "导出", self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        selected_ids = dialog.selected_category_ids()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出表情包", "TimeTip-表情包.zip", "表情包包 (*.zip)"
        )
        if not path:
            return
        try:
            export_emoji_package(path, self.emoji_categories, self.emojis, self.emoji_root, selected_ids)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "导出表情包失败", str(error))
            return
        self._show_emoji_feedback("表情包已导出。")

    def _import_emoji_package(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入表情包", "", "表情包包 (*.zip)"
        )
        if not path:
            return
        try:
            categories, records, assets = read_emoji_package(path)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, "导入表情包失败", str(error))
            return
        dialog = EmojiCategorySelectionDialog(categories, records, "导入", self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        selected_ids = dialog.selected_category_ids()
        categories = [category for category in categories if category["id"] in selected_ids]
        records = [record for record in records if record["category_id"] in selected_ids]

        existing_names = {category["name"] for category in self.emoji_categories}
        category_map = {"default": "default"}
        imported_categories = 0
        for category in categories:
            source_id = category["id"]
            if source_id == "default":
                continue
            existing = next((item for item in self.emoji_categories if item["name"] == category["name"]), None)
            if existing:
                category_map[source_id] = existing["id"]
                continue
            name = category["name"]
            base = name
            index = 1
            while name in existing_names:
                index += 1
                name = f"{base}（导入{index}）"
            new_id = uuid.uuid4().hex
            category_map[source_id] = new_id
            self.emoji_categories.append({"id": new_id, "name": name[:40]})
            existing_names.add(name)
            (self.emoji_root / new_id).mkdir(parents=True, exist_ok=True)
            imported_categories += 1

        imported_images = 0
        duplicate_ids = set()
        fingerprints_by_category = {category["id"]: self._category_fingerprint_index(category["id"])
                                    for category in self.emoji_categories}
        for record in records:
            category_id = category_map.get(record["category_id"], "default")
            source_bytes = assets.get(record["path"])
            if source_bytes is None:
                continue
            suffix = Path(record["path"]).suffix.lower()
            new_id, duplicate_id = self._add_emoji_bytes(source_bytes, suffix, category_id,
                                                         fingerprints_by_category.setdefault(category_id, {}))
            if new_id:
                imported_images += 1
            elif duplicate_id:
                duplicate_ids.add(duplicate_id)
        self.store.write_json("emoji_categories", self.emoji_categories)
        self.store.write_json("emojis", self.emojis)
        self._emoji_duplicate_ids = duplicate_ids
        self._refresh_emoji_categories(self.active_emoji_category)
        if duplicate_ids:
            self._show_emoji_feedback(f"已导入 {imported_categories} 个分类、{imported_images} 张图片；重复图片已跳过并高亮显示。")
        else:
            self._show_emoji_feedback(f"已导入 {imported_categories} 个分类、{imported_images} 张图片。")

    def _choose_emoji_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加表情包图片", "", "图片文件 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if paths:
            self._import_emoji_files(paths)

    def _import_emoji_files(self, paths):
        category_id = self.active_emoji_category
        added = 0
        duplicate_ids = set()
        fingerprints = self._category_fingerprint_index(category_id)
        for source_name in paths:
            source = Path(source_name)
            if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if QImageReader(str(source)).read().isNull():
                continue
            try:
                data = source.read_bytes()
            except OSError:
                continue
            record_id, duplicate_id = self._add_emoji_bytes(data, source.suffix.lower(), category_id, fingerprints)
            if record_id:
                added += 1
            elif duplicate_id:
                duplicate_ids.add(duplicate_id)
        if added:
            self.store.write_json("emojis", self.emojis)
        self._emoji_duplicate_ids = duplicate_ids
        self._refresh_emoji_grid()
        if duplicate_ids:
            self._show_emoji_feedback(f"{len(duplicate_ids)} 张重复图片已跳过，并高亮显示已有图片。")

    def _import_emoji_image(self, image):
        if image is None or image.isNull():
            return
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            return
        record_id, duplicate_id = self._add_emoji_bytes(bytes(buffer.data()), ".png", self.active_emoji_category,
                                                        self._category_fingerprint_index(self.active_emoji_category))
        if record_id:
            self.store.write_json("emojis", self.emojis)
        self._emoji_duplicate_ids = {duplicate_id} if duplicate_id else set()
        self._refresh_emoji_grid()
        if duplicate_id:
            self._show_emoji_feedback("重复图片已跳过，并高亮显示已有图片。")

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
