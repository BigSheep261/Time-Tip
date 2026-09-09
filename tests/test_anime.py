import unittest
from datetime import date, datetime
from app.domain.anime import anime_days_text, anime_for_date, anime_update_datetime, episode_dates, validate_anime
from app.domain.dates import format_dashboard_date

class AnimeDomainTests(unittest.TestCase):
    def setUp(self):
        self.item = {"title":"测试番", "air_days":[1,4], "air_start":"20:00", "air_end":"21:00", "update_time":"21:30", "progress":"第3集", "folder":"D:/Anime"}
    def test_schedule_and_update_time(self):
        self.assertEqual([a["title"] for a in anime_for_date([self.item], date(2026,9,8))], ["测试番"])
        self.assertEqual(anime_for_date([self.item], date(2026,9,9)), [])
        self.assertEqual(anime_update_datetime(self.item, date(2026,9,8)), datetime(2026,9,8,21,30))
        self.assertEqual(anime_days_text(self.item), "周二、周五")
    def test_date_based_weekly_episode_generation_and_completion(self):
        item = {"title":"十月新番", "category":"watching", "start_date":"2026-10-01", "end_date":"2026-12-31", "air_days":[1], "episode_count":12, "progress":0}
        self.assertEqual(episode_dates(item)[0], date(2026, 10, 6))
        self.assertEqual(len(episode_dates(item)), 12)
        self.assertEqual(episode_dates(item)[-1], date(2026, 12, 22))
        item["category"] = "completed"; item["progress"] = 12
        self.assertEqual(anime_for_date([item], date(2026, 10, 6)), [])

    def test_validation(self):
        for key, value in (("title", ""), ("air_days", []), ("update_time", "25:00"), ("air_end", "19:00")):
            bad = dict(self.item); bad[key] = value
            with self.assertRaises(ValueError): validate_anime(bad)
    def test_date_formats(self):
        now = datetime(2026,9,8,12)
        self.assertIn("星期二", format_dashboard_date(now, "full_cn"))
        self.assertEqual(format_dashboard_date(now, "japanese"), "2026年09月08日 · 火曜日")
        self.assertEqual(format_dashboard_date(now, "iso"), "2026-09-08 · 星期二")

if __name__ == "__main__": unittest.main()
