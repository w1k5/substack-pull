"""The dashboard and MCP use one set of Note comparison calculations."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from substack_local.analytics.cache import NoteDiskCache
from substack_local.analytics.note_comparison import note_comparison_metrics, summarize_note_cohort
from substack_local.analytics.service import AnalyticsService


def stats(note_id: str, impressions: int, actual: int, typical: int,
          audience: int = 200) -> dict:
    return {
        "id": note_id,
        "impressions": impressions,
        "impression_series": [
            {"is_primary": True, "points": [
                {"timestamp": "2026-11-01T00:00:00Z", "value": 0},
                {"timestamp": "2026-11-03T00:00:00Z", "value": actual}]},
            {"is_primary": False, "points": [
                {"timestamp": "2026-11-01T00:00:00Z", "value": 0},
                {"timestamp": "2026-11-03T00:00:00Z", "value": typical}]},
        ],
        "interactions": {"items": [
            {"title": "Profile visit", "value": 20},
            {"title": "Like", "value": 30},
            {"title": "Reply", "value": 5},
            {"title": "Link click", "value": 10},
        ]},
        "audience": [{"title": "Unconnected", "value": audience * .75},
                     {"title": "Subscribers", "value": audience * .25}],
    }


class NoteComparisonTests(TestCase):
    def test_rates_pace_and_sample_floors(self):
        measured = note_comparison_metrics(stats("1", 1000, 1200, 600))
        self.assertEqual(measured["pace"], {
            "actual": 1200.0, "typical": 600.0, "age": "48h",
            "ratio": 2.0, "label": "+100% vs typical"})
        self.assertEqual(measured["visitRate"], 20)
        self.assertEqual(measured["responseRate"], 35)
        self.assertEqual(measured["clickRate"], 10)
        self.assertEqual(measured["unconnected"], .75)
        small = note_comparison_metrics(stats("2", 99, 50, 100, audience=99))
        self.assertIsNone(small["visitRate"])
        self.assertIsNone(small["unconnected"])

    def test_cohort_ranking_and_standouts(self):
        rows = [
            {"id": note_id, **note_comparison_metrics(stats(note_id, 1000, actual, 600))}
            for note_id, actual in (("1", 1200), ("2", 300), ("3", 900))
        ]
        result = summarize_note_cohort(rows)
        self.assertEqual(result["pace"]["ranked_ids"], ["1", "3", "2"])
        self.assertEqual(result["pace"]["median"], 1.5)
        self.assertEqual(result["responses"]["plotted"], 3)
        self.assertEqual(result["responses"]["standouts"], 2)

    def test_existing_disk_cache_gets_metrics_without_refetch(self):
        with TemporaryDirectory() as directory:
            cache = NoteDiskCache(Path(directory))
            cache.write("1", stats("1", 1000, 1200, 600))
            service = AnalyticsService(object(), object(), cache)
            with patch("substack_local.analytics.service.note_stats") as fetch:
                self.assertEqual(service.note("1")["comparison"]["pace"]["ratio"], 2)
                fetch.assert_not_called()

    def test_cohort_skips_unavailable_notes_and_reports_them(self):
        service = AnalyticsService(object(), object())
        events = [
            {"type": "note", "id": "1", "day": "2026-11-01", "title": "First"},
            {"type": "note", "id": "2", "day": "2026-11-02", "title": "Second"},
        ]
        def load(note_id):
            if note_id == "2":
                raise ValueError("unavailable")
            raw = stats("1", 1000, 1200, 600)
            return {**raw, "comparison": note_comparison_metrics(raw)}

        with patch.object(service, "dashboard", return_value={"publication_events": events}), \
             patch.object(service, "note", side_effect=load):
            cohort = service.note_cohort(30)
        self.assertEqual(cohort["total"], 2)
        self.assertEqual([row["id"] for row in cohort["rows"]], ["1"])
        self.assertEqual(cohort["unavailable_ids"], ["2"])

    def test_completed_note_cohort_is_reused(self):
        service = AnalyticsService(object(), object())
        events = [{"type": "note", "id": "1", "day": "2026-11-01", "title": "First"}]
        raw = stats("1", 1000, 1200, 600)
        with patch.object(service, "dashboard", return_value={"publication_events": events}) as dashboard, \
             patch.object(service, "note", return_value={**raw, "comparison": note_comparison_metrics(raw)}) as note:
            first = service.note_cohort(30)
            self.assertIs(first, service.note_cohort(30))
            self.assertEqual(dashboard.call_count, 1)
            self.assertEqual(note.call_count, 1)
            self.assertEqual(first["lenses"]["responses"]["plotted_ids"], ["1"])

    def test_retry_unavailable_rebuilds_cached_cohort(self):
        service = AnalyticsService(object(), object())
        events = [{"type": "note", "id": "1", "day": "2026-11-01", "title": "First"}]
        raw = stats("1", 1000, 1200, 600)
        calls = 0

        def load(_note_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError("temporarily unavailable")
            return {**raw, "comparison": note_comparison_metrics(raw)}

        with patch.object(service, "dashboard", return_value={"publication_events": events}), \
             patch.object(service, "note", side_effect=load):
            first = service.note_cohort(30)
            self.assertEqual(first["unavailable_ids"], ["1"])
            self.assertIs(first, service.note_cohort(30))
            retried = service.note_cohort(30, retry_unavailable=True)
            self.assertEqual([row["id"] for row in retried["rows"]], ["1"])
            self.assertEqual(calls, 2)
            self.assertIs(retried, service.note_cohort(30))
