"""Calendar reminders and date annotations; legacy page adapter."""
from __future__ import annotations

import uuid
from datetime import datetime

from PyQt6.QtCore import QDate, QTime, Qt
from PyQt6.QtGui import QColor, QFont, QTextCharFormat
from PyQt6.QtWidgets import QBoxLayout, QCalendarWidget, QComboBox, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTimeEdit, QVBoxLayout, QWidget

from app.domain.anime import anime_for_date, episode_label, episode_dates
from app.presentation.widgets import Card


class CalendarPageMixin:
    def _calendar_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        title = QLabel("日历提醒")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        sub = QLabel("选中日期，添加只属于你的提醒。")
        sub.setObjectName("pageSubtitle")
        layout.addWidget(sub)
        content = QVBoxLayout()
        self.calendar_content_layout = content
        content.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 1100 else QBoxLayout.Direction.TopToBottom)
        content.setSpacing(14)
        cal_card = Card()
        cal_layout = QVBoxLayout(cal_card)
        cal_layout.setContentsMargins(14, 14, 14, 14)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.selectionChanged.connect(lambda: self._calendar_selected(self.calendar.selectedDate()))
        cal_layout.addWidget(self.calendar)
        content.addWidget(cal_card, 3)
        form = Card()
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(18, 18, 18, 18)
        self.selected_date_label = QLabel("")
        self.selected_date_label.setObjectName("cardTitle")
        form_layout.addWidget(self.selected_date_label)
        field_label = QLabel("提醒内容")
        field_label.setObjectName("fieldLabel")
        form_layout.addWidget(field_label)
        self.reminder_input = QLineEdit()
        self.reminder_input.setPlaceholderText("例如：给妈妈打电话")
        self.reminder_input.setMinimumHeight(42)
        form_layout.addWidget(self.reminder_input)
        form_layout.addWidget(QLabel("提醒时间（电脑本地时间）", objectName="fieldLabel"))
        self.reminder_time = QTimeEdit(QTime(9, 0))
        self.reminder_time.setDisplayFormat("HH:mm")
        self.reminder_time.setMinimumHeight(38)
        form_layout.addWidget(self.reminder_time)
        form_layout.addWidget(QLabel("提醒模式", objectName="fieldLabel"))
        self.reminder_mode = QComboBox()
        self.reminder_mode.addItem("需要电脑提醒", "notify")
        self.reminder_mode.addItem("仅在日历显示", "calendar")
        self.reminder_mode.setMinimumHeight(38)
        form_layout.addWidget(self.reminder_mode)
        add = QPushButton("添加提醒")
        add.setObjectName("primaryButton")
        add.setMinimumHeight(42)
        add.clicked.connect(self.add_reminder)
        form_layout.addWidget(add)
        form_layout.addSpacing(12)
        list_label = QLabel("已有提醒")
        list_label.setObjectName("fieldLabel")
        form_layout.addWidget(list_label)
        self.reminder_list = QListWidget()
        self.reminder_list.setWordWrap(True)
        self.reminder_list.setObjectName("cleanList")
        form_layout.addWidget(self.reminder_list, 1)
        remove = QPushButton("删除选中提醒")
        remove.setObjectName("secondaryButton")
        remove.clicked.connect(self.remove_reminder)
        form_layout.addWidget(remove)
        content.addWidget(form, 2)
        layout.addLayout(content, 1)
        return page

    def _calendar_selected(self, date: QDate) -> None:
        self.selected_date_label.setText(date.toString("yyyy年MM月dd日"))
        self.reminder_list.clear()
        key = date.toString("yyyy-MM-dd")
        for anime in anime_for_date(self.anime if self.feature_enabled("anime") else [], date.toPyDate()):
            item = QListWidgetItem("番剧 · " + anime["title"] + "  ·  " + episode_label(anime))
            item.setToolTip((anime.get("folder") or "未关联本地文件夹") + "\n仅在日历显示，不会主动提醒")
            item.setData(Qt.ItemDataRole.UserRole, {"kind": "anime", "id": anime["id"]})
            self.reminder_list.addItem(item)
        for reminder in self.store.reminders():
            if reminder.get("date") == key:
                mode = reminder.get("mode", "notify")
                state = " · 已提醒" if reminder.get("notified") else ""
                label = "电脑提醒" if mode == "notify" else "仅日历"
                item = QListWidgetItem(reminder.get("time", "09:00") + "  " + reminder.get("text", "") +
                                       f" · {label}" + state)
                item.setData(Qt.ItemDataRole.UserRole, reminder)
                self.reminder_list.addItem(item)

    def add_reminder(self) -> None:
        text = self.reminder_input.text().strip()
        if not text:
            self.reminder_input.setFocus()
            return
        key = self.calendar.selectedDate().toString("yyyy-MM-dd")
        items = self.store.reminders()
        items.append({"id": uuid.uuid4().hex, "date": key, "time": self.reminder_time.time().toString("HH:mm"), "text": text, "mode": self.reminder_mode.currentData(), "notified": False})
        self.store.save_reminders(items)
        self.reminder_input.clear()
        self._calendar_selected(self.calendar.selectedDate())
        self._update_summary()

    def remove_reminder(self) -> None:
        current = self.reminder_list.currentItem()
        if not current:
            return
        target = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(target, dict) and target.get("kind") == "anime":
            return
        items = self.store.reminders()
        items.remove(target)
        self.store.save_reminders(items)
        self._calendar_selected(self.calendar.selectedDate())
        self._update_summary()

    def _check_reminders(self, now: datetime) -> None:
        items = self.store.reminders()
        due = []
        for reminder in items:
            try:
                scheduled = datetime.fromisoformat(reminder["date"] + "T" + reminder.get("time", "09:00"))
            except (ValueError, TypeError):
                continue
            if reminder.get("mode", "notify") != "notify":
                continue
            if scheduled <= now and not reminder.get("notified"):
                due.append(reminder["text"])
                reminder["notified"] = now.isoformat()
        if due:
            self.store.save_reminders(items)
            self.notify("日历提醒：" + "、".join(due))
            self._calendar_selected(self.calendar.selectedDate())

    def _refresh_calendar_marks(self):
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        for reminder in self.store.reminders():
            date = QDate.fromString(reminder["date"], "yyyy-MM-dd")
            if date.isValid():
                style = QTextCharFormat()
                style.setForeground(QColor(self.theme.colors["primary"]))
                style.setFontWeight(QFont.Weight.Bold)
                style.setToolTip("有日历提醒")
                self.calendar.setDateTextFormat(date, style)
        for anime in (self.anime if self.feature_enabled("anime") else []):
            try:
                schedule = episode_dates(anime)
            except ValueError:
                schedule = []
            for day in schedule:
                qday = QDate(day.year, day.month, day.day)
                style = QTextCharFormat()
                style.setForeground(QColor(self.theme.colors["warning"]))
                style.setFontWeight(QFont.Weight.Bold)
                style.setToolTip("有番剧更新：" + anime["title"])
                self.calendar.setDateTextFormat(qday, style)

