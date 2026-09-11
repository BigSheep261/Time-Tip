"""QSettings persistence and legacy migration."""
from __future__ import annotations
import json
import zipfile
import uuid
import shutil
from pathlib import Path
from datetime import date, datetime, timedelta
from app.domain.countdowns import validate_cycle
from app.domain.anime import validate_anime
from app.infrastructure.database import DataStore
from PyQt6.QtCore import QSettings, QDateTime, Qt

class Store:
    def __init__(self, path: str | None = None) -> None:
        self._backend = DataStore() if path is None else None
        self.settings = QSettings(path, QSettings.Format.IniFormat) if path else None

    def get(self, key: str, default: str = "") -> str:
        if self._backend: return self._backend.get(key, default)
        return str(self.settings.value(key, default))

    def set(self, key: str, value: str) -> None:
        if self._backend: self._backend.set(key, value); return
        self.settings.setValue(key, value)
        self.settings.sync()

    def reminders(self) -> list[dict[str, str]]:
        if self._backend: return self._backend.reminders()
        try:
            data = json.loads(self.get("reminders", "[]"))
            return [r for r in data if isinstance(r, dict) and "date" in r and "text" in r] if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def save_reminders(self, items: list[dict[str, str]]) -> None:
        if self._backend: self._backend.save_reminders(items); return
        self.set("reminders", json.dumps(items, ensure_ascii=False))

    def anime(self) -> list[dict]:
        if self._backend: return self._backend.anime()
        data = self.read_json("anime", [])
        if not isinstance(data, list): return []
        valid = []
        for source in data:
            if not isinstance(source, dict): continue
            item = source.copy()
            legacy_schedule = "start_date" not in source and bool(source.get("air_days"))
            item.setdefault("id", uuid.uuid4().hex)
            if legacy_schedule:
                item["air_days"] = [source["air_days"][0]]
                item["start_date"] = (date.today() - timedelta(days=3650)).isoformat()
                item["end_date"] = (date.today() + timedelta(days=3650)).isoformat()
                item["episode_count"] = 999
                item["legacy_compat"] = True
            item.setdefault("start_date", "2026-01-01"); item.setdefault("end_date", "2026-03-31"); item.setdefault("group", "未分组")
            item.setdefault("air_days", [0]); item.setdefault("episode_count", 12); item.setdefault("progress", 0); item.setdefault("folder", ""); item.setdefault("category", "watching"); item.setdefault("cover", "")
            try: validate_anime(item)
            except ValueError: continue
            valid.append(item)
        if valid != data: self.write_json("anime", valid)
        return valid

    def export_data(self, path: str) -> None:
        if self._backend:
            self._backend.export_data(path); return
        payload = {"version": 2, "settings": {}, "collections": {}}
        for key in ("work", "break", "salary", "widgets", "window_geometry", "date_format", "theme", "target", "target_notified", "memo"):
            payload["settings"][key] = self.get(key, "")
        for key in ("countdowns", "memos", "reminders", "anime", "anime_groups"):
            payload["collections"][key] = self.read_json(key, [])
        if Path(path).suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive: archive.writestr("data.json", json.dumps(payload, ensure_ascii=False, indent=2))
        else: Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_data(self, path: str) -> None:
        if self._backend:
            self._backend.import_data(path); return
        if Path(path).suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive: payload = json.loads(archive.read("data.json").decode("utf-8"))
        else: payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict) or not isinstance(payload.get("collections"), dict):
            raise ValueError("数据文件格式不受支持。")
        for key, value in payload["settings"].items():
            if key in ("work", "break", "salary", "widgets", "window_geometry", "date_format", "theme", "target", "target_notified", "memo"): self.set(key, value)
        for key, value in payload["collections"].items():
            if key in ("countdowns", "memos", "reminders", "anime", "anime_groups"): self.write_json(key, value)

    def save_anime(self, items: list[dict]) -> None:
        if self._backend: self._backend.save_anime(items); return
        self.write_json("anime", items)

    def save_cover(self, source: str, item_id: str) -> str:
        if self._backend: return self._backend.save_cover(source, item_id)
        source_path = Path(source)
        if not source_path.is_file(): return ""
        cover_dir = Path(self.settings.fileName()).resolve().parent / "covers"
        cover_dir.mkdir(parents=True, exist_ok=True)
        destination = cover_dir / (item_id + source_path.suffix.lower())
        if source_path.resolve() != destination.resolve():
            shutil.copyfile(source_path, destination)
        return str(destination)

    def read_json(self, key, default):
        if self._backend: return self._backend.read_json(key, default)
        try:
            return json.loads(self.get(key, json.dumps(default)))
        except (ValueError, TypeError):
            return default

    def write_json(self, key, value):
        if self._backend: self._backend.write_json(key, value); return
        self.set(key, json.dumps(value, ensure_ascii=False))

    def migrate_collections(self):
        if self._backend:
            # The SQLite backend has already migrated legacy registry data.
            return
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


