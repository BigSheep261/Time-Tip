"""Versioned, explicit feature registration and Qt resource lifecycle.

Registration accepts trusted Python factories, never paths from user backups.
Legacy pages can retain their widget tree while disabled during migration.
New modules are disposed on disable and recreated on the next enable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
import json
import logging
import re
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QWidget

LOG = logging.getLogger(__name__)
MODULE_API_VERSION = 1


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    title: str
    factory: str | Callable
    api_version: int = MODULE_API_VERSION
    dependencies: tuple[str, ...] = ()
    required: bool = False
    default_enabled: bool = True
    visible: bool = True
    manageable: bool = True
    retain_page: bool = False


class ModuleContext:
    """Services available to modules; owned subscriptions stop on unload."""

    def __init__(self, manager, module_id):
        self._manager = manager
        self.module_id = module_id
        self.store = manager.host.store
        self.parent = manager.host
        self._connections = []
        self._timers = []
        self._subscriptions = []
        self._generation = 0

    def navigate(self, module_id):
        return self._manager.navigate(module_id)

    def _is_active(self):
        entry = self._manager.entries.get(self.module_id)
        return bool(entry and entry.enabled and entry.context is self)

    def notify(self, text):
        if self._is_active():
            self._manager.host.notify(text)

    def publish(self, event, payload=None):
        if self._is_active():
            self._manager.publish(event, payload)

    def subscribe(self, event, callback):
        self._subscriptions.append((event, callback))

    def connect(self, signal, callback):
        # Queued signals may already be in Qt's event queue when disconnected.
        generation = self._generation
        def guarded(*args):
            if generation == self._generation and self._is_active():
                callback(*args)
        signal.connect(guarded)
        self._connections.append((signal, guarded))

    def timer(self, milliseconds, callback, *, single_shot=False):
        timer = QTimer(self.parent)
        timer.setSingleShot(single_shot)
        self.connect(timer.timeout, callback)
        self._timers.append(timer)
        timer.start(milliseconds)
        return timer

    def cleanup(self):
        self._generation += 1
        for timer in self._timers:
            timer.stop()
            timer.deleteLater()
        self._timers.clear()
        for signal, callback in self._connections:
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass
        self._connections.clear()
        self._subscriptions.clear()


class FeatureModule:
    """Implement create_page; optionally override the lifecycle hooks."""

    def __init__(self, context: ModuleContext):
        self.context = context

    def create_page(self) -> QWidget:
        raise NotImplementedError

    def start(self):
        """Acquire resources; called on every enable."""

    def can_stop(self) -> bool:
        """Return False while work cannot safely be stopped. Must not mutate."""
        return True

    def stop(self):
        """Flush state and stop/join workers before returning."""

    def tick(self, now: datetime):
        pass

    def shown(self):
        pass

    def hidden(self):
        pass


@dataclass
class ModuleEntry:
    spec: ModuleSpec
    page: QWidget
    button: QPushButton
    instance: FeatureModule | None = None
    context: ModuleContext | None = None
    enabled: bool = False
    visible: bool = True


class ModuleManager(QObject):
    changed = pyqtSignal()

    def __init__(self, host, pages, navigation):
        super().__init__(host)
        self.host, self.pages, self.navigation = host, pages, navigation
        self.entries: dict[str, ModuleEntry] = {}
        self.last_error = ""
        self._busy = False
        self._states = self._read_states()

    def register(self, spec: ModuleSpec):
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", spec.id):
            raise ValueError("模块 ID 必须使用小写字母、数字、点、下划线或连字符")
        if spec.id in self.entries:
            raise ValueError(f"模块 ID 重复：{spec.id}")
        if spec.api_version != MODULE_API_VERSION:
            raise ValueError(f"模块接口版本不兼容：{spec.id}")
        page = QWidget()
        self.pages.addWidget(page)
        button = QPushButton(spec.title, objectName="navButton")
        button.setCheckable(True)
        button.setMinimumHeight(44)
        button.clicked.connect(lambda checked=False, key=spec.id: self.navigate(key))
        button.hide()
        self.navigation.addWidget(button)
        self.entries[spec.id] = ModuleEntry(spec, page, button, visible=spec.visible)
        self.changed.emit()

    def is_enabled(self, module_id):
        entry = self.entries.get(module_id)
        return bool(entry and entry.enabled)

    def _replace_page(self, entry, page):
        index = self.pages.indexOf(entry.page)
        old = entry.page
        current = self.pages.currentWidget()
        self.pages.removeWidget(old)
        self.pages.insertWidget(index, page)
        if current is old:
            self.pages.setCurrentWidget(page)
        elif current is not None:
            self.pages.setCurrentWidget(current)
        old.hide()
        old.deleteLater()
        entry.page = page

    def prepare(self, module_id):
        """Create a page without starting it (legacy startup compatibility)."""
        entry = self.entries[module_id]
        if entry.instance is not None:
            return
        context = ModuleContext(self, module_id)
        factory = entry.spec.factory
        instance = None
        try:
            if isinstance(factory, str):
                module, name = factory.split(":", 1)
                factory = getattr(import_module(module), name)
            instance = factory(context)
            if not isinstance(instance, FeatureModule):
                raise TypeError("模块工厂必须返回 FeatureModule")
            page = instance.create_page()
            if not isinstance(page, QWidget):
                raise TypeError("模块页面必须是 QWidget")
            self._replace_page(entry, page)
            entry.instance, entry.context = instance, context
            page.setEnabled(False)
        except Exception:
            context.cleanup()
            if isinstance(instance, FeatureModule):
                try:
                    instance.stop()
                except Exception:
                    LOG.exception("Failed to clean up module %s", module_id)
            raise

    def _dependency_order(self, module_id, visiting=None, visited=None):
        visiting = set() if visiting is None else visiting
        visited = set() if visited is None else visited
        if module_id not in self.entries:
            raise ValueError(f"缺少依赖模块：{module_id}")
        if module_id in visiting:
            raise ValueError(f"模块依赖存在循环：{module_id}")
        if module_id in visited:
            return []
        visiting.add(module_id)
        order = []
        for dependency in self.entries[module_id].spec.dependencies:
            order.extend(self._dependency_order(dependency, visiting, visited))
        visiting.remove(module_id)
        visited.add(module_id)
        return order + [module_id]

    def enable(self, module_id, *, persist=True):
        if self._busy:
            self.last_error = "模块状态正在切换，请稍后重试。"
            return False
        self._busy = True
        started = []
        try:
            for key in self._dependency_order(module_id):
                entry = self.entries[key]
                if entry.enabled:
                    continue
                self.prepare(key)
                entry.enabled = True
                started.append(entry)
                entry.instance.start()
                entry.page.setEnabled(True)
                entry.button.setVisible(entry.visible)
            if persist:
                self._save_states()
            self.last_error = ""
        except Exception as error:
            for entry in reversed(started):
                try:
                    self._stop_entry(entry)
                except Exception:
                    # A failed stop must not destroy a page still used by a
                    # worker. Keep it available for cleanup, but stop dispatch.
                    entry.enabled = False
                    entry.context.cleanup()
                    entry.button.hide()
                    entry.page.setEnabled(False)
                    LOG.exception("Module rollback failed: %s", entry.spec.id)
            self.last_error = f"模块加载失败：{error}"
            LOG.exception("Failed to enable module %s", module_id)
            return False
        finally:
            self._busy = False
        self.changed.emit()
        return True

    def _stop_entry(self, entry):
        # Keep the page and subscriptions alive if flushing state fails.
        entry.instance.stop()
        entry.enabled = False
        entry.context.cleanup()
        entry.button.hide()
        entry.page.setEnabled(False)
        if not entry.spec.retain_page:
            self._replace_page(entry, QWidget())
            entry.instance = entry.context = None

    def disable(self, module_id, *, persist=True):
        if self._busy:
            self.last_error = "模块状态正在切换，请稍后重试。"
            return False
        entry = self.entries[module_id]
        if entry.spec.required:
            self.last_error = "此模块提供基础导航或设置，当前阶段需要保持启用。"
            return False
        dependants = [e.spec.title for e in self.entries.values()
                      if e.enabled and module_id in e.spec.dependencies]
        if dependants:
            self.last_error = "请先停用依赖此模块的功能：" + "、".join(dependants)
            return False
        if not entry.enabled:
            return True
        self._busy = True
        try:
            if not entry.instance.can_stop():
                self.last_error = "模块仍有运行中的任务或未保存内容，请处理后再停用。"
                return False
            if self.pages.currentWidget() is entry.page:
                self.navigate("dashboard")
            self._stop_entry(entry)
            if persist:
                self._save_states()
            self.last_error = ""
        except Exception as error:
            self.last_error = f"模块停止失败：{error}"
            LOG.exception("Failed to disable module %s", module_id)
            return False
        finally:
            self._busy = False
            self.changed.emit()
        return True

    def unregister(self, module_id):
        entry = self.entries[module_id]
        if entry.spec.retain_page or entry.spec.required:
            self.last_error = "内置兼容模块当前支持停用，不支持移除注册。"
            return False
        if not self.disable(module_id):
            return False
        self.pages.removeWidget(entry.page)
        entry.page.deleteLater()
        self.navigation.removeWidget(entry.button)
        entry.button.deleteLater()
        del self.entries[module_id]
        self.changed.emit()
        return True

    def _read_states(self):
        # This is a settings key, not a list collection. SQLite stores the two
        # in different tables; get/set keeps INI and SQLite backups equivalent.
        try:
            raw = json.loads(self.host.store.get("module_states", "{}"))
        except (TypeError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save_states(self):
        states = {**self._states, **{key: e.enabled for key, e in self.entries.items()}}
        self.host.store.set("module_states", json.dumps(states, ensure_ascii=False))
        self._states = states

    def restore(self):
        errors = []
        for key, entry in self.entries.items():
            enabled = self._states.get(key, entry.spec.default_enabled)
            if entry.spec.required or enabled is not False:
                if not self.enable(key, persist=False):
                    errors.append(entry.spec.title + "：" + self.last_error)
                    if entry.spec.required:
                        raise RuntimeError(self.last_error)
        return errors

    def reload_preferences(self):
        """Apply restored enable flags; refuse busy modules without data loss."""
        self._states = self._read_states()
        wanted = {key: e.spec.required or self._states.get(key, e.spec.default_enabled) is not False
                  for key, e in self.entries.items()}
        # Dependencies of an enabled module are necessarily enabled too.
        for key in list(wanted):
            if wanted[key]:
                for dependency in self._dependency_order(key):
                    wanted[dependency] = True
        errors = []
        order = self._shutdown_order()
        for key in order:
            if not wanted[key] and not self.disable(key, persist=False):
                errors.append(self.last_error)
        errors.extend(self.restore())
        return errors

    def set_visible(self, module_id, visible):
        entry = self.entries[module_id]
        entry.visible = bool(visible)
        entry.button.setVisible(entry.enabled and entry.visible)

    def navigate(self, module_id):
        entry = self.entries.get(module_id)
        if entry is None or not entry.enabled or not entry.visible:
            return False
        self.host._switch_page(self.pages.indexOf(entry.page))
        return True

    def entry_at(self, index):
        widget = self.pages.widget(index)
        return next((entry for entry in self.entries.values() if entry.page is widget), None)

    def tick(self, now):
        for entry in list(self.entries.values()):
            if entry.enabled:
                try:
                    entry.instance.tick(now)
                except Exception:
                    LOG.exception("Module tick failed: %s", entry.spec.id)

    def publish(self, event, payload=None):
        for entry in list(self.entries.values()):
            if entry.enabled and entry.context:
                for name, callback in list(entry.context._subscriptions):
                    if name == event and entry.enabled:
                        try:
                            callback(payload)
                        except Exception:
                            LOG.exception("Module event failed: %s / %s", entry.spec.id, event)

    def _shutdown_order(self):
        order, visited = [], set()
        for key, entry in self.entries.items():
            if entry.enabled:
                order.extend(self._dependency_order(key, visited=visited))
        return list(reversed(order))

    def can_shutdown(self):
        try:
            return all(not e.enabled or e.instance.can_stop() for e in self.entries.values())
        except Exception as error:
            self.last_error = f"模块退出检查失败：{error}"
            LOG.exception("Module shutdown check failed")
            return False

    def shutdown(self):
        stopped = []
        try:
            for key in self._shutdown_order():
                entry = self.entries[key]
                if entry.enabled:
                    self._stop_entry(entry)
                    stopped.append(key)
        except Exception as error:
            LOG.exception("Module shutdown failed")
            for key in reversed(stopped):
                self.enable(key, persist=False)
            self.last_error = f"模块停止失败：{error}"
            return False
        return True
