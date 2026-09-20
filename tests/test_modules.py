"""Runtime lifecycle and real-window regression tests for optional features."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, date
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TimeTip-Application"))

from PyQt6.QtCore import QDate, QEvent, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QStackedWidget, QVBoxLayout, QWidget

from app.presentation.module_runtime import FeatureModule, ModuleManager, ModuleSpec
from app.infrastructure.store import Store
from app.infrastructure.database import DataStore
from app.presentation.window import TimeTipWindow


class Emitter(QObject):
    ping = pyqtSignal()


class SampleModule(FeatureModule):
    def __init__(self, context):
        super().__init__(context)
        self.started = self.stopped = self.ticks = self.events = self.signals = 0
        self.busy = False
        self.emitter = Emitter()

    def create_page(self):
        return QLabel("Test extension")

    def start(self):
        self.started += 1
        self.context.subscribe("sample", self.receive)
        self.context.connect(self.emitter.ping, self.receive_signal)
        self.timer = self.context.timer(60000, self.receive_signal)

    def receive(self, payload):
        self.events += 1

    def receive_signal(self):
        self.signals += 1

    def can_stop(self):
        return not self.busy

    def stop(self):
        self.stopped += 1

    def tick(self, now):
        self.ticks += 1


class FailingModule(SampleModule):
    def start(self):
        super().start()
        raise RuntimeError("start failed")


class StopFailureModule(SampleModule):
    def stop(self):
        raise RuntimeError("save failed")


class ModuleHost(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.pages = QStackedWidget(self)
        self.navigation = QVBoxLayout()
        self.modules = ModuleManager(self, self.pages, self.navigation)

    def _switch_page(self, index):
        self.pages.setCurrentIndex(index)

    def notify(self, text):
        pass


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temporary.name) / "settings.ini"))

    def tearDown(self):
        self.host.hide()
        self.host.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.store.close()
        self.temporary.cleanup()


class ModuleRuntimeTests(QtCase):
    def setUp(self):
        super().setUp()
        self.host = ModuleHost(self.store)
        self.manager = self.host.modules
        self.manager.register(ModuleSpec("dashboard", "Home", SampleModule, required=True))
        self.assertTrue(self.manager.enable("dashboard"))

    def test_importable_factory_load_unload_and_reload(self):
        self.manager.register(ModuleSpec("sample", "Sample", "test_modules:SampleModule"))
        entry = self.manager.entries["sample"]
        self.assertIsNone(entry.instance)
        self.assertTrue(self.manager.enable("sample"))
        first = entry.instance
        self.manager.tick(datetime.now())
        self.manager.publish("sample", 1)
        first.emitter.ping.emit()
        self.assertEqual((first.ticks, first.events, first.signals), (1, 1, 1))
        self.assertTrue(self.manager.navigate("sample"))
        self.assertTrue(self.manager.disable("sample"))
        self.assertIsNone(entry.instance)
        self.assertFalse(first.timer.isActive())
        self.manager.publish("sample", 2)
        first.emitter.ping.emit()
        self.manager.tick(datetime.now())
        self.assertEqual((first.ticks, first.events, first.signals), (1, 1, 1))
        self.assertTrue(self.manager.enable("sample"))
        self.assertIsNot(entry.instance, first)
        self.assertEqual(entry.instance.started, 1)
        self.assertTrue(self.manager.unregister("sample"))
        self.assertNotIn("sample", self.manager.entries)

    def test_dependency_order_and_unload_guard(self):
        self.manager.register(ModuleSpec("dependent", "Dependent", SampleModule, dependencies=("base",)))
        self.manager.register(ModuleSpec("base", "Base", SampleModule))
        self.assertTrue(self.manager.enable("dependent"))
        self.assertTrue(self.manager.is_enabled("base"))
        self.assertFalse(self.manager.disable("base"))
        self.assertTrue(self.manager.disable("dependent"))
        self.assertTrue(self.manager.disable("base"))
        self.assertFalse(self.manager.disable("dashboard"))

    def test_invalid_registration_and_dependency_failures(self):
        with self.assertRaises(ValueError):
            self.manager.register(ModuleSpec("dashboard", "Duplicate", SampleModule))
        with self.assertRaises(ValueError):
            self.manager.register(ModuleSpec("bad", "Bad", SampleModule, api_version=999))
        self.manager.register(ModuleSpec("missing", "Missing", SampleModule, dependencies=("absent",)))
        with self.assertLogs("app.presentation.module_runtime", level="ERROR"):
            self.assertFalse(self.manager.enable("missing"))
        self.assertIsNone(self.manager.entries["missing"].instance)
        self.manager.register(ModuleSpec("a", "A", SampleModule, dependencies=("b",)))
        self.manager.register(ModuleSpec("b", "B", SampleModule, dependencies=("a",)))
        with self.assertLogs("app.presentation.module_runtime", level="ERROR"):
            self.assertFalse(self.manager.enable("a"))
        self.assertFalse(self.manager.is_enabled("a"))

    def test_start_failure_rolls_back_new_dependencies_and_resources(self):
        self.manager.register(ModuleSpec("base", "Base", SampleModule))
        self.manager.register(ModuleSpec("broken", "Broken", FailingModule, dependencies=("base",)))
        with self.assertLogs("app.presentation.module_runtime", level="ERROR"):
            self.assertFalse(self.manager.enable("broken"))
        self.assertFalse(self.manager.is_enabled("base"))
        self.assertFalse(self.manager.is_enabled("broken"))
        self.assertIsNone(self.manager.entries["broken"].instance)
        self.assertTrue(self.manager.is_enabled("dashboard"))

    def test_busy_module_and_failed_save_remain_enabled(self):
        self.manager.register(ModuleSpec("busy", "Busy", SampleModule))
        self.manager.enable("busy")
        self.manager.entries["busy"].instance.busy = True
        self.assertFalse(self.manager.disable("busy"))
        self.assertTrue(self.manager.is_enabled("busy"))
        self.manager.register(ModuleSpec("save", "Save", StopFailureModule))
        self.manager.enable("save")
        with self.assertLogs("app.presentation.module_runtime", level="ERROR"):
            self.assertFalse(self.manager.disable("save"))
        self.assertTrue(self.manager.is_enabled("save"))
        self.assertIsNotNone(self.manager.entries["save"].instance)

    def test_shutdown_obeys_dependency_order_even_if_registered_backwards(self):
        stopped = []
        class OrderedModule(SampleModule):
            def stop(self):
                stopped.append(self.context.module_id)
        self.manager.register(ModuleSpec("child", "Child", OrderedModule, dependencies=("parent",)))
        self.manager.register(ModuleSpec("parent", "Parent", OrderedModule))
        self.assertTrue(self.manager.enable("child"))
        self.assertTrue(self.manager.shutdown())
        self.assertEqual(stopped, ["child", "parent"])

    def test_data_restore_applies_flags_without_restarting_active_modules(self):
        self.manager.register(ModuleSpec("sample", "Sample", SampleModule))
        self.manager.enable("sample")
        self.store.write_json("module_states", {"sample": False})
        self.assertEqual(self.manager.reload_preferences(), [])
        self.assertFalse(self.manager.is_enabled("sample"))
        self.store.write_json("module_states", {"sample": True})
        self.assertEqual(self.manager.reload_preferences(), [])
        instance = self.manager.entries["sample"].instance
        self.assertEqual(self.manager.reload_preferences(), [])
        self.assertIs(self.manager.entries["sample"].instance, instance)
        self.assertEqual(instance.started, 1)

    def test_old_context_cannot_notify_after_new_instance_is_loaded(self):
        self.manager.register(ModuleSpec("sample", "Sample", SampleModule))
        self.manager.enable("sample")
        old_context = self.manager.entries["sample"].context
        self.manager.disable("sample")
        self.manager.enable("sample")
        with patch.object(self.host, "notify") as notify:
            old_context.notify("late result")
            notify.assert_not_called()

    def test_sqlite_states_roundtrip_and_runtime_restore(self):
        root = Path(self.temporary.name)
        original = DataStore(root / "sqlite", migrate_legacy=False)
        restored = DataStore(root / "restored-sqlite", migrate_legacy=False)
        other = None
        try:
            other = ModuleHost(original)
            other.modules.register(ModuleSpec("sample", "Sample", SampleModule))
            other.modules.enable("sample")
            other.modules.disable("sample")
            self.assertFalse(json.loads(original.get("module_states"))["sample"])
            for suffix in (".json", ".zip"):
                backup = root / ("sqlite-backup" + suffix)
                original.export_data(str(backup))
                restored.import_data(str(backup))
                self.assertFalse(json.loads(restored.get("module_states"))["sample"])
            other.store = restored
            manager = ModuleManager(other, other.pages, other.navigation)
            manager.register(ModuleSpec("sample", "Sample", SampleModule))
            manager.restore()
            self.assertIsNone(manager.entries["sample"].instance)
        finally:
            if other is not None:
                other.deleteLater()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            original.close()
            restored.close()

    def test_disabled_default_module_is_never_instantiated(self):
        self.manager.register(ModuleSpec("off", "Off", FailingModule, default_enabled=False))
        self.manager.restore()
        self.assertIsNone(self.manager.entries["off"].instance)

    def test_retained_page_does_not_accept_previous_activation_callbacks(self):
        self.manager.register(ModuleSpec("cached", "Cached", SampleModule, retain_page=True))
        self.manager.enable("cached")
        entry = self.manager.entries["cached"]
        old_callback = entry.context._connections[0][1]
        self.manager.disable("cached")
        self.manager.enable("cached")
        old_callback()  # Simulate an already-queued delivery from before stop.
        self.assertEqual(entry.instance.signals, 0)
        entry.instance.emitter.ping.emit()
        self.assertEqual(entry.instance.signals, 1)


class WindowModulesTests(QtCase):
    def setUp(self):
        super().setUp()
        with patch.object(TimeTipWindow, "_start_timers"), patch(
            "app.presentation.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=False
        ):
            self.host = TimeTipWindow(self.store)
        self.host.show()

    def tearDown(self):
        self.host.jm_wait_for_shutdown()
        self.host.tray.hide()
        super().tearDown()

    def test_calendar_disabled_stops_notifications_and_reenable_catches_up_once(self):
        now = datetime.now()
        yesterday = (now - timedelta(days=1)).date().isoformat()
        self.store.save_reminders([
            {"id": "due", "date": yesterday, "time": "09:00", "text": "Due", "mode": "notify", "notified": False},
            {"id": "calendar", "date": yesterday, "time": "09:00", "text": "Calendar only", "mode": "calendar", "notified": False},
        ])
        self.host.modules.navigate("calendar")
        self.assertTrue(self.host.modules.disable("calendar"))
        self.assertEqual(self.host.pages.currentIndex(), 0)
        self.assertNotIn("reminders", self.host.tiles)
        self.assertFalse(self.host.modules.navigate("calendar"))
        with patch.object(self.host, "notify") as notify:
            self.host._tick()
            notify.assert_not_called()
            self.assertFalse(self.store.reminders()[0]["notified"])
            self.host.modules.enable("calendar")
            self.host._tick()
            self.host._tick()
            notify.assert_called_once()
        self.assertFalse(self.store.reminders()[1]["notified"])

    def test_focus_stops_and_retains_remaining_time(self):
        self.host.toggle_focus()
        self.assertTrue(self.host.pomodoro_running)
        self.host.modules.disable("focus")
        self.assertFalse(self.host.pomodoro_running)
        remaining = self.host.pomodoro_remaining
        self.host.modules.tick(datetime.now() + timedelta(hours=1))
        self.assertEqual(self.host.pomodoro_remaining, remaining)
        self.host.modules.enable("focus")
        self.assertFalse(self.host.pomodoro_running)
        self.assertEqual(self.host.pomodoro_remaining, remaining)

    def test_memo_flushes_before_disable_and_data_survives(self):
        self.host.add_memo()
        self.host.memo_title.setText("未保存的标题")
        self.assertTrue(self.host.modules.disable("memos"))
        self.assertFalse(self.host.memo_timer.isActive())
        self.assertEqual(self.store.load_collection("memos")[-1]["title"], "未保存的标题")
        self.host.modules.enable("memos")
        self.assertEqual(self.host.memo_title.text(), "未保存的标题")

    def test_anime_calendar_and_dashboard_follow_module_state(self):
        today = date.today()
        self.host.anime = [{"id": "a", "title": "Test Anime", "category": "watching",
                            "start_date": today.isoformat(), "end_date": today.isoformat(),
                            "air_days": [today.weekday()], "episode_count": 1, "progress": 0}]
        self.host.store.save_anime(self.host.anime)
        self.host._update_summary()
        self.host._calendar_selected(QDate.currentDate())
        self.assertEqual(self.host.reminder_list.count(), 1)
        self.assertTrue(self.host.modules.disable("anime"))
        self.assertEqual(self.host.reminder_list.count(), 0)
        self.assertNotIn("anime", self.host.tiles)
        self.assertEqual(len(self.store.anime()), 1)
        self.host.modules.enable("anime")
        self.assertEqual(self.host.reminder_list.count(), 1)
        self.assertIn("anime", self.host.tiles)

    def test_settings_persist_states_and_backup_roundtrip(self):
        self.host.module_checks["calendar"].setChecked(False)
        self.assertFalse(self.host.modules.is_enabled("calendar"))
        self.assertFalse(self.store.read_json("module_states", {})["calendar"])
        backup = Path(self.temporary.name) / "backup.json"
        self.store.export_data(str(backup))
        restored = Store(str(Path(self.temporary.name) / "restored.ini"))
        try:
            restored.import_data(str(backup))
            self.assertFalse(restored.read_json("module_states", {})["calendar"])
            with patch.object(TimeTipWindow, "_start_timers"), patch(
                "app.presentation.window.QSystemTrayIcon.isSystemTrayAvailable", return_value=False
            ):
                other = TimeTipWindow(restored)
            try:
                self.assertFalse(other.modules.is_enabled("calendar"))
                self.assertTrue(other.modules.is_enabled("settings"))
            finally:
                other.jm_wait_for_shutdown()
                other.tray.hide()
                other.deleteLater()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        finally:
            restored.close()

    def test_countdown_disabled_stops_notifications_without_losing_target(self):
        target = (datetime.now() - timedelta(minutes=2)).isoformat()
        self.host.countdowns = [{"id": "due", "title": "Due", "target": target,
                                 "mode": "standard", "notified": False}]
        self.store.write_json("countdowns", self.host.countdowns)
        self.host._refresh_countdown_lists()
        self.host.modules.disable("countdowns")
        self.assertFalse(self.host.add_countdown_button.isEnabled())
        with patch.object(self.host, "notify") as notify:
            self.host._tick()
            notify.assert_not_called()
            self.host.modules.enable("countdowns")
            self.host._tick()
            self.host._tick()
            notify.assert_called_once()
        self.assertEqual(self.store.load_collection("countdowns")[0]["target"], target)

    def test_calendar_add_and_remove_keep_calendar_only_mode(self):
        self.host.calendar.setSelectedDate(QDate.currentDate().addDays(1))
        self.host.reminder_input.setText("Only on calendar")
        self.host.reminder_mode.setCurrentIndex(self.host.reminder_mode.findData("calendar"))
        self.host.add_reminder()
        self.assertEqual(self.store.reminders()[0]["mode"], "calendar")
        self.assertEqual(self.host.reminder_list.count(), 1)
        self.host.reminder_list.setCurrentRow(0)
        self.host.remove_reminder()
        self.assertEqual(self.store.reminders(), [])
        self.assertEqual(self.host.reminder_list.count(), 0)

    def test_filtered_anime_order_preserves_hidden_records_and_progress(self):
        self.host.anime = [
            {"id": key, "title": title, "category": "backlog", "episode_count": 12,
             "progress": 0, "group": group}
            for key, title, group in [("a", "Alpha", "A"), ("b", "Beta", "B"), ("c", "Charlie", "A")]
        ]
        self.store.save_anime(self.host.anime)
        self.host._refresh_anime_list()
        self.host.anime_group_filter.setCurrentIndex(self.host.anime_group_filter.findData("A"))
        self.assertEqual(self.host.anime_list.ids(), ["a", "c"])
        self.host._save_anime_order(["c", "a"])
        self.assertEqual([a["id"] for a in self.host.anime], ["c", "b", "a"])
        self.host._save_anime_progress("c", 3)
        self.assertEqual(self.store.anime()[0]["progress"], 3)
        self.host.anime_sort.setCurrentIndex(self.host.anime_sort.findData("title"))
        self.assertEqual(self.host.anime_list.ids(), ["a", "c"])
        self.assertFalse(self.host.anime_list.dragEnabled())
        self.host.anime_search.setText("char")
        self.assertEqual(self.host.anime_list.ids(), ["c"])

    def test_restoring_backup_updates_runtime_module_switches(self):
        backup = Path(self.temporary.name) / "runtime-backup.json"
        self.store.write_json("module_states", {"calendar": False, "focus": False})
        self.store.export_data(str(backup))
        self.assertTrue(self.host.modules.is_enabled("calendar"))
        with patch("app.presentation.settings_page.QFileDialog.getOpenFileName",
                   return_value=(str(backup), "")):
            self.host.import_data()
        self.assertFalse(self.host.modules.is_enabled("calendar"))
        self.assertFalse(self.host.modules.is_enabled("focus"))
        self.assertFalse(self.host.module_checks["calendar"].isChecked())

    def test_settings_save_salary_and_theme_after_extraction(self):
        self.host.monthly_salary.setValue(22000)
        self.assertTrue(self.host.save_salary_settings())
        self.assertEqual(self.store.read_json("salary", {})["monthly"], 22000)
        self.host.theme_combo.setCurrentIndex(self.host.theme_combo.findData("dark"))
        self.assertEqual(self.host.theme.id, "dark")
        self.assertEqual(self.store.get("theme"), "dark")

    def test_new_module_needs_no_main_window_edit_and_unloads_cleanly(self):
        self.host.modules.register(ModuleSpec("sample", "Sample", "test_modules:SampleModule"))
        self.assertIn("sample", self.host.module_checks)
        self.assertTrue(self.host.modules.enable("sample"))
        self.assertTrue(self.host.modules.navigate("sample"))
        self.assertTrue(self.host.modules.unregister("sample"))
        self.assertEqual(self.host.pages.currentIndex(), 0)
        self.assertEqual(len(self.host.nav_buttons), 8)
        self.assertTrue(self.host.modules.navigate("tarot"))
        self.assertEqual(self.host.pages.currentIndex(), 9)


if __name__ == "__main__":
    unittest.main()
