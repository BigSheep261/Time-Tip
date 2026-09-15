"""Standalone ZIP import/export for the local emoji library."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path


def export_emoji_package(path: str, categories: list[dict], emojis: list[dict], root: Path) -> None:
    payload = {"format": "timetip-emojis", "version": 1, "categories": categories, "emojis": emojis}
    destination = Path(path)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(payload, ensure_ascii=False, indent=2))
        root = root.resolve()
        for record in emojis:
            relative = Path(str(record.get("path", "")))
            source = (root / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not source.is_file() or not source.is_relative_to(root):
                continue
            archive.write(source, "emojis/" + relative.as_posix())


def read_emoji_package(path: str) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    with zipfile.ZipFile(Path(path)) as archive:
        try:
            payload = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("表情包导入包缺少有效的 manifest.json。") from error
        if not isinstance(payload, dict) or payload.get("format") != "timetip-emojis" or payload.get("version") != 1:
            raise ValueError("此表情包导入包版本不受支持。")
        categories = payload.get("categories")
        emojis = payload.get("emojis")
        if not isinstance(categories, list) or not isinstance(emojis, list):
            raise ValueError("表情包导入包格式不完整。")
        category_ids = set()
        valid_categories = []
        for category in categories:
            if not isinstance(category, dict):
                raise ValueError("表情包分类格式不正确。")
            category_id, name = str(category.get("id", "")).strip(), str(category.get("name", "")).strip()
            if not category_id or not name or category_id in category_ids:
                raise ValueError("表情包分类包含重复或空值。")
            category_ids.add(category_id)
            valid_categories.append({"id": category_id, "name": name[:40]})
        assets = {}
        valid_emojis = []
        names = set(archive.namelist())
        for record in emojis:
            if not isinstance(record, dict):
                raise ValueError("表情包图片记录格式不正确。")
            record_id = str(record.get("id", "")).strip()
            relative = Path(str(record.get("path", "")))
            category_id = str(record.get("category_id", ""))
            archive_name = "emojis/" + relative.as_posix()
            if (not record_id or relative.is_absolute() or ".." in relative.parts or
                    category_id not in category_ids or relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"} or
                    archive_name not in names):
                raise ValueError("表情包图片记录或资源文件无效。")
            valid_emojis.append({"id": record_id, "path": relative.as_posix(), "category_id": category_id})
            assets[relative.as_posix()] = archive.read(archive_name)
        return valid_categories, valid_emojis, assets
