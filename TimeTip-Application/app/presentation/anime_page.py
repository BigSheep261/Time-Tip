"""Anime list, organization and editing; legacy page adapter."""
from __future__ import annotations

import uuid

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTimeEdit, QVBoxLayout, QWidget

from app.domain.anime import normalize_tags, validate_anime
from app.domain.anime_organization import anime_groups, group_name, reorder_anime
from app.presentation.anime_dialog import AnimeDialog
from app.presentation.anime_organization import AnimeGroupsDialog, AnimeListWidget


from app.presentation.anime_widgets import AnimeCard, AnimeFolderDialog

class AnimePageMixin:
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


