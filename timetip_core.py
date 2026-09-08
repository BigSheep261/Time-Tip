"""Compatibility exports for the domain layer."""
from app.domain.salary import DEFAULT_SALARY, parse_time, work_intervals, validate_salary, salary_snapshot
from app.domain.countdowns import countdown_text, countdown_target, countdown_cycle_key, countdown_due_period
from app.domain.layout import WIDGET_SIZES, pack_widgets
