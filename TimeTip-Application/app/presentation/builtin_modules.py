"""Lifecycle adapters for pages migrating away from the shared window.

New features should implement FeatureModule directly. These adapters deliberately
retain legacy pages so existing widget references and unsaved forms remain valid.
"""
from app.presentation.module_runtime import FeatureModule, ModuleSpec


class BuiltinPageModule(FeatureModule):
    def __init__(self, context, builder, *, scroll=False):
        super().__init__(context)
        self.host = context.parent
        self.builder, self.scroll = builder, scroll

    def create_page(self):
        page = getattr(self.host, self.builder)()
        return self.host._scroll_page(page) if self.scroll else page

    def start(self):
        if self.context.module_id == "jm":
            self.host._jm_closing = False

    def can_stop(self):
        key = self.context.module_id
        if key == "jm":
            return not self.host._jm_workers and not any(
                task["state"] in {"排队中", "下载中"} for task in self.host.jm_queue)
        if key == "anime":
            dialog = getattr(self.host, "_anime_dialog", None)
            return dialog is None or not dialog.isVisible()
        return True

    def stop(self):
        key = self.context.module_id
        if key == "focus" and self.host.pomodoro_running:
            self.host.toggle_focus()
        elif key == "memos":
            if not self.host.save_memo():
                raise RuntimeError("备忘录保存失败")
        elif key == "tarot":
            self.host.tarot_scroll_timer.stop()
        elif key == "jm":
            self.host.jm_shutdown()

    def tick(self, now):
        if self.context.module_id == "calendar":
            self.host._check_reminders(now)
        elif self.context.module_id == "countdowns":
            self.host._update_countdown(now)
        elif self.context.module_id == "focus":
            self.host._tick_focus(now)

    def shown(self):
        if self.context.module_id == "calendar":
            self.host._calendar_selected(self.host.calendar.selectedDate())


def _page(module_id, title, builder, *, scroll=False, required=False,
          visible=True, manageable=True):
    return ModuleSpec(module_id, title,
                      lambda context: BuiltinPageModule(context, builder, scroll=scroll),
                      required=required, visible=visible, manageable=manageable,
                      retain_page=True)


# Ordering preserves the historical page slots. Navigation uses IDs, including
# all future extensions, so a new module never needs a magic page number.
BUILTIN_MODULES = (
    _page("dashboard", "概览", "_dashboard_page", required=True),
    _page("calendar", "日历提醒", "_calendar_page", scroll=True),
    _page("focus", "番茄钟", "_focus_page", scroll=True),
    _page("memos", "备忘录", "_memo_page"),
    _page("countdowns", "倒计时", "_countdowns_page"),
    _page("settings", "设置", "_settings_page", required=True),
    _page("anime", "看番提醒", "_anime_page"),
    _page("emojis", "表情包", "_emoji_page"),
    _page("jm", "JM漫画下载", "_jm_page", scroll=True, visible=False, manageable=False),
    _page("tarot", "占卜", "_tarot_page"),
)

NAVIGATION_ORDER = ("dashboard", "calendar", "focus", "memos", "countdowns",
                    "emojis", "anime", "tarot", "settings", "jm")
