"""Save and notification use cases shared by presentation and tests."""
import uuid
from datetime import datetime

from app.domain.countdowns import validate_cycle, countdown_due_period


def prepare_countdown(existing: dict | None, title: str, mode: str, target: datetime,
                      schedule: dict, now: datetime) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("请为倒计时填写名称。")
    if mode not in ("standard", "cyclic"):
        raise ValueError("请选择有效的倒计时类型。")
    result = dict(existing) if existing else {"id": uuid.uuid4().hex}
    changed_mode = existing is None or existing.get("mode", "standard") != mode
    result.update(title=title, mode=mode, target=target.isoformat())
    if mode == "standard":
        changed = changed_mode or existing.get("target") != target.isoformat()
        if changed and target <= now:
            raise ValueError("请选择晚于当前时间的目标。")
        if changed:
            result["notified"] = False
        for key in ("cycle_start", "cycle_end", "frequency", "cycle_weekdays", "notified_cycle"):
            result.pop(key, None)
    else:
        result.update({key: schedule[key] for key in ("cycle_start", "cycle_end", "frequency", "cycle_weekdays")})
        validate_cycle(result)
        changed = changed_mode or any(existing.get(key, default) != result.get(key, default)
                                      for key, default in (("cycle_start", "09:30"), ("cycle_end", "17:30"),
                                                           ("frequency", "daily"), ("cycle_weekdays", [])))
        result["notified"] = False
        if changed:
            ended = countdown_due_period(result, now)
            result["notified_cycle"] = ended[0] if ended else ""
    return result


def collect_due(items: list[dict], now: datetime) -> list[str]:
    """Advance notification state once; collapse missed cycles to one reminder."""
    due = []
    for item in items:
        if item.get("mode", "standard") == "cyclic":
            ended = countdown_due_period(item, now)
            if ended and ended[0] > item.get("notified_cycle", ""):
                item["notified_cycle"] = ended[0]
                due.append(item["title"])
        elif not item.get("notified") and datetime.fromisoformat(item["target"]) <= now:
            item["notified"] = True
            due.append(item["title"])
    return due
