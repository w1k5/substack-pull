"""The prior-period comparison must use adjacent, equal-length date ranges."""

from datetime import date
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from substack_local.analytics.publication import fetch_dashboard, fetch_subscriber_source_series
from substack_local.analytics.service import AnalyticsService


class FakeApi:
    base_url = "https://example.substack.com"

    def __init__(self):
        self.requests = []

    def get_json(self, path):
        parsed = urlparse(path)
        query = parse_qs(parsed.query)
        self.requests.append((parsed.path, query))
        if parsed.path.endswith("/timeseries"):
            return []
        if parsed.path.endswith("/growth/events"):
            return {"pubEvents": []}
        previous = query.get("from_date") == ["2026-10-20"]
        if parsed.path.endswith("/growth/sources"):
            return {"sourceMetrics": [], "totals": [
                {"name": "traffic", "total": 80 if previous else 100},
                {"name": "subscribers", "total": 8 if previous else 12},
            ]}
        if parsed.path.endswith("/visitor_sources"):
            return {"rows": [{"source": "direct", "views": 25 if previous else 40}], "total": 1}
        raise AssertionError(f"Unexpected request: {path}")


class PublicationPeriodTests(TestCase):
    @patch("substack_local.analytics.publication.fetch_posts", return_value=[])
    def test_current_and_previous_periods_do_not_overlap(self, _posts):
        api = FakeApi()
        result = fetch_dashboard(api, 7, today=date(2026, 11, 2))

        self.assertEqual(result["range"], {"start": "2026-10-27", "end": "2026-11-02", "days": 7})
        self.assertEqual(result["previous"], {
            "range": {"start": "2026-10-20", "end": "2026-10-26"},
            "totals": {"views": 25, "visitors": 80, "subscribers": 8},
        })
        self.assertEqual(result["totals"], {"views": 40, "visitors": 100, "subscribers": 12})
        source_ranges = [
            (query["from_date"][0], query["to_date"][0])
            for path, query in api.requests if path.endswith("/visitor_sources")
        ]
        self.assertEqual(source_ranges, [("2026-10-27", "2026-11-02"), ("2026-10-20", "2026-10-26")])

    @patch("substack_local.analytics.publication.fetch_posts", side_effect=AssertionError("duplicate post index request"))
    def test_dashboard_uses_the_shared_published_post_index(self, _posts):
        rows = [{"id": 123, "title": "Cached post"}]
        result = fetch_dashboard(FakeApi(), 7, today=date(2026, 11, 2), post_rows=rows)
        self.assertEqual(result["posts"], rows)

    def test_source_series_selects_top_level_sources_without_their_children(self):
        class SeriesApi:
            def post_json(self, path, payload):
                self.path, self.payload = path, payload
                return {"timeseries": [{"source": "substack", "sourceName": "Substack",
                    "metrics": [{"name": "Subscribers", "total": 8,
                                 "timeseries": [{"date": "2026/11/01", "value": 3}]}]},
                    {"source": "direct", "sourceName": "Direct",
                     "metrics": [{"name": "Subscribers", "total": 2,
                                  "timeseries": [{"date": "2026/11/01", "value": 1}]}]}]}

        growth = {"sourceMetrics": [
            {"source": "substack", "metrics": [{"name": "Subscribers", "total": 8}],
             "children": [{"source": "notes", "metrics": [{"name": "Subscribers", "total": 5}]}]},
            {"source": "direct", "metrics": [{"name": "Subscribers", "total": 2}]},
        ]}
        api = SeriesApi()
        lines = fetch_subscriber_source_series(api, growth, "2026-10-27", "2026-11-02")
        self.assertEqual(api.path, "/api/v1/publication/stats/growth/partial-timeseries")
        self.assertEqual(api.payload["sources"], ["substack", "direct"])
        self.assertEqual(lines[0]["points"], [["2026-11-01", 3]])
        self.assertEqual([line["name"] for line in lines], ["Substack", "Direct"])


class PostRefreshTests(TestCase):
    @patch("substack_local.analytics.service.fetch_post", side_effect=[{"views": 1}, {"views": 2}])
    def test_explicit_refresh_bypasses_the_post_cache(self, fetch):
        service = AnalyticsService(api=object(), note_api=object())
        self.assertEqual(service.post("123")["views"], 1)
        self.assertEqual(service.post("123")["views"], 1)
        self.assertEqual(service.post("123", refresh=True)["views"], 2)
        self.assertEqual(fetch.call_count, 2)


class NoteRefreshTests(TestCase):
    @patch("substack_local.analytics.service.note_stats", side_effect=[{"impressions": 1}, {"impressions": 2}])
    def test_explicit_refresh_bypasses_the_note_cache(self, fetch):
        service = AnalyticsService(api=object(), note_api=object())
        self.assertEqual(service.note("456")["impressions"], 1)
        self.assertEqual(service.note("456")["comparison"]["impressions"], 1)
        self.assertEqual(service.note("456", refresh=True)["impressions"], 2)
        self.assertEqual(fetch.call_count, 2)
