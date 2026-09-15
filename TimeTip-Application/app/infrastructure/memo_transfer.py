"""Portable memo-only backups. Validation completes before anything is imported."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def export_memos(path: str, memos: list[dict]) -> None:
    payload = {
        "format": "timetip-memos", "version": 1,
        "exported_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "memos": memos,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_memos(path: str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and payload.get("format") == "timetip-memos":
        if payload.get("version") != 1:
            raise ValueError("此备忘录文件版本暂不支持。")
        records = payload.get("memos")
    elif isinstance(payload, dict) and isinstance(payload.get("collections"), dict):
        # Older full JSON backups can also supply just their memo collection.
        records = payload["collections"].get("memos")
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValueError("请选择 TimeTip 备忘录 JSON 文件。")
    if not isinstance(records, list):
        raise ValueError("文件中没有有效的备忘录列表。")
    result = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict) or not isinstance(record.get("title"), str):
            raise ValueError(f"第 {index} 条备忘录缺少有效标题。")
        if len(record["title"]) > 120:
            raise ValueError(f"第 {index} 条备忘录的标题不能超过 120 个字。")
        if not any(isinstance(record.get(key), str) for key in ("text", "html")):
            raise ValueError(f"第 {index} 条备忘录缺少有效内容。")
        item = {"title": record["title"], "text": record.get("text", "")}
        for key in ("text", "html", "edited_at", "saved_at"):
            if key not in record:
                continue
            value = record[key]
            if not isinstance(value, str):
                raise ValueError(f"第 {index} 条备忘录的 {key} 格式不正确。")
            if key.endswith("_at") and value:
                try:
                    datetime.fromisoformat(value)
                except ValueError as error:
                    raise ValueError(f"第 {index} 条备忘录的时间格式不正确。") from error
            item[key] = value
        result.append(item)
    return result
