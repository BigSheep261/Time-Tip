from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta

from PyQt6.QtCore import QByteArray, QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QBoxLayout, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizeGrip, QSpinBox, QStackedWidget, QVBoxLayout, QWidget, QSystemTrayIcon

from app.domain.salary import DEFAULT_SALARY, salary_snapshot, validate_salary
from app.domain.layout import WIDGET_SIZES
from app.domain.countdowns import countdown_snapshot
from app.domain.anime import anime_for_date, episode_label
from app.domain.dates import format_dashboard_date
from app.presentation.anime_dialog import DEFAULT_ANIME_COVER
from app.presentation.countdowns import CountdownPageMixin
from app.presentation.memos import MemoPageMixin
from app.presentation.emojis import EmojiPageMixin
from app.presentation.jm_manga import JMMangaPageMixin
from app.presentation.tarot import TarotPageMixin
from app.presentation.widgets import Card, DashboardTile, ResizeHandle, WidgetGrid
from app.infrastructure.store import Store
from app.infrastructure.updater import Updater
from app.version import DISPLAY_VERSION
from app.presentation.theme import APP_NAME, apply_theme, available_themes


from app.presentation.calendar_page import CalendarPageMixin
from app.presentation.anime_page import AnimePageMixin
from app.presentation.settings_page import SettingsPageMixin
from app.presentation.chrome import TitleBar, ThemeLogo, make_app_icon
from app.presentation.module_runtime import ModuleManager
from app.presentation.builtin_modules import BUILTIN_MODULES, NAVIGATION_ORDER


class TimeTipWindow(CalendarPageMixin, AnimePageMixin, SettingsPageMixin, TarotPageMixin, JMMangaPageMixin, EmojiPageMixin, MemoPageMixin, CountdownPageMixin, QMainWindow):
    def __init__(self, store: Store | None = None, *, feature_specs=()) -> None:
        super().__init__()
        self.store = store or Store()
        self._feature_specs = tuple(feature_specs)
        self._modules_ready = False
        # Apply the persisted theme before constructing widgets so every child starts
        # with the right palette; later changes reuse the same window and widgets.
        self.theme = apply_theme(QApplication.instance(), self.store.get("theme", "light"))
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
        self.anime = self.store.anime()
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
        self._jm_unlock_clicks = 0
        self._jm_unlock_timer = QTimer(self)
        self._jm_unlock_timer.setSingleShot(True)
        self._jm_unlock_timer.setInterval(1600)
        self._jm_unlock_timer.timeout.connect(self._reset_jm_unlock_clicks)
        self.updater = Updater(self)
        self.updater.update_available.connect(self._on_update_available)
        self.updater.no_update.connect(self._on_no_update)
        self.updater.download_progress.connect(self._on_update_progress)
        self.updater.download_ready.connect(self._on_update_downloaded)
        self.updater.failed.connect(self._on_update_failed)
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
        module_errors = self.modules.restore()
        self._modules_ready = True
        self.modules.changed.connect(self._modules_changed)
        self._modules_changed()
        self.module_feedback.setText("\n".join(module_errors))
        self._setup_resize()
        self._start_timers()
        self._tick()

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def set_theme(self, theme_id: str) -> None:
        """Switch the theme in place; timers, pages, edits and window state survive."""
        self.theme = apply_theme(QApplication.instance(), theme_id)
        self.store.set("theme", self.theme.id)
        if hasattr(self, "title_bar"):
            self.title_bar.set_theme(self.theme)
        if hasattr(self, "theme_combo"):
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self.theme.id)))
            self.theme_combo.blockSignals(False)
            self.theme_description.setText(self.theme.description)
        # Date marks use the accent color and therefore need repainting too.
        if hasattr(self, "calendar"):
            self._update_summary()
        if self._modules_ready:
            self.modules.publish("theme.changed", self.theme.id)

    def toggle_theme(self) -> None:
        ids = [theme.id for theme in available_themes()]
        current = ids.index(self.theme.id) if self.theme.id in ids else 0
        self.set_theme(ids[(current + 1) % len(ids)])

    def _reset_jm_unlock_clicks(self) -> None:
        self._jm_unlock_clicks = 0

    def _unlock_jm_mode(self) -> None:
        if self.jm_nav_button.isVisible():
            self._leave_jm_mode()
            return
        self._jm_unlock_clicks += 1
        self._jm_unlock_timer.start()
        remaining = max(0, 5 - self._jm_unlock_clicks)
        if remaining:
            return
        self._reset_jm_unlock_clicks()
        if not self.modules.enable("jm"):
            return
        self.modules.set_visible("jm", True)
        self.jm_unlock_button.setObjectName("dangerButton")
        self.jm_unlock_button.setText("离开里模式")
        self.jm_unlock_button.style().unpolish(self.jm_unlock_button)
        self.jm_unlock_button.style().polish(self.jm_unlock_button)
        self.modules.navigate("jm")

    def _leave_jm_mode(self) -> None:
        """Hide the optional JM page and return to settings."""
        if self.pages.currentWidget() is self.modules.entries["jm"].page:
            self.modules.navigate("settings")
        self.modules.set_visible("jm", False)
        self._reset_jm_unlock_clicks()
        self.jm_unlock_button.setObjectName("primaryButton")
        self.jm_unlock_button.setText("里模式")
        self.jm_unlock_button.style().unpolish(self.jm_unlock_button)
        self.jm_unlock_button.style().polish(self.jm_unlock_button)


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
        if not self.save_memo():
            return
        if not self.jm_shutdown():
            return
        if not self.modules.can_shutdown():
            return
        if not self.modules.shutdown():
            self.notify(self.modules.last_error)
            return
        self.quitting = True
        self.save_window_geometry()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        if not self.save_memo():
            event.ignore()
            return
        self.save_window_geometry()
        if not self.quitting and self.tray.isVisible():
            self.hide()
            event.ignore()
        elif self.jm_shutdown() and self.modules.can_shutdown():
            if self.modules.shutdown():
                event.accept()
            else:
                self.notify(self.modules.last_error)
                event.ignore()
        else:
            event.ignore()

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
        self.title_bar = TitleBar(self)
        self.title_bar.set_theme(self.theme)
        root_layout.addWidget(self.title_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(18, 0, 18, 18)
        body_layout.setSpacing(14)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(152)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_content = QWidget()
        side_layout = QVBoxLayout(sidebar_content)
        side_layout.setContentsMargins(10, 14, 10, 14)
        side_layout.setSpacing(7)
        side_label = QLabel("工作台")
        side_label.setObjectName("sectionLabel")
        side_layout.addWidget(side_label)
        feature_navigation = QVBoxLayout()
        feature_navigation.setSpacing(7)
        side_layout.addLayout(feature_navigation)
        self.pages = QStackedWidget()
        self.modules = ModuleManager(self, self.pages, feature_navigation)
        for spec in (*BUILTIN_MODULES, *self._feature_specs):
            self.modules.register(spec)
        for key in NAVIGATION_ORDER + tuple(spec.id for spec in self._feature_specs):
            button = self.modules.entries[key].button
            feature_navigation.removeWidget(button)
            feature_navigation.addWidget(button)
        # Keep legacy public indices stable; new modules navigate by ID.
        self.nav_buttons = [self.modules.entries[spec.id].button for spec in BUILTIN_MODULES[:8]]
        self.jm_nav_button = self.modules.entries["jm"].button
        self.tarot_nav_button = self.modules.entries["tarot"].button
        self._all_nav_buttons = self.nav_buttons + [self.jm_nav_button, self.tarot_nav_button]
        side_layout.addStretch()
        hint = QLabel(f"私人效率工具 {DISPLAY_VERSION}\n数据仅保存在本机")
        hint.setObjectName("sideHint")
        side_layout.addWidget(hint)
        sidebar_scroll.setWidget(sidebar_content)
        sidebar_layout.addWidget(sidebar_scroll)
        body_layout.addWidget(sidebar)

        for spec in BUILTIN_MODULES:
            self.modules.prepare(spec.id)
        body_layout.addWidget(self.pages, 1)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self.nav_buttons[0].setChecked(True)

    def feature_enabled(self, module_id):
        # Legacy startup builds shared widgets before applying persisted states.
        return not self._modules_ready or self.modules.is_enabled(module_id)

    def _modules_changed(self):
        if not self._modules_ready:
            return
        self._rebuild_dashboard()
        self._refresh_widget_settings()
        self._refresh_calendar_marks()
        self._calendar_selected(self.calendar.selectedDate())
        self._refresh_module_settings()
        self.add_countdown_button.setEnabled(self.feature_enabled("countdowns"))
        self.modules.publish("modules.changed")

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
        self.add_countdown_button = add_countdown
        add_countdown.clicked.connect(lambda: self.modules.navigate("countdowns") and self.new_countdown())
        header.addWidget(add_countdown)
        self.edit_layout_button = QPushButton("编辑布局", objectName="secondaryButton")
        self.edit_layout_button.setCheckable(True)
        self.edit_layout_button.toggled.connect(self._toggle_layout_editing)
        header.addWidget(self.edit_layout_button)
        layout.addLayout(header)
        self.layout_hint = QLabel("拖动组件调整位置，点击右上角 ··· 调整大小、顺序或隐藏；隐藏的组件可在设置中恢复。", objectName="pageSubtitle")
        self.layout_hint.setWordWrap(True)
        self.layout_hint.hide()
        layout.addWidget(self.layout_hint)
        self.grid = WidgetGrid()
        self.grid.tileMoved.connect(lambda key, target: self._change_widget(key, "move_to", target))
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
        if self.anime:
            specs.append(("anime", "番剧更新", (2, 1), "plain"))
        owners = {"focus": "focus", "reminders": "calendar", "anime": "anime",
                  "countdown": "countdowns", "memo": "memos"}
        return [spec for spec in specs if self.feature_enabled(owners.get(spec[0].split(":")[0], "dashboard"))]

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
        # Reuse existing tiles so reorder and resize operations animate in place.
        previous = self.tiles
        self.tiles = {}
        for key, title, default_size, tone in self._ordered_specs():
            state = self._widget_state(key, default_size)
            if not state["visible"]:
                continue
            tile = previous.pop(key, None)
            if tile is None:
                tile = DashboardTile(key, title, tuple(state["size"]), tone)
                tile.changed.connect(self._change_widget)
                tile.opened.connect(self._open_widget)
            else:
                tile.update_spec(title, tuple(state["size"]), tone)
            tile.set_editing(self.edit_layout_button.isChecked())
            self.tiles[key] = tile
        for tile in previous.values():
            tile.hide()
            tile.deleteLater()
        self.grid.set_tiles(list(self.tiles.values()))
        self._render_dashboard(datetime.now())

    def _toggle_layout_editing(self, editing):
        self.edit_layout_button.setText("完成布局" if editing else "编辑布局")
        self.layout_hint.setVisible(editing)
        self.grid.set_editing(editing)
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
        elif action == "move_to":
            keys = [spec[0] for spec in self._ordered_specs()]
            if key in keys:
                keys.remove(key)
                target = max(0, min(len(keys), int(value)))
                keys.insert(target, key)
                for order, item_key in enumerate(keys):
                    self.widget_config[item_key]["order"] = order
        self.store.write_json("widgets", self.widget_config)
        self._rebuild_dashboard()
        self._refresh_widget_settings()

    def _open_widget(self, key):
        if key.startswith("countdown:"):
            if self.modules.navigate("countdowns"):
                self._select_list_id(self.countdown_list, key.split(":", 1)[1])
        elif key.startswith("memo:"):
            if self.modules.navigate("memos"):
                self._select_list_id(self.memo_list, key.split(":", 1)[1])
        else:
            self.modules.navigate({"salary": "settings", "clock": "calendar", "focus": "focus", "reminders": "calendar", "anime": "anime"}[key])

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
            elif key == "anime":
                today = anime_for_date(self.anime, now.date())
                cover = next((a.get("cover") for a in today if a.get("cover")), next((a.get("cover") for a in self.anime if a.get("cover")), ""))
                default_cover = DEFAULT_ANIME_COVER
                cover_path = Path(cover) if cover and Path(cover).is_file() else default_cover
                pixmap = QPixmap(str(cover_path)) if cover_path.is_file() else make_app_icon().pixmap(96, 96)
                tile.value_label.setPixmap(pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                tile.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tile.hint_label.setText("、".join(a["title"] for a in today) if today else "今天没有番剧更新")
                tile.detail_label.setText("\n".join(f'{a["title"]} · {episode_label(a)}' for a in today) or "在看番提醒页添加追番。")
                tile.open_button.setText("管理看番提醒  →")
            elif key.startswith("memo:"):
                item = next((item for item in self.memos if key == "memo:" + item["id"]), None)
                if item:
                    tile.value_label.setStyleSheet("font-size: 19px; font-weight: 600;")
                    lines = item["text"].strip().splitlines()
                    tile.value_label.setText(lines[0] if lines else "记下一点灵感")
                    tile.hint_label.setText(f"{len(item['text'])} 字 · 自动保存")
                    tile.detail_label.setText("\n".join(lines[1:6])[:300] or "点击下方继续记录。")
                    tile.open_button.setText("打开备忘录  →")


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


    def _start_timers(self) -> None:
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self.timer = timer

    def _tick(self) -> None:
        now = datetime.now()
        self.day_label.setText(format_dashboard_date(now, self.date_format))
        self.modules.tick(now)
        self._render_dashboard(now)

    def _tick_focus(self, now):
        if self.pomodoro_running:
            self.pomodoro_remaining = max(0, int((self.pomodoro_deadline - now).total_seconds() + 0.999))
            if self.pomodoro_remaining <= 0:
                self.pomodoro_mode = "break" if self.pomodoro_mode == "work" else "work"
                self.pomodoro_remaining = (self.break_spin.value() if self.pomodoro_mode == "break" else self.work_spin.value()) * 60
                self.pomodoro_deadline = now + timedelta(seconds=self.pomodoro_remaining)
                self.notify("专注时段结束，休息一下吧。" if self.pomodoro_mode == "break" else "休息结束，开始新的专注。")
            self._render_focus_time()

    @staticmethod
    def _select_list_id(widget, item_id):
        for row in range(widget.count()):
            if widget.item(row).data(Qt.ItemDataRole.UserRole) == item_id:
                widget.setCurrentRow(row)
                return

    def _switch_page(self, index: int) -> None:
        entry = self.modules.entry_at(index)
        if entry is None or not entry.enabled or not entry.visible:
            return
        current = self.pages.currentIndex()
        if index == current:
            return
        previous = self.modules.entry_at(current)
        if previous and previous.enabled:
            previous.instance.hidden()
        direction = 1 if index > current else -1
        self.pages.setCurrentIndex(index)
        page = self.pages.currentWidget()
        if page is not None:
            if hasattr(self, "_page_animation"):
                self._page_animation.stop()
            page.raise_()
            page.move(self.pages.width() * direction, 0)
            animation = QPropertyAnimation(page, b"pos", self)
            animation.setDuration(240)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(page.pos())
            animation.setEndValue(QPoint(0, 0))
            self._page_animation = animation
            animation.start()
        for candidate in self.modules.entries.values():
            candidate.button.setChecked(candidate is entry)
        entry.instance.shown()


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


    def _update_summary(self):
        self._render_dashboard(datetime.now())
        self._refresh_calendar_marks()
