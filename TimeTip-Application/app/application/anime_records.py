"""Application-level normalization for persisted anime records.

Both persistence backends call this module so migrations and validation do not
silently diverge depending on how the application was started.
"""
from __future__ import annotations

from datetime import date, timedelta
import uuid
from typing import Any, Callable

from app.domain.anime import LOCAL_CATEGORIES, normalize_tags, validate_anime


IdFactory = Callable[[], str]


def normalize_anime_records(
    value: Any,
    *,
    today: date | None = None,
    id_factory: IdFactory | None = None,
) -> list[dict]:
    """Return valid, uniquely identified anime records from persisted input.

    Old TimeTip releases stored only a weekday for scheduled anime. Those
    records remain usable by assigning a wide compatibility date range instead
    of being discarded during the SQLite migration.
    """
    if not isinstance(value, list):
        return []

    current_day = today or date.today()
    make_id = id_factory or (lambda: uuid.uuid4().hex)
    default_end = current_day + timedelta(weeks=12)
    records: list[dict] = []
    seen_ids: set[str] = set()

    for source in value:
        if not isinstance(source, dict):
            continue

        item = source.copy()
        item.setdefault("category", "watching")
        legacy_schedule = (
            item.get("category") not in LOCAL_CATEGORIES
            and "start_date" not in source
            and isinstance(source.get("air_days"), list)
            and bool(source["air_days"])
        )

        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip() or item_id in seen_ids:
            item_id = _unique_id(make_id, seen_ids)
        item["id"] = item_id

        if legacy_schedule:
            item["air_days"] = [source["air_days"][0]]
            item["start_date"] = (current_day - timedelta(days=3650)).isoformat()
            item["end_date"] = (current_day + timedelta(days=3650)).isoformat()
            item["episode_count"] = 999
            item["legacy_compat"] = True

        item.setdefault("start_date", current_day.isoformat())
        item.setdefault("end_date", default_end.isoformat())
        item.setdefault("group", "未分组")
        item.setdefault("air_days", [0])
        item.setdefault("episode_count", 12)
        item.setdefault("progress", 0)
        item.setdefault("folder", "")
        item.setdefault("cover", "")
        item["tags"] = normalize_tags(item.get("tags", []))

        try:
            validate_anime(item)
        except ValueError:
            continue

        seen_ids.add(item_id)
        records.append(item)

    return records


def _unique_id(factory: IdFactory, seen_ids: set[str]) -> str:
    for _ in range(100):
        candidate = str(factory()).strip()
        if candidate and candidate not in seen_ids:
            return candidate
    # A broken injected factory should not make loading user data impossible.
    while (candidate := uuid.uuid4().hex) in seen_ids:
        pass
    return candidate
