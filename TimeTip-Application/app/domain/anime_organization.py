"""Grouping and ordering rules shared by the anime editor and list."""
from __future__ import annotations

UNGROUPED = "未分组"


def group_name(value) -> str:
    return str(value or "").strip() or UNGROUPED


def anime_groups(items, saved=()):
    names = {group_name(item.get("group")) for item in items}
    names.update(group_name(name) for name in saved if isinstance(name, str))
    names.discard(UNGROUPED)
    return [UNGROUPED, *sorted(names, key=str.casefold)]


def reorder_anime(items, visible_ids):
    """Reorder only visible slots, preserving every hidden entry's position."""
    by_id = {item["id"]: item for item in items}
    if len(by_id) != len(items) or len(set(visible_ids)) != len(visible_ids):
        raise ValueError("番剧标识重复，无法保存顺序。")
    if not set(visible_ids) <= by_id.keys():
        raise ValueError("番剧列表已变化，请重新调整顺序。")
    visible = set(visible_ids)
    ordered = iter(by_id[item_id] for item_id in visible_ids)
    return [next(ordered) if item["id"] in visible else item for item in items]
