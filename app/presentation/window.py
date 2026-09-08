from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from PyQt6.QtCore import QByteArray, QDate, QPoint, QTime, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QSystemTrayIcon,
)

from app.domain.salary import DEFAULT_SALARY, salary_snapshot, validate_salary
from app.domain.layout import WIDGET_SIZES
from app.domain.countdowns import countdown_snapshot
from app.presentation.countdowns import CountdownPageMixin
from app.presentation.widgets import Card, DashboardTile, ResizeHandle, WidgetGrid
from app.infrastructure.store import Store
from app.presentation.theme import APP_NAME, PRIMARY


def make_app_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(PRIMARY))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 18, 18)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Arial", 25, QFont.Weight.Bold))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "T")
    painter.end()
    return QIcon(pix)


class TitleBar(QFrame):
    moved = pyqtSignal(QPoint)

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self._drag_pos: QPoint | None = None
        self.setFixedHeight(62)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 18, 8)
        layout.setSpacing(10)
        logo = QLabel("T")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(34, 34)
        layout.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        subtitle = QLabel("你的节奏，由你掌握")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch()
        for text, tip, slot in [("—", "最小化", window.showMinimized), ("□", "最大化 / 还原", window.toggle_maximized), ("×", "关闭到托盘", window.close)]:
            button = QPushButton(text)
            button.setObjectName("windowButton")
            button.setToolTip(tip)
            button.setAccessibleName(tip)
            button.setFixedSize(34, 34)
            button.clicked.connect(slot)
            layout.addWidget(button)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window.windowHandle() and self.window.windowHandle().startSystemMove():
                return
            self._drag_pos = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.toggle_maximized()


class TimeTipWindow(CountdownPageMixin, QMainWindow):
    def __init__(self, store: Store | None = None) -> None:
        super().__init__()
        self.store = store or Store()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.setMinimumSize(860, 620)
        self.resize(1220, 830)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.last_reminder_check = set()
        self.pomodoro_running = False
        self.pomodoro_mode = "work"
        self.pomodoro_remaining = 25 * 60
        self.pomodoro_deadline = None
        self.store.migrate_collections()
        self.countdowns = self.store.load_collection("countdowns")
        self.memos = self.store.load_collection("memos")
        self.active_countdown_id = None
        self.active_memo_id = None
        self.deleted_countdown = None
        self.deleted_memo = None
        self.widget_config = self.store.read_json("widgets", {})
        if not isinstance(self.widget_config, dict):
            self.widget_config = {}
        self.tiles = {}
        saved_salary = self.store.read_json("salary", {})
        self.salary_config = {**DEFAULT_SALARY, **saved_salary} if isinstance(saved_salary, dict) else DEFAULT_SALARY.copy()
        try:
            validate_salary(self.salary_config)
        except (ValueError, TypeError, KeyError):
            self.salary_config = DEFAULT_SALARY.copy()
        self.quitting = False
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction("显示 TimeTip", self.restore_window)
        menu.addAction("退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.restore_window() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

        self._build_ui()
        self._load_settings()
        self._setup_resize()
        self._start_timers()
        self._tick()

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _setup_resize(self):
        E, C = Qt.Edge, Qt.CursorShape
        specs = [(E.LeftEdge, C.SizeHorCursor), (E.RightEdge, C.SizeHorCursor),
                 (E.TopEdge, C.SizeVerCursor), (E.BottomEdge, C.SizeVerCursor),
                 (E.LeftEdge | E.TopEdge, C.SizeFDiagCursor), (E.RightEdge | E.TopEdge, C.SizeBDiagCursor),
                 (E.LeftEdge | E.BottomEdge, C.SizeBDiagCursor), (E.RightEdge | E.BottomEdge, C.SizeFDiagCursor)]
        self.resize_handles = [ResizeHandle(self, edges, cursor) for edges, cursor in specs]
        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.timeout.connect(self.save_window_geometry)
        geometry = self.store.get("window_geometry")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii", errors="ignore")))
        self._position_handles()

    def _position_handles(self):
        if not hasattr(self, "resize_handles"):
            return
        w, h, edge, corner = self.width(), self.height(), 6, 16
        rects = [(0, corner, edge, h - corner * 2), (w-edge, corner, edge, h-corner*2),
                 (corner, 0, w-corner*2, edge), (corner, h-edge, w-corner*2, edge),
                 (0, 0, corner, corner), (w-corner, 0, corner, corner),
                 (0, h-corner, corner, corner), (w-corner, h-corner, corner, corner)]
        for handle, rect in zip(self.resize_handles, rects):
            handle.setGeometry(*rect)
            handle.setVisible(not self.isMaximized())
            handle.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_handles()
        if hasattr(self, "calendar_content_layout"):
            self.calendar_content_layout.setDirection(QBoxLayout.Direction.LeftToRight if self.width() >= 1100 else QBoxLayout.Direction.TopToBottom)
        if hasattr(self, "geometry_timer"):
            self.geometry_timer.start(500)

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "geometry_timer"):
            self.geometry_timer.start(500)

    def save_window_geometry(self):
        self.store.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))

    def restore_window(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self.quitting = True
        self.save_memo()
        self.save_window_geometry()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        self.save_memo()
        self.save_window_geometry()
        if not self.quitting and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def notify(self, text: str) -> None:
        QApplication.beep()
        if self.tray.isVisible():
            self.tray.showMessage(APP_NAME, text, QSystemTrayIcon.MessageIcon.Information, 7000)
        else:
            box = QMessageBox(QMessageBox.Icon.Information, APP_NAME, text, parent=self)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()
            self.notification_box = box

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(TitleBar(self))

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 0, 18, 18)
        body_layout.setSpacing(14)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(152)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(10, 14, 10, 14)
        side_layout.setSpacing(7)
        side_label = QLabel("工作台")
        side_label.setObjectName("sectionLabel")
        side_layout.addWidget(side_label)
        self.nav_buttons: list[QPushButton] = []
        for index, text in enumerate(["概览", "日历提醒", "番茄钟", "备忘录", "倒计时", "设置"]):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(44)
            button.clicked.connect(lambda _checked, i=index: self._switch_page(i))
            side_layout.addWidget(button)
            self.nav_buttons.append(button)
        side_layout.addStretch()
        hint = QLabel("私人效率工具\n数据仅保存在本机")
        hint.setObjectName("sideHint")
        side_layout.addWidget(hint)
        body_layout.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._dashboard_page())
        self.pages.addWidget(self._scroll_page(self._calendar_page()))
        self.pages.addWidget(self._scroll_page(self._focus_page()))
        self.pages.addWidget(self._memo_page())
        self.pages.addWidget(self._countdowns_page())
        self.pages.addWidget(self._settings_page())
        body_layout.addWidget(self.pages, 1)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self.nav_buttons[0].setChecked(True)

    def _scroll_page(self, page):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        welcome = QVBoxLayout()
        welcome.addWidget(QLabel("概览", objectName="pageTitle"))
        self.day_label = QLabel("", objectName="pageSubtitle")
        welcome.addWidget(self.day_label)
        header.addLayout(welcome, 1)
        add_countdown = QPushButton("＋ 倒计时", objectName="secondaryButton")
        add_countdown.clicked.connect(lambda: (self._switch_page(4), self.new_countdown()))
        header.addWidget(add_countdown)
        self.edit_layout_button = QPushButton("编辑布局", objectName="secondaryButton")
        self.edit_layout_button.setCheckable(True)
        self.edit_layout_button.toggled.connect(self._toggle_layout_editing)
        header.addWidget(self.edit_layout_button)
        layout.addLayout(header)
        self.layout_hint = QLabel("点击组件右上角 ··· 调整大小、顺序或隐藏；隐藏的组件可在设置中恢复。", objectName="pageSubtitle")
        self.layout_hint.setWordWrap(True)
        self.layout_hint.hide()
        layout.addWidget(self.layout_hint)
        self.grid = WidgetGrid()
        self.dashboard_scroll = self._scroll_page(self.grid)
        layout.addWidget(self.dashboard_scroll, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("按你的节奏，安排每一格。", objectName="cardHint"))
        footer.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("拖动调整窗口大小")
        footer.addWidget(self.size_grip)
        layout.addLayout(footer)
        return page

    def _widget_specs(self):
        specs = [("countdown:" + item["id"], item["title"], (2, 2) if i == 0 else (2, 1), "purple") for i, item in enumerate(self.countdowns)]
        specs += [("salary", "今日已赚", (2, 1), "green"), ("clock", "现在", (1, 1), "plain"),
                  ("focus", "番茄钟", (1, 1), "plain"), ("reminders", "日历提醒", (2, 1), "plain")]
        specs += [("memo:" + item["id"], item["title"] or "未命名备忘录", (2, 1), "plain") for item in self.memos]
        return specs

    def _widget_state(self, key, size):
        state = self.widget_config.get(key, {})
        if not isinstance(state, dict):
            state = {}
        if not isinstance(state.get("size"), (list, tuple)) or tuple(state["size"]) not in WIDGET_SIZES:
            state["size"] = list(size)
        state.setdefault("visible", True)
        state.setdefault("order", 10000)
        if not isinstance(state["order"], (float, int)):
            state["order"] = 10000
        self.widget_config[key] = state
        return state

    def _ordered_specs(self):
        specs = self._widget_specs()
        return sorted(specs, key=lambda spec: self._widget_state(spec[0], spec[2])["order"])

    def _rebuild_dashboard(self):
        for tile in self.tiles.values():
            tile.hide()
            tile.deleteLater()
        self.tiles = {}
        for key, title, default_size, tone in self._ordered_specs():
            state = self._widget_state(key, default_size)
            if not state["visible"]:
                continue
            tile = DashboardTile(key, title, tuple(state["size"]), tone)
            tile.changed.connect(self._change_widget)
            tile.opened.connect(self._open_widget)
            tile.set_editing(self.edit_layout_button.isChecked())
            self.tiles[key] = tile
        self.grid.set_tiles(list(self.tiles.values()))
        self._render_dashboard(datetime.now())

    def _toggle_layout_editing(self, editing):
        self.edit_layout_button.setText("完成布局" if editing else "编辑布局")
        self.layout_hint.setVisible(editing)
        for tile in self.tiles.values():
            tile.set_editing(editing)

    def _change_widget(self, key, action, value):
        state = self.widget_config[key]
        if action == "size" and tuple(value) in WIDGET_SIZES:
            state["size"] = list(value)
        elif action == "visible":
            state["visible"] = bool(value)
        elif action == "move":
            keys = [spec[0] for spec in self._ordered_specs()]
            index = keys.index(key)
            target = max(0, min(len(keys) - 1, index + value))
            keys[index], keys[target] = keys[target], keys[index]
            for order, item_key in enumerate(keys):
                self.widget_config[item_key]["order"] = order
        self.store.write_json("widgets", self.widget_config)
        self._rebuild_dashboard()
        self._refresh_widget_settings()

    def _open_widget(self, key):
        if key.startswith("countdown:"):
            self._switch_page(4)
            self._select_list_id(self.countdown_list, key.split(":", 1)[1])
        elif key.startswith("memo:"):
            self._switch_page(3)
            self._select_list_id(self.memo_list, key.split(":", 1)[1])
        else:
            self._switch_page({"salary": 5, "clock": 1, "focus": 2, "reminders": 1}[key])

    def _render_dashboard(self, now):
        for key, tile in self.tiles.items():
            if key == "clock":
                tile.value_label.setText(now.strftime("%H:%M:%S"))
                tile.hint_label.setText(now.strftime("%m月%d日") + " · 星期" + "一二三四五六日"[now.weekday()])
                tile.detail_label.setText("此刻，也是一个新的开始。")
                tile.open_button.setText("查看日历  →")
            elif key == "salary":
                try:
                    result = salary_snapshot(self.salary_config, now)
                    tile.value_label.setText(f"¥ {result['earned']:,.2f}")
                    tile.title_label.setText("今日已赚" if result["day"] == now.date() else result["day"].strftime("%m月%d日班次已赚"))
                    tile.hint_label.setText(result["status"] + " · " + result["detail"])
                    tile.detail_label.setText(f"本班次预计 ¥ {result['daily']:,.2f}\n每秒 ¥ {result['per_second']:.4f} · 本月 {result['workdays']} 个工作日")
                except (ValueError, TypeError, KeyError):
                    tile.value_label.setText("开启工资时钟")
                    tile.hint_label.setText("填写月薪与工作时间")
                    tile.detail_label.setText("看见每一秒的付出。仅在设置的工作时段累计。")
                tile.open_button.setText("工资设置  →")
            elif key == "focus":
                m, sec = divmod(max(0, self.pomodoro_remaining), 60)
                tile.value_label.setText(f"{m:02d}:{sec:02d}")
                tile.hint_label.setText(("专注" if self.pomodoro_mode == "work" else "休息") + ("中" if self.pomodoro_running else " · 待开始"))
                tile.detail_label.setText(f"专注 {self.work_spin.value()} 分钟，休息 {self.break_spin.value()} 分钟。")
                tile.open_button.setText("进入番茄钟  →")
            elif key == "reminders":
                reminders = self.store.reminders()
                pending = [r for r in reminders if not r.get("notified")]
                tile.value_label.setText(f"{len(pending)} 条待提醒")
                next_item = min(pending, key=lambda r: r["date"] + r.get("time", "09:00"), default=None)
                tile.hint_label.setText(next_item["text"] if next_item else "所有安排，心中有数")
                tile.detail_label.setText((next_item["date"] + "  " + next_item.get("time", "09:00")) if next_item else "在日历中添加接下来的安排。")
            elif key.startswith("countdown:"):
                item = next((item for item in self.countdowns if key == "countdown:" + item["id"]), None)
                if item:
                    snapshot = countdown_snapshot(item, now)
                    value = snapshot["text"]
                    if tile.width() < 260:
                        value = value.replace("天 ", "天\n")
                    tile.value_label.setText(value)
                    tile.hint_label.setText(snapshot["hint"])
                    tile.detail_label.setText(snapshot["detail"])
            elif key.startswith("memo:"):
                item = next((item for item in self.memos if key == "memo:" + item["id"]), None)
                if item:
                    tile.value_label.setStyleSheet("font-size: 19px; font-weight: 600;")
                    lines = item["text"].strip().splitlines()
                    tile.value_label.setText(lines[0] if lines else "记下一点灵感")
                    tile.hint_label.setText(f"{len(item['text'])} 字 · 自动保存")
                    tile.detail_label.setText("\n".join(lines[1:6])[:300] or "点击下方继续记录。")
                    tile.open_button.setText("打开备忘录  →")

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

    def _focus_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        title = QLabel("番茄钟")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        subtitle = QLabel("把时间切成专注而轻盈的片段。")
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)
        timer_card = Card("focusCard")
        timer_layout = QVBoxLayout(timer_card)
        timer_layout.setContentsMargins(26, 28, 26, 28)
        self.focus_mode_label = QLabel("专注时段")
        self.focus_mode_label.setObjectName("eyebrow")
        self.focus_mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.focus_mode_label)
        self.focus_time_label = QLabel("25:00")
        self.focus_time_label.setObjectName("focusTime")
        self.focus_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.focus_time_label)
        controls = QHBoxLayout()
        controls.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_start = QPushButton("开始专注")
        self.focus_start.setObjectName("primaryButton")
        self.focus_start.setMinimumSize(130, 44)
        self.focus_start.clicked.connect(self.toggle_focus)
        reset = QPushButton("重置")
        reset.setObjectName("secondaryButton")
        reset.setMinimumSize(90, 44)
        reset.clicked.connect(self.reset_focus)
        controls.addWidget(self.focus_start)
        controls.addSpacing(10)
        controls.addWidget(reset)
        timer_layout.addLayout(controls)
        layout.addWidget(timer_card)
        settings_card = Card()
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(20, 18, 20, 18)
        settings_layout.addWidget(QLabel("时长设置", objectName="cardTitle"))
        row = QHBoxLayout()
        row.addWidget(QLabel("专注分钟"))
        self.work_spin = QSpinBox()
        self.work_spin.setRange(1, 120)
        self.work_spin.setValue(25)
        row.addWidget(self.work_spin)
        row.addSpacing(22)
        row.addWidget(QLabel("休息分钟"))
        self.break_spin = QSpinBox()
        self.break_spin.setRange(1, 60)
        self.break_spin.setValue(5)
        row.addWidget(self.break_spin)
        row.addStretch()
        save = QPushButton("应用设置")
        save.setObjectName("secondaryButton")
        save.clicked.connect(self.apply_focus_settings)
        row.addWidget(save)
        settings_layout.addLayout(row)
        layout.addWidget(settings_card)
        layout.addStretch()
        return page

    def _page_header(self, layout, title, subtitle):
        layout.addWidget(QLabel(title, objectName="pageTitle"))
        label = QLabel(subtitle, objectName="pageSubtitle")
        label.setWordWrap(True)
        layout.addWidget(label)

    def _memo_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 0)
        layout.setSpacing(14)
        self._page_header(layout, "备忘录", "一个想法，一条记录。编辑后自动保存，切换时也会保留。")
        content = QHBoxLayout()
        content.setSpacing(14)
        left = Card()
        left.setMaximumWidth(260)
        left_layout = QVBoxLayout(left)
        new = QPushButton("＋ 新建备忘录", objectName="primaryButton")
        new.clicked.connect(self.add_memo)
        left_layout.addWidget(new)
        self.memo_list = QListWidget(objectName="cleanList")
        self.memo_list.setMinimumWidth(160)
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
        card_layout.addWidget(QLabel("标题", objectName="fieldLabel"))
        self.memo_title = QLineEdit()
        self.memo_title.setPlaceholderText("给这条记录起个名字")
        self.memo_title.setMaxLength(120)
        self.memo_title.textChanged.connect(self._memo_changed)
        card_layout.addWidget(self.memo_title)
        card_layout.addWidget(QLabel("内容", objectName="fieldLabel"))
        self.memo_edit = QTextEdit()
        self.memo_edit.setAcceptRichText(False)
        self.memo_edit.setPlaceholderText("点击「新建备忘录」开始记录……")
        self.memo_edit.textChanged.connect(self._memo_changed)
        self.memo_timer = QTimer(self)
        self.memo_timer.setSingleShot(True)
        self.memo_timer.timeout.connect(self.save_memo)
        card_layout.addWidget(self.memo_edit, 1)
        bottom = QHBoxLayout()
        self.memo_status = QLabel("新建一条备忘录开始记录", objectName="cardHint")
        bottom.addWidget(self.memo_status, 1)
        self.memo_save_button = QPushButton("立即保存", objectName="primaryButton")
        self.memo_save_button.clicked.connect(self.save_memo)
        bottom.addWidget(self.memo_save_button)
        card_layout.addLayout(bottom)
        content.addWidget(card, 3)
        layout.addLayout(content, 1)
        return page

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(16)
        self._page_header(layout, "设置", "管理你的时间、工资计算方式与概览布局。所有设置仅保存在本机。")
        summary = Card()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(20, 18, 20, 18)
        row = QHBoxLayout()
        row.addWidget(QLabel("倒计时总览", objectName="cardTitle"), 1)
        manage = QPushButton("管理倒计时  →", objectName="secondaryButton")
        manage.clicked.connect(lambda: self._switch_page(4))
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
        layout.addStretch()
        return self._scroll_page(page)

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
            self.salary_feedback.setStyleSheet("color: #BA3345;")
            self.salary_feedback.setText(str(error))
            return False
        self.salary_config = config
        self.store.write_json("salary", config)
        result = salary_snapshot(config, datetime.now())
        self.salary_feedback.setStyleSheet("color: #237255;")
        self.salary_feedback.setText(f"已保存 · 本月 {result['workdays']} 个工作日 · 每日 ¥ {result['daily']:,.2f} · 每秒 ¥ {result['per_second']:.4f}")
        self._render_dashboard(datetime.now())
        return True

    def _load_settings(self) -> None:
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
        self._refresh_countdown_lists()
        self._refresh_memo_list(self.memos[0]["id"] if self.memos else None)
        self._calendar_selected(self.calendar.selectedDate())
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self._update_summary()
        self._render_focus_time()

    def _start_timers(self) -> None:
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self.timer = timer

    def _tick(self) -> None:
        now = datetime.now()
        self.day_label.setText(now.strftime("%Y年%m月%d日  ·  %A").replace("Monday", "星期一").replace("Tuesday", "星期二").replace("Wednesday", "星期三").replace("Thursday", "星期四").replace("Friday", "星期五").replace("Saturday", "星期六").replace("Sunday", "星期日"))
        self._update_countdown(now)
        if self.pomodoro_running:
            self.pomodoro_remaining = max(0, int((self.pomodoro_deadline - now).total_seconds() + 0.999))
            if self.pomodoro_remaining <= 0:
                self.pomodoro_mode = "break" if self.pomodoro_mode == "work" else "work"
                self.pomodoro_remaining = (self.break_spin.value() if self.pomodoro_mode == "break" else self.work_spin.value()) * 60
                self.pomodoro_deadline = now + timedelta(seconds=self.pomodoro_remaining)
                self.notify("专注时段结束，休息一下吧。" if self.pomodoro_mode == "break" else "休息结束，开始新的专注。")
            self._render_focus_time()
        self._check_reminders(now)
        self._render_dashboard(now)

    @staticmethod
    def _select_list_id(widget, item_id):
        for row in range(widget.count()):
            if widget.item(row).data(Qt.ItemDataRole.UserRole) == item_id:
                widget.setCurrentRow(row)
                return

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 1:
            self._calendar_selected(self.calendar.selectedDate())

    def _calendar_selected(self, date: QDate) -> None:
        self.selected_date_label.setText(date.toString("yyyy年MM月dd日"))
        self.reminder_list.clear()
        key = date.toString("yyyy-MM-dd")
        for reminder in self.store.reminders():
            if reminder.get("date") == key:
                state = " · 已提醒" if reminder.get("notified") else ""
                item = QListWidgetItem(reminder.get("time", "09:00") + "  " + reminder.get("text", "") + state)
                item.setData(Qt.ItemDataRole.UserRole, reminder)
                self.reminder_list.addItem(item)

    def add_reminder(self) -> None:
        text = self.reminder_input.text().strip()
        if not text:
            self.reminder_input.setFocus()
            return
        key = self.calendar.selectedDate().toString("yyyy-MM-dd")
        items = self.store.reminders()
        items.append({"id": uuid.uuid4().hex, "date": key, "time": self.reminder_time.time().toString("HH:mm"), "text": text})
        self.store.save_reminders(items)
        self.reminder_input.clear()
        self._calendar_selected(self.calendar.selectedDate())
        self._update_summary()

    def remove_reminder(self) -> None:
        current = self.reminder_list.currentItem()
        if not current:
            return
        target = current.data(Qt.ItemDataRole.UserRole)
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
            if scheduled <= now and not reminder.get("notified"):
                due.append(reminder["text"])
                reminder["notified"] = now.isoformat()
        if due:
            self.store.save_reminders(items)
            self.notify("日历提醒：" + "、".join(due))
            self._calendar_selected(self.calendar.selectedDate())

    def toggle_focus(self) -> None:
        if self.pomodoro_running:
            self.pomodoro_remaining = max(0, int((self.pomodoro_deadline - datetime.now()).total_seconds() + 0.999))
        else:
            self.pomodoro_deadline = datetime.now() + timedelta(seconds=self.pomodoro_remaining)
        self.pomodoro_running = not self.pomodoro_running
        self.work_spin.setEnabled(not self.pomodoro_running)
        self.break_spin.setEnabled(not self.pomodoro_running)
        self.focus_start.setText("暂停" if self.pomodoro_running else "继续专注")

    def reset_focus(self) -> None:
        self.pomodoro_running = False
        self.work_spin.setEnabled(True)
        self.break_spin.setEnabled(True)
        self.pomodoro_mode = "work"
        self.pomodoro_remaining = self.work_spin.value() * 60
        self.focus_start.setText("开始专注")
        self._render_focus_time()

    def apply_focus_settings(self) -> None:
        self.store.set("work", str(self.work_spin.value()))
        self.store.set("break", str(self.break_spin.value()))
        self.reset_focus()
        self._update_summary()

    def _render_focus_time(self) -> None:
        minutes, seconds = divmod(max(0, self.pomodoro_remaining), 60)
        self.focus_time_label.setText(f"{minutes:02d}:{seconds:02d}")
        self.focus_mode_label.setText("专注时段" if self.pomodoro_mode == "work" else "休息时段")

    def _refresh_memo_list(self, selected_id=None):
        self.memo_list.blockSignals(True)
        self.memo_list.clear()
        for memo in self.memos:
            item = QListWidgetItem(memo["title"] or "未命名备忘录")
            item.setData(Qt.ItemDataRole.UserRole, memo["id"])
            item.setToolTip(memo["title"])
            self.memo_list.addItem(item)
        self._select_list_id(self.memo_list, selected_id)
        self.memo_list.blockSignals(False)
        self._load_memo_editor(selected_id)

    def _load_memo_editor(self, item_id):
        self.active_memo_id = item_id
        memo = next((m for m in self.memos if m["id"] == item_id), None)
        for edit in (self.memo_title, self.memo_edit):
            edit.blockSignals(True)
            edit.setEnabled(memo is not None)
        self.memo_title.setText(memo["title"] if memo else "")
        self.memo_edit.setPlainText(memo["text"] if memo else "")
        for edit in (self.memo_title, self.memo_edit):
            edit.blockSignals(False)
        self.delete_memo_button.setEnabled(memo is not None)
        self.memo_save_button.setEnabled(memo is not None)
        self.memo_status.setText("已自动保存" if memo else "新建一条备忘录开始记录")

    def _memo_selected(self, current, previous=None):
        self.save_memo()
        self._load_memo_editor(current.data(Qt.ItemDataRole.UserRole) if current else None)

    def add_memo(self):
        self.save_memo()
        item = {"id": uuid.uuid4().hex, "title": "新备忘录", "text": ""}
        self.memos.append(item)
        self.store.write_json("memos", self.memos)
        self._refresh_memo_list(item["id"])
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.memo_title.setFocus()
        self.memo_title.selectAll()

    def delete_memo(self):
        if not self.active_memo_id:
            return
        self.save_memo()
        self.memo_timer.stop()
        index = next(i for i, m in enumerate(self.memos) if m["id"] == self.active_memo_id)
        self.deleted_memo = (index, self.memos[index], self.widget_config.get("memo:" + self.active_memo_id, {}).copy())
        self.memos.pop(index)
        self.widget_config.pop("memo:" + self.active_memo_id, None)
        self.active_memo_id = None
        self.store.write_json("memos", self.memos)
        self.store.write_json("widgets", self.widget_config)
        selected = self.memos[min(index, len(self.memos)-1)]["id"] if self.memos else None
        self._refresh_memo_list(selected)
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.undo_memo_button.show()

    def undo_delete_memo(self):
        if not self.deleted_memo:
            return
        self.save_memo()
        index, item, config = self.deleted_memo
        self.memos.insert(index, item)
        self.widget_config["memo:" + item["id"]] = config
        self.store.write_json("memos", self.memos)
        self.store.write_json("widgets", self.widget_config)
        self._refresh_memo_list(item["id"])
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self.deleted_memo = None
        self.undo_memo_button.hide()

    def _memo_changed(self) -> None:
        if self.active_memo_id:
            self.memo_status.setText("正在保存…")
            self.memo_timer.start(500)

    def save_memo(self) -> None:
        self.memo_timer.stop()
        memo = next((m for m in self.memos if m["id"] == self.active_memo_id), None)
        if memo is None:
            return
        title, text = self.memo_title.text(), self.memo_edit.toPlainText()
        title_changed = memo["title"] != title
        if title_changed or memo["text"] != text:
            memo.update(title=title, text=text)
            self.store.write_json("memos", self.memos)
            for row in range(self.memo_list.count()):
                item = self.memo_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == memo["id"]:
                    item.setText(title or "未命名备忘录")
                    item.setToolTip(title)
            tile = self.tiles.get("memo:" + memo["id"])
            if tile:
                tile.title_label.setText(title or "未命名备忘录")
            if title_changed:
                self._refresh_widget_settings()
            self._render_dashboard(datetime.now())
        self.memo_status.setText("已自动保存")

    def _update_summary(self) -> None:
        self._render_dashboard(datetime.now())
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())
        for reminder in self.store.reminders():
            date = QDate.fromString(reminder["date"], "yyyy-MM-dd")
            if date.isValid():
                style = QTextCharFormat()
                style.setForeground(QColor(PRIMARY))
                style.setFontWeight(QFont.Weight.Bold)
                style.setToolTip("有日历提醒")
                self.calendar.setDateTextFormat(date, style)


