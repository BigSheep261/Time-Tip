"""SQLite persistence and portable backups for installed TimeTip builds."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import sys
from typing import Any
import uuid
import zipfile

from app.application.anime_records import normalize_anime_records
from app.infrastructure.schema import BACKUP_VERSION, COLLECTION_KEYS, SETTING_KEYS


class DataStore:
    KEYS = SETTING_KEYS
    COLLECTIONS = COLLECTION_KEYS
    _REGISTRY_MIGRATION_KEY = "_migration.registry.v1"

    def __init__(self, root: str | os.PathLike[str] | None = None, *, migrate_legacy: bool = True):
        configured = os.environ.get("TIMETIP_DATA_DIR")
        if root:
            self.root = Path(root)
        elif configured:
            self.root = Path(configured)
        elif getattr(sys, "frozen", False):
            self.root = Path(sys.executable).resolve().parent / "data"
        else:
            self.root = Path.home() / "AppData/Local/TimeTip/data"

        self.root.mkdir(parents=True, exist_ok=True)
        self.covers = self.root / "covers"
        self.covers.mkdir(exist_ok=True)
        self.path = self.root / "timetip.sqlite3"
        self.db = sqlite3.connect(str(self.path), timeout=5)
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS collections (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.commit()
        self._closed = False
        if migrate_legacy:
            self._migrate_registry_once()

    def _migrate_registry_once(self) -> None:
        # Keep the SQLite backend independently testable; Qt is only needed
        # when an actual registry migration is attempted.
        from PyQt6.QtCore import QSettings

        marker = self.db.execute(
            "SELECT value FROM settings WHERE key=?", (self._REGISTRY_MIGRATION_KEY,)
        ).fetchone()
        if marker:
            return

        # Databases created by earlier SQLite releases have no marker. Any
        # existing user row means they were already migrated; never overwrite
        # newer values with stale registry data.
        has_data = self.db.execute(
            "SELECT EXISTS(SELECT 1 FROM settings WHERE key<>?) "
            "OR EXISTS(SELECT 1 FROM collections)",
            (self._REGISTRY_MIGRATION_KEY,),
        ).fetchone()[0]
        if has_data:
            with self.db:
                self._set_raw(self._REGISTRY_MIGRATION_KEY, "1")
            return

        legacy = QSettings("TimeTip", "TimeTip")
        with self.db:
            for key in self.KEYS:
                if legacy.contains(key):
                    self._set_raw(key, str(legacy.value(key)))

            if legacy.contains("countdowns"):
                self._write_json_raw("countdowns", self._legacy_json(legacy.value("countdowns"), []))
            if legacy.contains("memos"):
                self._write_json_raw("memos", self._legacy_json(legacy.value("memos"), []))

            if not self._read_json_raw("countdowns", None):
                target = str(legacy.value("target", ""))
                if target:
                    notified_value = str(legacy.value("target_notified", ""))
                    self._write_json_raw(
                        "countdowns",
                        [{
                            "id": "legacy",
                            "title": "我的倒计时",
                            "target": target,
                            "mode": "standard",
                            "notified": notified_value == target,
                        }],
                    )
            if not self._read_json_raw("memos", None):
                memo = str(legacy.value("memo", ""))
                if memo:
                    self._write_json_raw(
                        "memos", [{"id": "legacy", "title": "我的备忘录", "text": memo}]
                    )
            self._set_raw(self._REGISTRY_MIGRATION_KEY, "1")

    @staticmethod
    def _legacy_json(value: Any, default: Any) -> Any:
        try:
            return json.loads(str(value))
        except (TypeError, ValueError):
            return default

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        with self.db:
            self._set_raw(key, value)

    def _set_raw(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def read_json(self, key: str, default: Any) -> Any:
        return self._read_json_raw(key, default)

    def _read_json_raw(self, key: str, default: Any) -> Any:
        row = self.db.execute("SELECT value FROM collections WHERE name=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, ValueError):
            return default

    def write_json(self, key: str, value: Any) -> None:
        serialized = json.dumps(value, ensure_ascii=False)
        with self.db:
            self._write_json_raw(key, value, serialized=serialized)

    def _write_json_raw(self, key: str, value: Any, *, serialized: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO collections(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (key, serialized if serialized is not None else json.dumps(value, ensure_ascii=False)),
        )

    def reminders(self) -> list[dict]:
        value = self.read_json("reminders", [])
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict) and "date" in item and "text" in item]

    def save_reminders(self, items: list[dict]) -> None:
        self.write_json("reminders", items)

    def anime(self) -> list[dict]:
        value = self.read_json("anime", [])
        result = normalize_anime_records(value)
        if result != value:
            self.write_json("anime", result)
        return result

    def save_anime(self, items: list[dict]) -> None:
        self.write_json("anime", items)

    def save_cover(self, source: str, item_id: str) -> str:
        source_path = Path(source)
        if not source_path.is_file():
            return ""
        destination = self.covers / (item_id + source_path.suffix.lower())
        if source_path.resolve() != destination.resolve():
            self._atomic_write(destination, source_path.read_bytes())
        return str(destination)

    def export_data(self, path: str) -> None:
        payload = {
            "version": BACKUP_VERSION,
            "settings": {key: self.get(key, "") for key in self.KEYS},
            "collections": {key: self.read_json(key, []) for key in self.COLLECTIONS},
        }
        cover_sources: dict[str, Path] = {}
        anime = payload["collections"].get("anime", [])
        if isinstance(anime, list):
            covers_root = self.covers.resolve()
            for item in anime:
                if not isinstance(item, dict):
                    continue
                cover = item.get("cover", "")
                source = Path(str(cover)) if cover else None
                if source and source.is_file() and source.resolve().is_relative_to(covers_root):
                    archive_name = "covers/" + source.name
                    cover_sources[archive_name] = source
                    item["cover"] = archive_name

        destination = Path(path)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            if destination.suffix.lower() == ".zip":
                with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("data.json", json.dumps(payload, ensure_ascii=False, indent=2))
                    for archive_name, source in cover_sources.items():
                        archive.write(source, archive_name)
                    for archive_name, source in self._emoji_sources(payload).items():
                        archive.write(source, archive_name)
            else:
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _emoji_sources(self, payload: dict) -> dict[str, Path]:
        sources: dict[str, Path] = {}
        root = (self.root / "emojis").resolve()
        records = payload["collections"].get("emojis", [])
        if not isinstance(records, list):
            return sources
        for record in records:
            if not isinstance(record, dict):
                continue
            relative = self._safe_relative(record.get("path", ""))
            if relative is None:
                continue
            source = (root / Path(*relative.parts)).resolve()
            if source.is_file() and source.is_relative_to(root):
                sources["emojis/" + relative.as_posix()] = source
        return sources

    def import_data(self, path: str) -> None:
        source = Path(path)
        if source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                try:
                    payload = json.loads(archive.read("data.json").decode("utf-8"))
                except KeyError as error:
                    raise ValueError("导入包缺少 data.json。") from error
                self._validate_payload(payload)
                self._restore_assets(archive, payload)
        else:
            payload = json.loads(source.read_text(encoding="utf-8"))
            self._validate_payload(payload)

        anime = payload["collections"].get("anime", [])
        for item in anime:
            cover = item.get("cover", "") if isinstance(item, dict) else ""
            normalized = self._safe_relative(cover)
            if normalized and normalized.parts[0] == "covers" and len(normalized.parts) == 2:
                item["cover"] = str(self.covers / normalized.name)

        with self.db:
            for key, value in payload["settings"].items():
                if key in self.KEYS:
                    self._set_raw(key, value)
            for key, value in payload["collections"].items():
                if key in self.COLLECTIONS:
                    self._write_json_raw(key, value)

    @classmethod
    def _validate_payload(cls, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise ValueError("数据文件格式不受支持。")
        version = payload.get("version", 1)
        if type(version) is not int or not 1 <= version <= BACKUP_VERSION:
            raise ValueError("数据文件版本不受支持。")
        if not isinstance(payload.get("settings"), dict) or not isinstance(
            payload.get("collections"), dict
        ):
            raise ValueError("数据文件格式不受支持。")
        for key, value in payload["collections"].items():
            if key in cls.COLLECTIONS and not isinstance(value, list):
                raise ValueError(f"数据集合 {key} 的格式不正确。")
        for key, value in payload["settings"].items():
            if key in cls.KEYS and isinstance(value, (dict, list)):
                raise ValueError(f"设置项 {key} 的格式不正确。")

    def _restore_assets(self, archive: zipfile.ZipFile, payload: dict) -> None:
        names = set(archive.namelist())
        anime = payload["collections"].get("anime", [])
        for item in anime:
            cover = item.get("cover", "") if isinstance(item, dict) else ""
            relative = self._safe_relative(cover)
            if not relative or relative.parts[0] != "covers" or len(relative.parts) != 2:
                continue
            archive_name = relative.as_posix()
            if archive_name in names:
                self._atomic_write(self.covers / relative.name, archive.read(archive_name))

        emoji_root = (self.root / "emojis").resolve()
        emojis = payload["collections"].get("emojis", [])
        for record in emojis:
            relative = self._safe_relative(record.get("path", "")) if isinstance(record, dict) else None
            if relative is None:
                continue
            archive_name = "emojis/" + relative.as_posix()
            destination = (emoji_root / Path(*relative.parts)).resolve()
            if archive_name in names and destination.is_relative_to(emoji_root):
                self._atomic_write(destination, archive.read(archive_name))

    @staticmethod
    def _safe_relative(value: Any) -> PurePosixPath | None:
        text = str(value).replace("\\", "/").strip()
        relative = PurePosixPath(text)
        if (
            not text
            or relative.is_absolute()
            or relative in (PurePosixPath("."), PurePosixPath(".."))
            or ".." in relative.parts
            or (relative.parts and relative.parts[0].endswith(":"))
        ):
            return None
        return relative

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def close(self) -> None:
        if not self._closed:
            self.db.close()
            self._closed = True
