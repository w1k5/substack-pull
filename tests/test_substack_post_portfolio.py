"""Completed first-week comparisons use one detail fetch and survive restarts."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
import json
from unittest.mock import patch

from substack_local.analytics.cache import PostWeekDiskCache
from substack_local.analytics.post import first_week_summary
from substack_local.analytics.service import AnalyticsService


def detail(views=600, signups=9):
    return {"posts": [{"id": 123, "post_date": "2026-09-01T12:00:00Z",
                       "type": "newsletter", "audience": "everyone",
                       "stats": {"firstWeekDailyStats": [{
                           "day_n": 6, "dt": "2026-09-07T00:00:00Z",
                           "cumulative_views": views, "cumulative_signups": signups,
                       }]}}]}


class FakeApi:
    def __init__(self):
        self.calls = []

    def get_json(self, path):
        self.calls.append(path)
        return detail()


class PostPortfolioTests(unittest.TestCase):
    def test_only_complete_first_week_is_used(self):
        post = detail()["posts"][0]
        self.assertIsNone(first_week_summary("123", post, today=date(2026, 9, 7)))
        self.assertEqual(first_week_summary("123", post, today=date(2026, 9, 8))["signups"], 9)

    def test_launch_and_later_week_use_the_same_completed_window(self):
        post = detail(views=1000, signups=8)["posts"][0]
        post["stats"]["firstWeekDailyStats"].insert(0, {
            "day_n": 0, "dt": "2026-09-01T00:00:00Z",
            "cumulative_views": 200, "cumulative_signups": 1,
        })
        summary = first_week_summary("123", post, today=date(2026, 9, 8))
        self.assertEqual(summary["launch_views"], 200)
        self.assertEqual(summary["later_week_views"], 800)
        self.assertEqual(summary["later_week_share"], .8)
        self.assertEqual([day["day"] for day in summary["daily"]], [1, 7])

    def test_old_week_cache_is_refetched_for_daily_view_data(self):
        with TemporaryDirectory() as directory:
            cache = PostWeekDiskCache(Path(directory) / "post-week")
            path = cache.directory / "123.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"schema_version": 1, "post_id": "123",
                                        "fetched_at": time.time(),
                                        "data": {"id": "123", "views": 600, "signups": 9}}))
            self.assertIsNone(cache.read("123"))

    def test_portfolio_keeps_week_and_lifetime_metrics_distinct(self):
        service = AnalyticsService(object(), object())
        published = [{"id": "123", "title": "Example", "date": "2026-09-01T12:00:00Z",
                      "views": 3000, "shares": 30, "likes": 90, "comments": 18,
                      "restacks": 12, "signups": 12}]
        week = first_week_summary("123", detail(views=1000, signups=8)["posts"][0],
                                  today=date(2026, 9, 8))
        with patch.object(service, "posts", return_value=published), \
             patch.object(service, "post_week", return_value=week):
            row = service.post_portfolio()["rows"][0]
        self.assertEqual(row["views"], 1000)
        self.assertEqual(row["later_views"], 2000)
        self.assertEqual(row["later_multiple"], 2)
        self.assertEqual(row["share_rate"], 10)
        self.assertEqual(row["likes_rate"], 30)
        self.assertEqual(row["comments_rate"], 6)
        self.assertEqual(row["restacks_rate"], 4)

    def test_one_detail_call_and_disk_cache_across_services(self):
        with TemporaryDirectory() as directory:
            api = FakeApi()
            cache = PostWeekDiskCache(Path(directory) / "post-week")
            first = AnalyticsService(api, object(), post_week_cache=cache)
            second = AnalyticsService(api, object(), post_week_cache=cache)
            self.assertEqual(first.post_week("123")["views"], 600)
            self.assertEqual(second.post_week("123")["signups"], 9)
            self.assertEqual(api.calls, ["/api/v1/post_management/detail/123"])

    def test_completed_portfolio_is_reused_until_refresh(self):
        service = AnalyticsService(object(), object())
        published = [{"id": "123", "title": "Example", "date": "2026-09-01T12:00:00Z",
                      "views": 3000, "shares": 30, "signups": 12}]
        week = first_week_summary("123", detail(views=1000, signups=8)["posts"][0],
                                  today=date(2026, 9, 8))
        with patch.object(service, "posts", return_value=published) as posts, \
             patch.object(service, "post_week", return_value=week) as week_fetch:
            first = service.post_portfolio()
            self.assertIs(first, service.post_portfolio())
            self.assertEqual(posts.call_count, 1)
            self.assertEqual(week_fetch.call_count, 1)
            service.post_portfolio(refresh=True)
            self.assertEqual(week_fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
