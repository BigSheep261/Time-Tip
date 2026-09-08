"""Countdown form, selection and view rendering."""
from datetime import datetime
from PyQt6.QtCore import QDateTime, QTime, Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit, QComboBox, QDateTimeEdit, QTimeEdit, QPushButton, QCheckBox)
from app.presentation.widgets import Card
from app.domain.countdowns import countdown_snapshot
from app.application.countdowns import prepare_countdown, collect_due

class CountdownPageMixin:
    def _countdowns_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 14)
        layout.setSpacing(14)
        self._page_header(layout, "倒计时", "标准倒计时到期停止，循环倒计时按时段自动开始下一轮。")
        self.countdown_list = QListWidget(objectName="cleanList")
        self.countdown_list.setFixedHeight(140)
        self.countdown_list.setWordWrap(True)
        self.countdown_list.currentItemChanged.connect(self._countdown_selected)
        layout.addWidget(self.countdown_list)
        card = Card()
        form = QVBoxLayout(card)
        form.setContentsMargins(20, 18, 20, 18)
        form.setSpacing(10)
        self.countdown_form_title = QLabel("新建倒计时", objectName="cardTitle")
        form.addWidget(self.countdown_form_title)
        names = QGridLayout()
        names.setColumnStretch(0, 2)
        names.setColumnStretch(1, 1)
        self.countdown_name = QLineEdit()
        self.countdown_name.setMaxLength(120)
        self.countdown_name.setPlaceholderText("例如：周末旅行、下班")
        self.countdown_mode = QComboBox()
        self.countdown_mode.addItem("标准倒计时", "standard")
        self.countdown_mode.addItem("循环倒计时", "cyclic")
        for col, (label, widget) in enumerate((("名称", self.countdown_name), ("倒计时类型", self.countdown_mode))):
            field = QLabel(label, objectName="fieldLabel")
            field.setBuddy(widget)
            names.addWidget(field, 0, col)
            names.addWidget(widget, 1, col)
        form.addLayout(names)
        self.standard_fields = QWidget()
        standard = QVBoxLayout(self.standard_fields)
        standard.setContentsMargins(0, 0, 0, 0)
        standard.addWidget(QLabel("目标时间（电脑本地时间）", objectName="fieldLabel"))
        self.target_edit = QDateTimeEdit()
        self.target_edit.setCalendarPopup(True)
        self.target_edit.setDisplayFormat("yyyy年 MM月 dd日  HH:mm:ss")
        self.target_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        standard.addWidget(self.target_edit)
        form.addWidget(self.standard_fields)
        self.cycle_fields = QWidget()
        cycle = QVBoxLayout(self.cycle_fields)
        cycle.setContentsMargins(0, 0, 0, 0)
        fields = QGridLayout()
        self.cycle_frequency = QComboBox()
        for title, value in (("每天", "daily"), ("周一至周五", "weekdays"), ("每周自选", "weekly")):
            self.cycle_frequency.addItem(title, value)
        self.cycle_start = QTimeEdit(QTime(9, 30))
        self.cycle_end = QTimeEdit(QTime(17, 30))
        for edit in (self.cycle_start, self.cycle_end):
            edit.setDisplayFormat("HH:mm")
        for col, (label, widget) in enumerate((("重复周期", self.cycle_frequency), ("开始时间", self.cycle_start), ("结束时间", self.cycle_end))):
            field = QLabel(label, objectName="fieldLabel")
            field.setBuddy(widget)
            fields.addWidget(field, 0, col)
            fields.addWidget(widget, 1, col)
            fields.setColumnStretch(col, 1)
        cycle.addLayout(fields)
        self.cycle_days_widget = QWidget()
        days = QHBoxLayout(self.cycle_days_widget)
        days.setContentsMargins(0, 0, 0, 0)
        self.cycle_weekday_checks = []
        for index, day in enumerate("一二三四五六日"):
            check = QCheckBox("周" + day)
            check.setChecked(index < 5)
            self.cycle_weekday_checks.append(check)
            days.addWidget(check)
        cycle.addWidget(self.cycle_days_widget)
        form.addWidget(self.cycle_fields)
        self.countdown_feedback = QLabel("", objectName="cardHint")
        self.countdown_feedback.setWordWrap(True)
        form.addWidget(self.countdown_feedback)
        row = QHBoxLayout()
        self.save_countdown_button = QPushButton("添加倒计时", objectName="primaryButton")
        self.save_countdown_button.clicked.connect(self.save_target)
        row.addWidget(self.save_countdown_button)
        new = QPushButton("新建另一条", objectName="secondaryButton")
        new.clicked.connect(self.new_countdown)
        row.addWidget(new)
        row.addStretch()
        self.delete_countdown_button = QPushButton("删除选中", objectName="secondaryButton")
        self.delete_countdown_button.clicked.connect(self.delete_countdown)
        self.delete_countdown_button.setEnabled(False)
        row.addWidget(self.delete_countdown_button)
        form.addLayout(row)
        self.undo_countdown_button = QPushButton("撤销删除", objectName="secondaryButton")
        self.undo_countdown_button.clicked.connect(self.undo_delete_countdown)
        self.undo_countdown_button.hide()
        form.addWidget(self.undo_countdown_button, 0, Qt.AlignmentFlag.AlignLeft)
        for widget in (self.countdown_name, self.countdown_mode, self.target_edit, self.cycle_frequency, self.cycle_start, self.cycle_end):
            widget.setMinimumHeight(40)
            widget.setMinimumWidth(0)
        self.countdown_mode.currentIndexChanged.connect(self._countdown_mode_changed)
        self.cycle_frequency.currentIndexChanged.connect(self._countdown_mode_changed)
        layout.addWidget(card)
        layout.addStretch()
        self._countdown_mode_changed()
        return self._scroll_page(page)

    def _countdown_mode_changed(self):
        cyclic = self.countdown_mode.currentData() == "cyclic"
        self.standard_fields.setVisible(not cyclic)
        self.cycle_fields.setVisible(cyclic)
        self.cycle_days_widget.setVisible(self.cycle_frequency.currentData() == "weekly")
        self.countdown_feedback.setText(
            "时段开始前等待，结束时提醒一次，再等待下一轮。结束早于开始时按跨天计算。"
            if cyclic else "到期后提醒一次并停止；关闭到托盘后仍可提醒。")


    def _refresh_countdown_lists(self):
        for widget in (self.countdown_list, self.settings_countdown_list):
            widget.blockSignals(True)
            widget.clear()
            for countdown in self.countdowns:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, countdown["id"])
                widget.addItem(item)
            self._select_list_id(widget, self.active_countdown_id)
            widget.blockSignals(False)
        self._render_countdown_lists(datetime.now())

    def _render_countdown_lists(self, now):
        snapshots = [countdown_snapshot(c, now) for c in self.countdowns]
        running = sum(s["state"] == "running" for s in snapshots)
        waiting = sum(s["state"] == "waiting" for s in snapshots)
        ended = len(snapshots) - running - waiting
        self.settings_summary.setText(f"共 {len(snapshots)} 个倒计时 · {running} 个进行中 · {waiting} 个待开始 · {ended} 个已结束")
        for widget in (self.countdown_list, self.settings_countdown_list):
            for row, countdown in enumerate(self.countdowns):
                if row >= widget.count():
                    break
                snapshot = snapshots[row]
                text = countdown["title"] + "\n" + snapshot["hint"] + " · " + snapshot["text"]
                widget.item(row).setText(text)
                widget.item(row).setToolTip(text)

    def _countdown_selected(self, current, previous=None):
        if not current:
            return
        self.active_countdown_id = current.data(Qt.ItemDataRole.UserRole)
        item = next(c for c in self.countdowns if c["id"] == self.active_countdown_id)
        self.countdown_name.setText(item["title"])
        self.target_edit.setDateTime(QDateTime(datetime.fromisoformat(item["target"])))
        index = self.countdown_mode.findData(item.get("mode", "standard"))
        self.countdown_mode.setCurrentIndex(max(0, index))
        self.cycle_start.setTime(QTime.fromString(item.get("cycle_start", "09:30"), "HH:mm"))
        self.cycle_end.setTime(QTime.fromString(item.get("cycle_end", "17:30"), "HH:mm"))
        self.cycle_frequency.setCurrentIndex(max(0, self.cycle_frequency.findData(item.get("frequency", "daily"))))
        for i, check in enumerate(self.cycle_weekday_checks):
            check.setChecked(i in item.get("cycle_weekdays", [0, 1, 2, 3, 4]))
        self.countdown_form_title.setText("编辑倒计时")
        self.save_countdown_button.setText("保存修改")
        self.delete_countdown_button.setEnabled(True)
        self.countdown_feedback.setText("修改后点击保存生效。")

    def new_countdown(self):
        self.active_countdown_id = None
        self.countdown_list.setCurrentRow(-1)
        self.countdown_name.clear()
        self.target_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.countdown_mode.setCurrentIndex(0)
        self.cycle_start.setTime(QTime(9, 30))
        self.cycle_end.setTime(QTime(17, 30))
        self.cycle_frequency.setCurrentIndex(0)
        for i, check in enumerate(self.cycle_weekday_checks):
            check.setChecked(i < 5)
        self.countdown_form_title.setText("新建倒计时")
        self.save_countdown_button.setText("添加倒计时")
        self.delete_countdown_button.setEnabled(False)
        self.countdown_feedback.setText("填写名称和目标时间后添加。")
        self.countdown_name.setFocus()

    def save_target(self) -> None:
        existing = next((c for c in self.countdowns if c["id"] == self.active_countdown_id), None)
        schedule = {
            "cycle_start": self.cycle_start.time().toString("HH:mm"),
            "cycle_end": self.cycle_end.time().toString("HH:mm"),
            "frequency": self.cycle_frequency.currentData(),
            "cycle_weekdays": [i for i, check in enumerate(self.cycle_weekday_checks) if check.isChecked()]
                if self.cycle_frequency.currentData() == "weekly" else [],
        }
        try:
            item = prepare_countdown(existing, self.countdown_name.text(),
                                     self.countdown_mode.currentData(), self.target_edit.dateTime().toPyDateTime(),
                                     schedule, datetime.now())
        except ValueError as error:
            self.countdown_feedback.setText(str(error))
            return
        if existing is None:
            self.countdowns.append(item)
        else:
            existing.clear()
            existing.update(item)
        self.active_countdown_id = item["id"]
        self.store.write_json("countdowns", self.countdowns)
        self._refresh_countdown_lists()
        self._countdown_selected(self.countdown_list.currentItem())
        self.countdown_feedback.setText("已保存，可在概览查看独立倒计时组件。")
        self._rebuild_dashboard()
        self._refresh_widget_settings()


    def delete_countdown(self):
        if not self.active_countdown_id:
            return
        index = next(i for i, c in enumerate(self.countdowns) if c["id"] == self.active_countdown_id)
        self.deleted_countdown = (index, self.countdowns[index], self.widget_config.get("countdown:" + self.active_countdown_id, {}).copy())
        self.countdowns = [c for c in self.countdowns if c["id"] != self.active_countdown_id]
        self.widget_config.pop("countdown:" + self.active_countdown_id, None)
        self.store.write_json("countdowns", self.countdowns)
        self.store.write_json("widgets", self.widget_config)
        self.new_countdown()
        self._refresh_countdown_lists()
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.countdown_feedback.setText("倒计时已删除。")
        self.undo_countdown_button.show()

    def undo_delete_countdown(self):
        if not self.deleted_countdown:
            return
        index, item, config = self.deleted_countdown
        self.countdowns.insert(index, item)
        self.widget_config["countdown:" + item["id"]] = config
        self.store.write_json("countdowns", self.countdowns)
        self.store.write_json("widgets", self.widget_config)
        self.active_countdown_id = item["id"]
        self._refresh_countdown_lists()
        self._countdown_selected(self.countdown_list.currentItem())
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.deleted_countdown = None
        self.undo_countdown_button.hide()
        self.countdown_feedback.setText("已恢复删除的倒计时。")

    def _update_countdown(self, now=None) -> None:
        now = now or datetime.now()
        due = collect_due(self.countdowns, now)
        if due:
            self.store.write_json("countdowns", self.countdowns)
            self.notify("倒计时结束：" + "、".join(due))
        self._render_countdown_lists(now)


