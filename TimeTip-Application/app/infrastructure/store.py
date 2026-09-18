"""Persistence facade for SQLite and isolated INI compatibility profiles."""
from __future__ import annotations
import json
import zipfile
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from app.domain.countdowns import validate_cycle
from app.application.anime_records import normalize_anime_records
from app.infrastructure.database import DataStore
from app.infrastructure.schema import BACKUP_VERSION, COLLECTION_KEYS, SETTING_KEYS
from PyQt6.QtCore import QSettings, QDateTime, Qt

class Store:
    KEYS = SETTING_KEYS
    COLLECTIONS = COLLECTION_KEYS

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
        valid = normalize_anime_records(data)
        if valid != data: self.write_json("anime", valid)
        return valid

    def export_data(self, path: str) -> None:
        if self._backend:
            self._backend.export_data(path); return
        payload = {"version": BACKUP_VERSION, "settings": {}, "collections": {}}
        for key in self.KEYS:
            payload["settings"][key] = self.get(key, "")
        for key in self.COLLECTIONS:
            payload["collections"][key] = self.read_json(key, [])
        if Path(path).suffix.lower() == ".zip":
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("data.json", json.dumps(payload, ensure_ascii=False, indent=2))
                root = self.asset_root("emojis").resolve()
                for record in payload["collections"].get("emojis", []):
                    if not isinstance(record, dict): continue
                    relative = Path(str(record.get("path", "")))
                    source = (root / relative).resolve()
                    if not relative.is_absolute() and ".." not in relative.parts and source.is_file() and source.is_relative_to(root):
                        archive.write(source, "emojis/" + relative.as_posix())
        else: Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_data(self, path: str) -> None:
        if self._backend:
            self._backend.import_data(path); return
        if Path(path).suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                try:
                    payload = json.loads(archive.read("data.json").decode("utf-8"))
                except KeyError as error:
                    raise ValueError("导入包缺少 data.json。") from error
                DataStore._validate_payload(payload)
                root = self.asset_root("emojis").resolve()
                for name in archive.namelist():
                    if not name.startswith("emojis/") or name.endswith("/"): continue
                    relative = Path(name[7:])
                    destination = (root / relative).resolve()
                    if not relative.is_absolute() and ".." not in relative.parts and destination.is_relative_to(root):
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(archive.read(name))
        else: payload = json.loads(Path(path).read_text(encoding="utf-8"))
        DataStore._validate_payload(payload)
        for key, value in payload["settings"].items():
            if key in self.KEYS: self.set(key, value)
        for key, value in payload["collections"].items():
            if key in self.COLLECTIONS: self.write_json(key, value)

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

    def asset_root(self, name: str) -> Path:
        """Return a persistent local directory for binary user assets."""
        if self._backend:
            root = self._backend.root / name
        else:
            root = Path(self.settings.fileName()).resolve().parent / name
        root.mkdir(parents=True, exist_ok=True)
        return root

    def close(self) -> None:
        """Flush and release the active persistence backend."""
        if self._backend:
            self._backend.close()
        elif self.settings is not None:
            self.settings.sync()

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


