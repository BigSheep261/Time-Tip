"""QSettings persistence and legacy migration."""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from app.domain.countdowns import validate_cycle
from PyQt6.QtCore import QSettings, QDateTime, Qt

class Store:
    def __init__(self, path: str | None = None) -> None:
        self.settings = QSettings(path, QSettings.Format.IniFormat) if path else QSettings("TimeTip", "TimeTip")

    def get(self, key: str, default: str = "") -> str:
        return str(self.settings.value(key, default))

    def set(self, key: str, value: str) -> None:
        self.settings.setValue(key, value)
        self.settings.sync()

    def reminders(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self.get("reminders", "[]"))
            return [r for r in data if isinstance(r, dict) and "date" in r and "text" in r] if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def save_reminders(self, items: list[dict[str, str]]) -> None:
        self.set("reminders", json.dumps(items, ensure_ascii=False))

    def read_json(self, key, default):
        try:
            return json.loads(self.get(key, json.dumps(default)))
        except (ValueError, TypeError):
            return default

    def write_json(self, key, value):
        self.set(key, json.dumps(value, ensure_ascii=False))

    def migrate_collections(self):
        # Keep the old keys as a recovery copy, and migrate only once (even after deleting all items).
        if not self.settings.contains("countdowns"):
            target = QDateTime.fromString(self.get("target"), Qt.DateFormat.ISODate)
            items = []
            if target.isValid():
                dt = target.toPyDateTime()
                items.append({"id": uuid.uuid4().hex, "title": "我的倒计时", "target": dt.isoformat(),
                              "mode": "standard", "notified": self.get("target_notified") == dt.isoformat()})
            self.write_json("countdowns", items)
        if not self.settings.contains("memos"):
            text = self.get("memo")
            self.write_json("memos", [{"id": uuid.uuid4().hex, "title": "我的备忘录", "text": text}] if text else [])


    def load_collection(self, key):
        data = self.read_json(key, [])
        if not isinstance(data, list):
            return []
        items, seen = [], set()
        for source in data:
            if not isinstance(source, dict):
                continue
            item = source.copy()
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id or item_id in seen:
                item_id = uuid.uuid4().hex
            item["id"] = item_id
            item["title"] = str(item.get("title", "未命名"))
            if key == "countdowns":
                try:
                    target = datetime.fromisoformat(item["target"])
                    if target.tzinfo:
                        target = target.astimezone().replace(tzinfo=None)
                    item["target"] = target.isoformat()
                    item.setdefault("mode", "standard")
                    if item["mode"] == "cyclic":
                        item.setdefault("cycle_start", "09:30")
                        item.setdefault("cycle_end", "17:30")
                        item.setdefault("frequency", "daily")
                        validate_cycle(item)
                        if not isinstance(item.get("notified_cycle", ""), str):
                            item["notified_cycle"] = ""
                    elif item["mode"] != "standard":
                        raise ValueError("Unknown countdown type")
                except (ValueError, TypeError, KeyError):
                    continue
            else:
                item["text"] = str(item.get("text", ""))
            seen.add(item_id)
            items.append(item)
        if items != data:
            self.write_json(key, items)
        return items

