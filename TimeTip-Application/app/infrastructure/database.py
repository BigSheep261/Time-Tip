"""SQLite persistence for installed TimeTip builds."""
from __future__ import annotations
import json, os, sqlite3, sys, zipfile
from pathlib import Path
from typing import Any
from PyQt6.QtCore import QSettings
from app.domain.anime import normalize_tags, validate_anime

class DataStore:
    KEYS = ("work", "break", "salary", "widgets", "window_geometry", "date_format", "theme", "target", "target_notified", "memo", "update_auto_check")
    COLLECTIONS = ("countdowns", "memos", "reminders", "anime", "anime_groups", "emojis", "emoji_categories")
    def __init__(self, root: str | None = None):
        configured = os.environ.get("TIMETIP_DATA_DIR")
        if root: self.root = Path(root)
        elif configured: self.root = Path(configured)
        elif getattr(sys, "frozen", False): self.root = Path(sys.executable).resolve().parent / "data"
        else: self.root = Path.home() / "AppData/Local/TimeTip/data"
        self.root.mkdir(parents=True, exist_ok=True)
        self.covers = self.root / "covers"; self.covers.mkdir(exist_ok=True)
        self.path = self.root / "timetip.sqlite3"
        self.db = sqlite3.connect(str(self.path))
        self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS collections (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.commit()
        self._migrate_registry_once()
    def _migrate_registry_once(self):
        if self.db.execute("SELECT 1 FROM settings LIMIT 1").fetchone(): return
        legacy = QSettings("TimeTip", "TimeTip")
        for key in self.KEYS:
            if legacy.contains(key): self.set(key, str(legacy.value(key)))
        if legacy.contains("countdowns"):
            self.write_json("countdowns", self._legacy_json(legacy.value("countdowns"), []))
        if legacy.contains("memos"):
            self.write_json("memos", self._legacy_json(legacy.value("memos"), []))
        if not self.read_json("countdowns", None):
            target = legacy.value("target", "")
            if target:
                self.write_json("countdowns", [{"id": "legacy", "title": "我的倒计时", "target": str(target), "mode": "standard", "notified": bool(legacy.value("target_notified", ""))}])
        if not self.read_json("memos", None):
            memo = legacy.value("memo", "")
            if memo: self.write_json("memos", [{"id": "legacy", "title": "我的备忘录", "text": str(memo)}])
    @staticmethod
    def _legacy_json(value, default):
        try: return json.loads(str(value))
        except (TypeError, ValueError): return default
    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    def set(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value))); self.db.commit()
    def read_json(self, key: str, default: Any):
        row = self.db.execute("SELECT value FROM collections WHERE name=?", (key,)).fetchone()
        if not row: return default
        try: return json.loads(row[0])
        except (TypeError, ValueError): return default
    def write_json(self, key: str, value: Any):
        self.db.execute("INSERT INTO collections(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False))); self.db.commit()
    def reminders(self):
        value = self.read_json("reminders", []); return [r for r in value if isinstance(r, dict) and "date" in r and "text" in r] if isinstance(value, list) else []
    def save_reminders(self, items): self.write_json("reminders", items)
    def anime(self):
        value = self.read_json("anime", [])
        if not isinstance(value, list): return []
        result = []
        for source in value:
            if not isinstance(source, dict): continue
            item = source.copy()
            item.setdefault("id", os.urandom(8).hex()); item.setdefault("start_date", "2026-01-01"); item.setdefault("end_date", "2026-03-31"); item.setdefault("group", "未分组")
            item.setdefault("air_days", [0]); item.setdefault("episode_count", 12); item.setdefault("progress", 0); item.setdefault("folder", ""); item.setdefault("category", "watching"); item.setdefault("cover", "")
            item["tags"] = normalize_tags(item.get("tags", []))
            try: validate_anime(item)
            except ValueError: continue
            result.append(item)
        if result != value: self.write_json("anime", result)
        return result
    def save_anime(self, items): self.write_json("anime", items)
    def save_cover(self, source: str, item_id: str) -> str:
        source_path = Path(source)
        if not source_path.is_file(): return ""
        destination = self.covers / (item_id + source_path.suffix.lower())
        destination.write_bytes(source_path.read_bytes())
        return str(destination)
    def export_data(self, path: str) -> None:
        payload = {"version": 2, "settings": {}, "collections": {}}
        for key in self.KEYS: payload["settings"][key] = self.get(key, "")
        for key in self.COLLECTIONS: payload["collections"][key] = self.read_json(key, [])
        for item in payload["collections"].get("anime", []):
            cover = item.get("cover", "")
            source = Path(cover) if cover else None
            if source and source.is_file() and source.resolve().is_relative_to(self.covers.resolve()): item["cover"] = "covers/" + source.name
        destination = Path(path)
        if destination.suffix.lower() == ".zip":
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("data.json", json.dumps(payload, ensure_ascii=False, indent=2))
                for item in payload["collections"]["anime"]:
                    cover = item.get("cover", "")
                    if cover:
                        source = Path(cover)
                        if source.is_file() and source.resolve().is_relative_to(self.covers.resolve()): archive.write(source, "covers/" + source.name)
                root = (self.root / "emojis").resolve()
                for record in payload["collections"].get("emojis", []):
                    if not isinstance(record, dict): continue
                    relative = Path(str(record.get("path", "")))
                    source = (root / relative).resolve()
                    if not relative.is_absolute() and ".." not in relative.parts and source.is_file() and source.is_relative_to(root):
                        archive.write(source, "emojis/" + relative.as_posix())
        else: destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    def import_data(self, path: str) -> None:
        source = Path(path)
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                names = set(archive.namelist())
                if "data.json" not in names: raise ValueError("导入包缺少 data.json。")
                payload = json.loads(archive.read("data.json").decode("utf-8"))
                for name in names:
                    if name.startswith("covers/") and not name.endswith("/"):
                        safe = Path(name).name
                        (self.covers / safe).write_bytes(archive.read(name))
                    elif name.startswith("emojis/") and not name.endswith("/"):
                        relative = Path(name[7:])
                        root = (self.root / "emojis").resolve()
                        destination = (root / relative).resolve()
                        if not relative.is_absolute() and ".." not in relative.parts and destination.is_relative_to(root):
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            destination.write_bytes(archive.read(name))
        else: payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict) or not isinstance(payload.get("collections"), dict): raise ValueError("数据文件格式不受支持。")
        for item in payload["collections"].get("anime", []):
            if isinstance(item, dict) and str(item.get("cover", "")).startswith("covers/"):
                item["cover"] = str(self.covers / Path(item["cover"]).name)
        self.db.execute("BEGIN")
        try:
            for key, value in payload["settings"].items():
                if key in self.KEYS: self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            for key, value in payload["collections"].items():
                if key in self.COLLECTIONS: self.db.execute("INSERT INTO collections(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
    def close(self): self.db.close()
