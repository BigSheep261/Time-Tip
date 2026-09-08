import unittest
from datetime import datetime

from app.application.countdowns import collect_due, prepare_countdown
from app.domain.countdowns import countdown_snapshot, countdown_target, validate_cycle


class CycleTests(unittest.TestCase):
    def create(self, now=datetime(2026, 9, 8, 8), **changes):
        schedule = dict(cycle_start="09:30", cycle_end="17:30", frequency="daily", cycle_weekdays=[])
        schedule.update(changes)
        return prepare_countdown(None, "下班", "cyclic", now, schedule, now)

    def test_wait_start_finish_and_next_day(self):
        item = self.create()
        snapshot = countdown_snapshot(item, datetime(2026, 9, 8, 9))
        self.assertEqual((snapshot["state"], snapshot["text"]), ("waiting", "00天 08:00:00"))
        self.assertEqual(countdown_snapshot(item, datetime(2026, 9, 8, 9, 30))["state"], "running")
        self.assertEqual(countdown_snapshot(item, datetime(2026, 9, 8, 10, 30))["text"], "00天 07:00:00")
        end = datetime(2026, 9, 8, 17, 30)
        self.assertEqual(collect_due([item], end), ["下班"])
        self.assertEqual(collect_due([item], end), [])
        snapshot = countdown_snapshot(item, end)
        self.assertEqual(snapshot["state"], "waiting")
        self.assertEqual(snapshot["start"], datetime(2026, 9, 9, 9, 30))
        self.assertEqual(snapshot["text"], "00天 08:00:00")
        self.assertEqual(collect_due([item], datetime(2026, 9, 9, 17, 30)), ["下班"])

    def test_sleep_restart_and_clock_rollback_do_not_duplicate(self):
        item = self.create()
        # Wake the next morning: the latest missed ending is still delivered.
        self.assertEqual(collect_due([item], datetime(2026, 9, 9, 8)), ["下班"])
        persisted = dict(item)
        self.assertEqual(collect_due([persisted], datetime(2026, 9, 9, 8)), [])
        self.assertEqual(collect_due([persisted], datetime(2026, 9, 7, 18)), [])
        self.assertEqual(collect_due([persisted], datetime(2026, 10, 9, 8)), ["下班"])

    def test_weekday_and_weekly_overnight_schedules(self):
        item = self.create(frequency="weekdays")
        self.assertEqual(countdown_snapshot(item, datetime(2026, 9, 11, 18))["start"], datetime(2026, 9, 14, 9, 30))
        night = self.create(frequency="weekly", cycle_weekdays=[4], cycle_start="22:00", cycle_end="06:00")
        self.assertEqual(countdown_snapshot(night, datetime(2026, 9, 12, 1))["text"], "00天 05:00:00")
        self.assertEqual(countdown_snapshot(night, datetime(2026, 9, 12, 6))["start"], datetime(2026, 9, 18, 22))
        self.assertEqual(collect_due([night], datetime(2026, 9, 12, 6)), ["下班"])
        daily = self.create(cycle_start="22:00", cycle_end="06:00")
        self.assertEqual(countdown_target(daily, datetime(2026, 12, 31, 23)), datetime(2027, 1, 1, 6))

    def test_new_after_end_and_title_edit_do_not_replay(self):
        now = datetime(2026, 9, 8, 18)
        item = self.create(now)
        self.assertEqual(collect_due([item], now), [])
        edited = prepare_countdown(item, "新的标题", "cyclic", now, item, now)
        self.assertEqual(edited["notified_cycle"], item["notified_cycle"])
        self.assertEqual(collect_due([edited], now), [])

    def test_standard_stops_and_mode_switch_validates_past_target(self):
        item = dict(id="1", title="一次", target="2026-09-08T10:00:00", mode="standard")
        self.assertEqual(collect_due([item], datetime(2026, 9, 8, 10)), ["一次"])
        self.assertEqual(countdown_snapshot(item, datetime(2026, 9, 8, 9))["text"], "00天 00:00:00")
        with self.assertRaises(ValueError):
            prepare_countdown(self.create(), "一次", "standard", datetime(2026, 9, 8, 8), {}, datetime(2026, 9, 8, 9))

    def test_invalid_schedules(self):
        for changes in ({"cycle_end": "09:30"}, {"cycle_start": "25:00"}, {"frequency": "invalid"},
                        {"frequency": "weekly", "cycle_weekdays": []}, {"frequency": "weekly", "cycle_weekdays": [7]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.create(**changes)
