"""Pure schedule and progress rules for anime entries."""
from __future__ import annotations
from datetime import date, timedelta
import re
WEEKDAY_NAMES = "一二三四五六日"
CATEGORIES = (("backlog", "补番"), ("watching", "追番"), ("completed", "已看完"))
LOCAL_CATEGORIES = {"backlog", "completed"}

def normalize_tags(value) -> list[str]:
    """Convert user/imported tag values to a clean, bounded list."""
    if isinstance(value, str):
        values = re.split(r"[,，、;；\n]+", value)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return []
    result, seen = [], set()
    for raw in values:
        text = str(raw).strip()
        key = text.casefold()
        if text and key not in seen:
            result.append(text)
            seen.add(key)
    return result[:6]
def progress_number(item: dict) -> int:
    value = item.get("progress", 0)
    if isinstance(value, int): return value
    text = str(value)
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits or 0)

def validate_anime(item: dict) -> None:
    if not str(item.get("title", "")).strip(): raise ValueError("请填写番剧名称。")
    if item.get("category", "watching") not in dict(CATEGORIES): raise ValueError("请选择番剧分类。")
    tags = item.get("tags", [])
    if tags is not None:
        if not isinstance(tags, (list, tuple)): raise ValueError("标签格式不正确。")
        if len(tags) > 6: raise ValueError("最多添加 6 个标签。")
        if any(not isinstance(tag, str) or not tag.strip() for tag in tags): raise ValueError("标签不能为空。")
    # 补番和已看完都是本地清单，不需要设置放送日期或每周更新日。
    if item.get("category") in LOCAL_CATEGORIES:
        try: count = int(item.get("episode_count", 12))
        except (TypeError, ValueError): count = 0
        if not 1 <= count <= 999: raise ValueError("集数应在 1 到 999 之间。")
        try: progress = progress_number(item)
        except (TypeError, ValueError): progress = -1
        if not 0 <= progress <= count: raise ValueError("当前观看进度超出集数范围。")
        return
    days = item.get("air_days", [])
    if not isinstance(days, list) or len(days) != 1 or type(days[0]) is not int or days[0] not in range(7): raise ValueError("请选择一个每周放送日。")
    try:
        start = date.fromisoformat(item["start_date"]); end = date.fromisoformat(item["end_date"])
    except (KeyError, TypeError, ValueError): raise ValueError("请填写有效的放送开始和结束日期。")
    if end < start: raise ValueError("放送结束日期不能早于开始日期。")
    try: count = int(item.get("episode_count", 12))
    except (TypeError, ValueError): count = 0
    if not 1 <= count <= 999: raise ValueError("集数应在 1 到 999 之间。")
    try: progress = progress_number(item)
    except (TypeError, ValueError): progress = -1
    if not 0 <= progress <= count: raise ValueError("当前观看进度超出集数范围。")
def episode_dates(item: dict) -> list[date]:
    if item.get("category") in LOCAL_CATEGORIES: return []
    validate_anime(item); start = date.fromisoformat(item["start_date"]); end = date.fromisoformat(item["end_date"]); weekday = item["air_days"][0]; first = start + timedelta(days=(weekday - start.weekday()) % 7)
    return [day for index in range(int(item.get("episode_count", 12))) if (day := first + timedelta(days=index * 7)) <= end]
def anime_occurs_on(item: dict, day: date) -> bool:
    if item.get("category") in LOCAL_CATEGORIES: return False
    if item.get("category") == "completed" and progress_number(item) >= int(item.get("episode_count", 12)):
        return False
    # Compatibility for records from the previous time-of-day model.
    if "start_date" not in item or item.get("legacy_compat"):
        return day.weekday() in item.get("air_days", [])
    try: return day in episode_dates(item)
    except ValueError: return False
def anime_for_date(items: list[dict], day: date) -> list[dict]: return [item for item in items if anime_occurs_on(item, day)]
def anime_update_datetime(item: dict, day: date):
    from datetime import datetime, time
    raw = item.get("update_time", "00:00")
    hour, minute = map(int, str(raw).split(":")[:2])
    return datetime.combine(day, time(hour, minute))
def anime_days_text(item: dict) -> str: return "、".join("周" + WEEKDAY_NAMES[d] for d in item.get("air_days", []))
def episode_label(item: dict) -> str: return f"第 {progress_number(item)} 话"
