"""Pure countdown rules. Dates refer to the computer's local wall clock."""
from __future__ import annotations
import math
from datetime import datetime, timedelta
from .salary import parse_time


def countdown_text(target: datetime, now: datetime) -> str:
    seconds = max(0, math.ceil((target - now).total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days:02d}天 {hours:02d}:{minutes:02d}:{seconds:02d}"


def validate_cycle(item: dict) -> None:
    start, end = parse_time(item["cycle_start"]), parse_time(item["cycle_end"])
    if start == end:
        raise ValueError("循环倒计时的开始和结束时间不能相同。")
    frequency = item.get("frequency", "daily")
    if frequency not in ("daily", "weekdays", "weekly"):
        raise ValueError("请选择有效的循环周期。")
    if frequency == "weekly":
        days = item.get("cycle_weekdays", [])
        if not isinstance(days, list) or not days or any(type(d) is not int or d not in range(7) for d in days):
            raise ValueError("请至少选择一个循环日。")


def _windows(item: dict, now: datetime):
    validate_cycle(item)
    start, end = parse_time(item["cycle_start"]), parse_time(item["cycle_end"])
    frequency = item.get("frequency", "daily")
    days = range(7) if frequency == "daily" else (range(5) if frequency == "weekdays" else item["cycle_weekdays"])
    for offset in range(-8, 9):
        day = now.date() + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        begins, ends = datetime.combine(day, start), datetime.combine(day, end)
        if ends <= begins:
            ends += timedelta(days=1)
        yield begins, ends


def countdown_target(item: dict, now: datetime) -> datetime:
    if item.get("mode", "standard") != "cyclic":
        return datetime.fromisoformat(item["target"])
    return next(end for _, end in _windows(item, now) if end > now)


def countdown_cycle_key(item: dict, now: datetime) -> str:
    return countdown_target(item, now).isoformat(timespec="seconds")


def countdown_due_period(item: dict, now: datetime) -> tuple[str, datetime] | None:
    """Latest completed occurrence, including one missed during sleep/restart."""
    if item.get("mode", "standard") != "cyclic":
        return None
    ended = max((end for _, end in _windows(item, now) if end <= now), default=None)
    return (ended.isoformat(timespec="seconds"), ended) if ended else None


def cycle_description(item: dict) -> str:
    frequency = item.get("frequency", "daily")
    period = {"daily": "每天", "weekdays": "周一至周五"}.get(frequency)
    if period is None:
        period = "每周" + "、".join("一二三四五六日"[d] for d in sorted(set(item["cycle_weekdays"])))
    overnight = "（跨天）" if item["cycle_end"] < item["cycle_start"] else ""
    return f"{period} {item['cycle_start']}–{item['cycle_end']}{overnight}"


def countdown_snapshot(item: dict, now: datetime) -> dict:
    if item.get("mode", "standard") != "cyclic":
        target = datetime.fromisoformat(item["target"])
        finished = item.get("notified", False) or target <= now
        return {"state": "finished" if finished else "running", "target": target,
                "text": countdown_text(target, target if finished else now),
                "hint": "标准 · 已结束" if finished else "标准 · " + target.strftime("%Y.%m.%d %H:%M"),
                "detail": "目标时间已到，倒计时已停止。" if finished else "到达目标时间后提醒一次并停止。"}
    start, end = next((start, end) for start, end in _windows(item, now) if end > now)
    waiting = now < start
    return {"state": "waiting" if waiting else "running", "target": end, "start": start,
            "text": countdown_text(end, max(now, start)),
            "hint": "循环 · " + ("待开始 " + start.strftime("%m.%d %H:%M") if waiting else "进行中 · " + end.strftime("%H:%M") + " 结束"),
            "detail": cycle_description(item) + "\n" + ("时段开始后自动计时。" if waiting else "本轮结束后提醒，并等待下一轮。")}

