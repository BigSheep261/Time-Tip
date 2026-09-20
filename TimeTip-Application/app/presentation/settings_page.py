"""Settings, data transfer and module controls; legacy page adapter."""
from __future__ import annotations

import sys
from datetime import datetime

from PyQt6.QtCore import QTime, Qt, QTimer
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout, QGridLayout, QLabel, QListWidget, QMessageBox, QPushButton, QProgressBar, QTimeEdit, QVBoxLayout, QWidget

from app.domain.salary import DEFAULT_SALARY, salary_snapshot, validate_salary
from app.domain.layout import WIDGET_SIZES
from app.domain.dates import format_dashboard_date, DATE_FORMATS
from app.presentation.widgets import Card
from app.infrastructure import startup
from app.infrastructure.updater import Updater
from app.version import DISPLAY_VERSION
from app.presentation.theme import available_themes, set_feedback_state


class SettingsPageMixin:
    def save_theme(self) -> None:
        if hasattr(self, "theme_combo") and self.theme_combo.currentData():
            self.set_theme(self.theme_combo.currentData())

    def refresh_theme_options(self) -> None:
        """Refresh settings after an extension registers a new theme at runtime."""
        if not hasattr(self, "theme_combo"):
            return
        current = self.theme.id
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        for theme in available_themes():
            self.theme_combo.addItem(theme.label, theme.id)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(current)))
        self.theme_combo.blockSignals(False)
        self.theme_description.setText(self.theme.description)

    def save_date_format(self):
        if not hasattr(self, "date_format_combo"):
            return
        self.date_format = self.date_format_combo.currentData() or "full_cn"
        self.store.set("date_format", self.date_format)
        if hasattr(self, "day_label"):
            self.day_label.setText(format_dashboard_date(datetime.now(), self.date_format))

    def export_data(self):
        if not self.save_memo():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 TimeTip 数据", "TimeTip-backup.zip", "TimeTip 数据包 (*.zip);;JSON 文件 (*.json)")
        if not path: return
        try:
            self.store.export_data(path); self.data_transfer_feedback.setText("数据已导出：" + path)
        except (OSError, ValueError) as error: self.data_transfer_feedback.setText("导出失败：" + str(error))

    def import_data(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 TimeTip 数据", "", "TimeTip 数据包 (*.zip *.json);;所有文件 (*.*)")
        if not path: return
        if not self.save_memo():
            return
        try:
            self.store.import_data(path)
            self._jm_load_favorites()
            self.countdowns = self.store.load_collection("countdowns"); self.memos = self.store.load_collection("memos"); self.anime = self.store.anime()
            saved_salary = self.store.read_json("salary", {}); self.salary_config = {**DEFAULT_SALARY, **saved_salary} if isinstance(saved_salary, dict) else DEFAULT_SALARY.copy()
            self._load_settings()
            module_errors = self.modules.reload_preferences()
            self._modules_changed()
            self.modules.publish("data.reloaded")
            self.data_transfer_feedback.setText("数据已导入，界面已刷新。")
            self.module_feedback.setText("\n".join(module_errors))
        except (OSError, ValueError, TypeError) as error: self.data_transfer_feedback.setText("导入失败：" + str(error))

    def check_for_updates(self) -> None:
        if not hasattr(self, "update_feedback"):
            return
        self.update_feedback.setText("正在检查更新…")
        set_feedback_state(self.update_feedback, "info")
        self.updater.check()

    def _on_update_available(self, metadata: dict) -> None:
        version = str(metadata.get("version", "")).lstrip("vV").strip()
        notes = str(metadata.get("release_notes", "暂无更新说明。")).strip() or "暂无更新说明。"
        source = str(metadata.get("source_label", metadata.get("source", "未知来源")))
        source_ip = str(metadata.get("source_ip", self.updater.metadata_url.split("/")[2] if "/" in self.updater.metadata_url else "未知"))
        client_ip = str(metadata.get("client_ip", "未知"))
        self.update_source.setText(f"更新源 IP：{source_ip} · 客户端 IP：{client_ip} · 安装包来源：{source}")
        self.update_feedback.setText(f"发现新版本 V{version}，已确认更新源可用。")
        set_feedback_state(self.update_feedback, "success")
        answer = QMessageBox.question(
            self,
            "TimeTip 更新",
            f"发现新版本 V{version}。\n\n{notes}\n\n现在下载并安装吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.update_progress.setVisible(True)
            self.update_progress.setValue(0)
            self.update_download_button.setEnabled(False)
            self.updater.download()

    def _on_no_update(self, metadata: dict) -> None:
        source = str(metadata.get("source_label", metadata.get("source", "未知来源")))
        source_ip = str(metadata.get("source_ip", "未知"))
        client_ip = str(metadata.get("client_ip", "未知"))
        self.update_source.setText(f"更新源 IP：{source_ip} · 客户端 IP：{client_ip} · 安装包来源：{source}")
        self.update_feedback.setText(f"当前已是最新版本 {DISPLAY_VERSION}。")
        set_feedback_state(self.update_feedback, "success")

    def _on_update_progress(self, received: int, total: int) -> None:
        self.update_progress.setVisible(True)
        if total > 0:
            self.update_progress.setRange(0, 100)
            self.update_progress.setValue(min(100, int(received * 100 / total)))
            self.update_feedback.setText(f"正在下载更新… {received / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB")
        else:
            self.update_progress.setRange(0, 0)
            self.update_feedback.setText(f"正在下载更新… {received / 1024 / 1024:.1f} MB")

    def _on_update_downloaded(self, path: str) -> None:
        try:
            Updater.launch_installer(path)
            self.update_progress.setVisible(False)
            self.update_download_button.setEnabled(True)
            self.update_feedback.setText("安装器已启动，下载成功，TimeTip 将退出并完成更新。")
            QTimer.singleShot(300, self.quit_app)
        except OSError as error:
            self._on_update_failed(str(error))

    def _on_update_failed(self, message: str) -> None:
        if hasattr(self, "update_progress"):
            self.update_progress.setVisible(False)
        if hasattr(self, "update_download_button"):
            self.update_download_button.setEnabled(True)
        if hasattr(self, "update_feedback"):
            set_feedback_state(self.update_feedback, "error")
            self.update_feedback.setText("更新失败：" + message)

    def _save_update_auto_check(self, enabled: bool) -> None:
        self.store.set("update_auto_check", "1" if enabled else "0")

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(16)
        self._page_header(layout, "设置", "管理你的时间、工资计算方式与概览布局。所有设置仅保存在本机。")
        date_card = Card()
        date_row = QHBoxLayout(date_card)
        date_row.setContentsMargins(20, 14, 20, 14)
        date_row.addWidget(QLabel("概览日期格式", objectName="cardTitle"))
        self.date_format_combo = QComboBox()
        for key, example in DATE_FORMATS:
            self.date_format_combo.addItem(example, key)
        self.date_format_combo.currentIndexChanged.connect(self.save_date_format)
        date_row.addWidget(self.date_format_combo, 1)
        layout.addWidget(date_card)
        module_card = Card()
        module_layout = QVBoxLayout(module_card)
        module_layout.setContentsMargins(20, 14, 20, 14)
        module_layout.addWidget(QLabel("功能模块", objectName="cardTitle"))
        note = QLabel("关闭功能会隐藏入口并停止对应后台活动，已有数据会保留。重新勾选即可启用。", objectName="cardHint")
        note.setWordWrap(True)
        module_layout.addWidget(note)
        self.module_settings_layout = QVBoxLayout()
        module_layout.addLayout(self.module_settings_layout)
        self.module_feedback = QLabel("", objectName="cardHint")
        self.module_feedback.setWordWrap(True)
        module_layout.addWidget(self.module_feedback)
        layout.addWidget(module_card)
        theme_card = Card()
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(20, 14, 20, 14)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("界面主题", objectName="cardTitle"))
        self.theme_combo = QComboBox()
        self.theme_combo.setAccessibleName("界面主题")
        self.theme_combo.currentIndexChanged.connect(self.save_theme)
        theme_row.addWidget(self.theme_combo, 1)
        theme_layout.addLayout(theme_row)
        self.theme_description = QLabel("", objectName="cardHint")
        self.theme_description.setWordWrap(True)
        theme_layout.addWidget(self.theme_description)
        layout.addWidget(theme_card)
        self.refresh_theme_options()
        self.jm_unlock_button = QPushButton("里模式", objectName="primaryButton")
        self.jm_unlock_button.clicked.connect(self._unlock_jm_mode)
        startup_card = Card()
        startup_layout = QVBoxLayout(startup_card)
        startup_layout.setContentsMargins(20, 14, 20, 14)
        startup_row = QHBoxLayout()
        self.startup_check = QCheckBox("开机自动启动 TimeTip")
        self.startup_check.setAccessibleName("开机自启")
        self.startup_check.toggled.connect(self._toggle_startup)
        startup_row.addWidget(self.startup_check)
        startup_row.addStretch()
        startup_layout.addLayout(startup_row)
        self.startup_feedback = QLabel("登录 Windows 后自动打开 TimeTip。", objectName="cardHint")
        self.startup_feedback.setWordWrap(True)
        startup_layout.addWidget(self.startup_feedback)
        layout.addWidget(startup_card)
        update_card = Card()
        update_layout = QVBoxLayout(update_card)
        update_layout.setContentsMargins(20, 14, 20, 14)
        update_row = QHBoxLayout()
        update_row.addWidget(QLabel("软件更新", objectName="cardTitle"))
        self.update_download_button = QPushButton("检查更新", objectName="secondaryButton")
        self.update_download_button.clicked.connect(self.check_for_updates)
        update_row.addWidget(self.update_download_button)
        self.update_auto_check = QCheckBox("启动时自动检查更新")
        self.update_auto_check.setAccessibleName("自动检查更新")
        self.update_auto_check.toggled.connect(self._save_update_auto_check)
        update_row.addWidget(self.update_auto_check)
        update_layout.addLayout(update_row)
        self.update_feedback = QLabel("点击“检查更新”获取最新版本信息。", objectName="cardHint")
        self.update_feedback.setWordWrap(True)
        update_layout.addWidget(self.update_feedback)
        self.update_source = QLabel("更新源 IP：尚未检查 · 安装包来源：尚未确认", objectName="cardHint")
        self.update_source.setWordWrap(True)
        update_layout.addWidget(self.update_source)
        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setVisible(False)
        update_layout.addWidget(self.update_progress)
        layout.addWidget(update_card)
        transfer_card = Card()
        transfer_row = QHBoxLayout(transfer_card); transfer_row.setContentsMargins(20, 14, 20, 14)
        transfer_row.addWidget(QLabel("数据备份", objectName="cardTitle"))
        export_button = QPushButton("导出数据", objectName="secondaryButton"); export_button.clicked.connect(self.export_data); transfer_row.addWidget(export_button)
        import_button = QPushButton("导入数据", objectName="secondaryButton"); import_button.clicked.connect(self.import_data); transfer_row.addWidget(import_button)
        self.data_transfer_feedback = QLabel("SQLite 数据库位于安装目录的 data 文件夹。", objectName="cardHint"); transfer_row.addWidget(self.data_transfer_feedback, 1)
        layout.addWidget(transfer_card)
        summary = Card()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(20, 18, 20, 18)
        row = QHBoxLayout()
        row.addWidget(QLabel("倒计时总览", objectName="cardTitle"), 1)
        manage = QPushButton("管理倒计时  →", objectName="secondaryButton")
        manage.clicked.connect(lambda: self.modules.navigate("countdowns"))
        row.addWidget(manage)
        summary_layout.addLayout(row)
        self.settings_summary = QLabel("", objectName="cardHint")
        summary_layout.addWidget(self.settings_summary)
        self.settings_countdown_list = QListWidget(objectName="cleanList")
        self.settings_countdown_list.setMinimumHeight(100)
        self.settings_countdown_list.setMaximumHeight(200)
        self.settings_countdown_list.itemDoubleClicked.connect(lambda item: self._open_widget("countdown:" + item.data(Qt.ItemDataRole.UserRole)))
        summary_layout.addWidget(self.settings_countdown_list)
        layout.addWidget(summary)
        salary = Card()
        form = QVBoxLayout(salary)
        form.setContentsMargins(20, 18, 20, 18)
        form.setSpacing(12)
        form.addWidget(QLabel("每日工资", objectName="cardTitle"))
        note = QLabel("月薪 ÷ 当月所选工作日数 = 每日工资；按有效工作秒数累计。午休、下班和休息日不增长。", objectName="cardHint")
        note.setWordWrap(True)
        form.addWidget(note)
        fields = QGridLayout()
        fields.setHorizontalSpacing(16)
        fields.setVerticalSpacing(8)
        self.monthly_salary = QDoubleSpinBox()
        self.monthly_salary.setRange(0, 100000000)
        self.monthly_salary.setDecimals(2)
        self.monthly_salary.setGroupSeparatorShown(True)
        self.monthly_salary.setPrefix("¥ ")
        self.monthly_salary.setSingleStep(1000)
        self.shift_start = QTimeEdit(QTime(9, 0))
        self.shift_end = QTimeEdit(QTime(18, 0))
        for edit in (self.shift_start, self.shift_end):
            edit.setDisplayFormat("HH:mm")
        for col, (title, widget) in enumerate([("月薪（元）", self.monthly_salary), ("上班时间", self.shift_start), ("下班时间", self.shift_end)]):
            label = QLabel(title, objectName="fieldLabel")
            label.setBuddy(widget)
            fields.addWidget(label, 0, col)
            fields.addWidget(widget, 1, col)
            fields.setColumnStretch(col, 1)
        form.addLayout(fields)
        form.addWidget(QLabel("每周工作日", objectName="fieldLabel"))
        weekdays = QHBoxLayout()
        self.weekday_checks = []
        for index, title in enumerate(["周一", "周二", "周三", "周四", "周五", "周六", "周日"]):
            check = QCheckBox(title)
            check.setChecked(index < 5)
            weekdays.addWidget(check)
            self.weekday_checks.append(check)
        weekdays.addStretch()
        form.addLayout(weekdays)
        pause_row = QHBoxLayout()
        self.salary_break_check = QCheckBox("扣除午休 / 休息时间")
        self.salary_break_check.setChecked(True)
        pause_row.addWidget(self.salary_break_check)
        self.salary_break_start = QTimeEdit(QTime(12, 0))
        self.salary_break_end = QTimeEdit(QTime(13, 0))
        for edit in (self.salary_break_start, self.salary_break_end):
            edit.setDisplayFormat("HH:mm")
            self.salary_break_check.toggled.connect(edit.setEnabled)
        pause_row.addWidget(self.salary_break_start)
        pause_row.addWidget(QLabel("至"))
        pause_row.addWidget(self.salary_break_end)
        pause_row.addStretch()
        form.addLayout(pause_row)
        hint = QLabel("支持跨午夜班次，工资归属上班日期。工作日按星期计算，法定节假日及调休暂不自动识别。", objectName="cardHint")
        hint.setWordWrap(True)
        form.addWidget(hint)
        self.salary_feedback = QLabel("填写后保存，即可在概览查看实时工资。", objectName="cardHint")
        self.salary_feedback.setWordWrap(True)
        form.addWidget(self.salary_feedback)
        save = QPushButton("保存工资设置", objectName="primaryButton")
        save.clicked.connect(self.save_salary_settings)
        form.addWidget(save, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(salary)
        widget_card = Card()
        widget_layout = QVBoxLayout(widget_card)
        widget_layout.setContentsMargins(20, 18, 20, 18)
        widget_layout.setSpacing(12)
        widget_layout.addWidget(QLabel("概览组件", objectName="cardTitle"))
        hint = QLabel("勾选要显示的组件，并选择宽 × 高。宽窗口使用 4 列，窄窗口自动收为 2 列；布局自动保存。", objectName="cardHint")
        hint.setWordWrap(True)
        widget_layout.addWidget(hint)
        self.widget_settings_container = QWidget()
        self.widget_settings_layout = QVBoxLayout(self.widget_settings_container)
        self.widget_settings_layout.setContentsMargins(0, 0, 0, 0)
        widget_layout.addWidget(self.widget_settings_container)
        layout.addWidget(widget_card)
        layout.addWidget(self.jm_unlock_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch()
        return self._scroll_page(page)

    def _toggle_startup(self, enabled: bool) -> bool:
        try:
            startup.set_startup_enabled(enabled)
        except startup.StartupError as error:
            self.startup_check.blockSignals(True)
            self.startup_check.setChecked(not enabled)
            self.startup_check.blockSignals(False)
            set_feedback_state(self.startup_feedback, "error")
            self.startup_feedback.setText(str(error))
            return False
        set_feedback_state(self.startup_feedback, "success")
        self.startup_feedback.setText("已开启：登录 Windows 后自动启动。" if enabled else "已关闭开机自启。")
        return True

    def _refresh_widget_settings(self):
        while self.widget_settings_layout.count():
            child = self.widget_settings_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        for key, title, size, tone in self._ordered_specs():
            state = self._widget_state(key, size)
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(title[:35] + ("…" if len(title) > 35 else ""))
            check.setToolTip(title)
            check.setChecked(bool(state["visible"]))
            check.toggled.connect(lambda value, k=key: self._change_widget(k, "visible", value))
            line.addWidget(check, 1)
            combo = QComboBox()
            combo.setAccessibleName(title + "组件大小")
            for size in WIDGET_SIZES:
                combo.addItem(f"{size[0]} × {size[1]}", size)
            combo.setCurrentIndex(WIDGET_SIZES.index(tuple(state["size"])))
            combo.currentIndexChanged.connect(lambda index, k=key: self._change_widget(k, "size", WIDGET_SIZES[index]))
            line.addWidget(combo)
            self.widget_settings_layout.addWidget(row)

    def save_salary_settings(self):
        config = {"monthly": self.monthly_salary.value(), "start": self.shift_start.time().toString("HH:mm"),
                  "end": self.shift_end.time().toString("HH:mm"), "weekdays": [i for i, c in enumerate(self.weekday_checks) if c.isChecked()],
                  "break_enabled": self.salary_break_check.isChecked(), "break_start": self.salary_break_start.time().toString("HH:mm"),
                  "break_end": self.salary_break_end.time().toString("HH:mm")}
        try:
            validate_salary(config)
        except ValueError as error:
            set_feedback_state(self.salary_feedback, "error")
            self.salary_feedback.setText(str(error))
            return False
        self.salary_config = config
        self.store.write_json("salary", config)
        result = salary_snapshot(config, datetime.now())
        set_feedback_state(self.salary_feedback, "success")
        self.salary_feedback.setText(f"已保存 · 本月 {result['workdays']} 个工作日 · 每日 ¥ {result['daily']:,.2f} · 每秒 ¥ {result['per_second']:.4f}")
        self._render_dashboard(datetime.now())
        return True

    def _load_settings(self) -> None:
        self.set_theme(self.store.get("theme", self.theme.id))
        for key, spin, default in [("work", self.work_spin, 25), ("break", self.break_spin, 5)]:
            try:
                spin.setValue(int(self.store.get(key, str(default))))
            except ValueError:
                spin.setValue(default)
        self.pomodoro_remaining = self.work_spin.value() * 60
        config = self.salary_config
        self.monthly_salary.setValue(float(config["monthly"]))
        self.shift_start.setTime(QTime.fromString(config["start"], "HH:mm"))
        self.shift_end.setTime(QTime.fromString(config["end"], "HH:mm"))
        self.salary_break_check.setChecked(config["break_enabled"])
        self.salary_break_start.setTime(QTime.fromString(config["break_start"], "HH:mm"))
        self.salary_break_end.setTime(QTime.fromString(config["break_end"], "HH:mm"))
        for index, check in enumerate(self.weekday_checks):
            check.setChecked(index in config["weekdays"])
        self.date_format = self.store.get("date_format", "full_cn")
        self.date_format_combo.setCurrentIndex(max(0, self.date_format_combo.findData(self.date_format)))
        self.startup_check.blockSignals(True)
        self.startup_check.setChecked(startup.is_startup_enabled())
        self.startup_check.blockSignals(False)
        auto_check = self.store.get("update_auto_check", "1") == "1"
        self.update_auto_check.blockSignals(True)
        self.update_auto_check.setChecked(auto_check)
        self.update_auto_check.blockSignals(False)
        if auto_check and getattr(sys, "frozen", False):
            QTimer.singleShot(1200, self.check_for_updates)
        self._refresh_countdown_lists()
        self._refresh_anime_list()
        self._refresh_memo_list(self.memos[0]["id"] if self.memos else None)
        self._calendar_selected(self.calendar.selectedDate())
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self._update_summary()
        self._render_focus_time()

    def _refresh_module_settings(self):
        while self.module_settings_layout.count():
            item = self.module_settings_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.module_checks = {}
        for key, entry in self.modules.entries.items():
            if not entry.spec.manageable:
                continue
            check = QCheckBox(entry.spec.title + ("（基础模块）" if entry.spec.required else ""))
            check.setChecked(entry.enabled)
            check.setEnabled(not entry.spec.required)
            check.toggled.connect(lambda value, module_id=key: self._set_module_enabled(module_id, value))
            self.module_settings_layout.addWidget(check)
            self.module_checks[key] = check

    def _set_module_enabled(self, module_id, enabled):
        operation = self.modules.enable if enabled else self.modules.disable
        if operation(module_id):
            self.module_feedback.setText("已启用。" if enabled else "已停用，数据已保留。")
        else:
            self.module_feedback.setText(self.modules.last_error)
        self._refresh_module_settings()
