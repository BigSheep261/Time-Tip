import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timetip_core import DEFAULT_SALARY, WIDGET_SIZES, countdown_text, pack_widgets, salary_snapshot, validate_salary


class SalaryTests(unittest.TestCase):
    def setUp(self):
        self.config = {**DEFAULT_SALARY, "monthly": 22000}

    def snapshot(self, hour, minute=0, second=0, day=7):
        return salary_snapshot(self.config, datetime(2026, 9, day, hour, minute, second))

    def test_full_workday_and_second_precision(self):
        self.assertEqual(self.snapshot(8)["earned"], 0)
        self.assertEqual(self.snapshot(9)["status"], "上班")
        self.assertEqual(self.snapshot(9)["workdays"], 22)
        self.assertAlmostEqual(self.snapshot(10)["earned"], 125)
        self.assertAlmostEqual(self.snapshot(10, 0, 1)["earned"] - self.snapshot(10)["earned"], 1000 / 28800)
        self.assertAlmostEqual(self.snapshot(18)["earned"], 1000)
        self.assertEqual(self.snapshot(18)["status"], "下班")
        self.assertEqual(self.snapshot(23)["earned"], self.snapshot(18)["earned"])

    def test_break_boundaries_freeze_and_resume(self):
        self.assertEqual(self.snapshot(12)["status"], "下班")
        self.assertIn("午休", self.snapshot(12)["detail"])
        self.assertEqual(self.snapshot(12)["earned"], self.snapshot(12, 59, 59)["earned"])
        self.assertEqual(self.snapshot(13)["status"], "上班")
        self.assertEqual(self.snapshot(12)["earned"], self.snapshot(13)["earned"])
        self.assertGreater(self.snapshot(13, 0, 1)["earned"], self.snapshot(13)["earned"])

    def test_weekends_and_new_day_reset(self):
        self.assertEqual(self.snapshot(14, day=6)["earned"], 0)
        self.assertEqual(self.snapshot(14, day=6)["detail"], "休息日")
        self.assertEqual(self.snapshot(0, day=8)["earned"], 0)

    def test_custom_workweek_and_no_break(self):
        self.config.update(weekdays=[5, 6], break_enabled=False)
        result = self.snapshot(14, day=6)
        self.assertEqual(result["workdays"], 8)
        self.assertEqual(result["status"], "上班")
        self.assertEqual(result["duration"], 9 * 3600)
        self.assertEqual(self.snapshot(14)["earned"], 0)

    def test_overnight_weekend_and_month_boundary(self):
        self.config.update(start="22:00", end="06:00", break_enabled=True, break_start="02:00", break_end="03:00")
        before_midnight = salary_snapshot(self.config, datetime(2026, 7, 31, 23))
        after_midnight = salary_snapshot(self.config, datetime(2026, 8, 1, 1))
        after_end = salary_snapshot(self.config, datetime(2026, 8, 1, 7))
        self.assertEqual(after_midnight["day"], before_midnight["day"])
        self.assertEqual(after_midnight["workdays"], 23)
        self.assertEqual(after_midnight["status"], "上班")
        self.assertAlmostEqual(after_midnight["earned"], before_midnight["earned"] * 3)
        self.assertAlmostEqual(after_end["earned"], 22000 / 23)
        self.assertEqual(after_end["status"], "下班")

    def test_invalid_settings_rejected(self):
        for change in [{"monthly": 0}, {"monthly": float("nan")}, {"weekdays": []}, {"weekdays": [7]},
                       {"start": "18:00"}, {"break_end": "19:00"}, {"break_start": "08:00"},
                       {"break_start": "13:00", "break_end": "12:00"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_salary({**self.config, **change})


class LayoutTests(unittest.TestCase):
    def test_packing_has_no_overlap_and_clamps_only_rendered_width(self):
        for columns in (2, 4):
            sizes = list(WIDGET_SIZES) * 5
            placements = pack_widgets(sizes, columns)
            cells = set()
            for row, col, width, height in placements:
                self.assertLessEqual(col + width, columns)
                for r in range(row, row + height):
                    for c in range(col, col + width):
                        self.assertNotIn((r, c), cells)
                        cells.add((r, c))
            self.assertEqual(sizes[3], (4, 1))

    def test_countdown_ceil_and_zero_clamp(self):
        target = datetime(2026, 9, 7, 12)
        self.assertEqual(countdown_text(target, datetime(2026, 9, 7, 11, 59, 59, 999999)), "00天 00:00:01")
        self.assertEqual(countdown_text(target, target), "00天 00:00:00")
        self.assertEqual(countdown_text(target, datetime(2026, 9, 8)), "00天 00:00:00")
