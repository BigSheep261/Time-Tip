"""Salary calculation rules, independent of Qt."""
from __future__ import annotations
import calendar
import math
from datetime import date, datetime, time, timedelta

DEFAULT_SALARY = {
    "monthly": 0.0,
    "start": "09:00",
    "end": "18:00",
    "weekdays": [0, 1, 2, 3, 4],
    "break_enabled": True,
    "break_start": "12:00",
    "break_end": "13:00",
}


def parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def work_intervals(config: dict, day: date) -> list[tuple[datetime, datetime]]:
    start = datetime.combine(day, parse_time(config["start"]))
    end = datetime.combine(day, parse_time(config["end"]))
    if end <= start:
        end += timedelta(days=1)
    if not config.get("break_enabled"):
        return [(start, end)]
    pause = datetime.combine(day, parse_time(config["break_start"]))
    if pause < start:
        pause += timedelta(days=1)
    resume = datetime.combine(pause.date(), parse_time(config["break_end"]))
    if resume <= pause:
        resume += timedelta(days=1)
    if not start < pause < resume < end:
        raise ValueError("午休必须在上下班之间，且结束时间晚于开始时间。")
    return [(start, pause), (resume, end)]


def validate_salary(config: dict) -> None:
    monthly = float(config["monthly"])
    if not math.isfinite(monthly) or not 0 < monthly <= 100000000:
        raise ValueError("请输入大于 0 的月薪。")
    days = config["weekdays"]
    if not days or any(type(d) is not int or d not in range(7) for d in days):
        raise ValueError("请至少选择一个工作日。")
    if parse_time(config["start"]) == parse_time(config["end"]):
        raise ValueError("上下班时间不能相同。")
    work_intervals(config, date(2026, 1, 1))


def salary_snapshot(config: dict, now: datetime) -> dict:
    """Derive earnings from scheduled time, so sleep/restarts never lose seconds."""
    validate_salary(config)
    day = now.date()
    overnight = parse_time(config["end"]) < parse_time(config["start"])
    yesterday = day - timedelta(days=1)
    if overnight and now.time() < parse_time(config["start"]) and yesterday.weekday() in config["weekdays"]:
        day = yesterday
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    workdays = sum(date(day.year, day.month, d).weekday() in config["weekdays"] for d in range(1, days_in_month + 1))
    intervals = work_intervals(config, day)
    duration = sum((end - start).total_seconds() for start, end in intervals)
    daily = float(config["monthly"]) / workdays
    scheduled = day.weekday() in config["weekdays"]
    elapsed = sum(max(0, min((now - start).total_seconds(), (end - start).total_seconds())) for start, end in intervals) if scheduled else 0
    working = scheduled and any(start <= now < end for start, end in intervals)
    on_break = scheduled and len(intervals) == 2 and intervals[0][1] <= now < intervals[1][0]
    return {
        "status": "上班" if working else "下班",
        "detail": "午休中 · 暂停累计" if on_break else ("休息日" if not scheduled else ("正在累计" if working else ("今日工作已结束" if elapsed else "尚未上班"))),
        "earned": daily * min(elapsed / duration, 1),
        "daily": daily,
        "per_second": daily / duration,
        "elapsed": elapsed,
        "duration": duration,
        "workdays": workdays,
        "day": day,
    }


