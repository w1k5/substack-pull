"""The MCP and dashboard can reuse post and Note stats across process lifetimes."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch

from substack_local.analytics.cache import (
    NoteDiskCache, PostDiskCache, PublishedPostsDiskCache, PublicationDiskCache,
    prune_analytics_caches,
)
from substack_local.analytics.service import AnalyticsService


def publication_snapshot(day: str, days: int, views: int) -> dict:
    return {
        "publication": "https://example.substack.com", "refreshed_at": f"{day}T12:00:00-05:00",
        "range": {"start": day, "end": day, "days": days},
        "previous": {"range": {}, "totals": {}}, "totals": {"views": views},
        "series": [], "publication_events": [], "growth_sources": [],
        "subscriber_source_series": [], "traffic_sources": [], "posts": [],
    }


class PruningTests(TestCase):
    def test_expired_records_in_old_sessions_are_removed_and_fresh_records_survive(self):
        with TemporaryDirectory() as directory:
            host = Path(directory) / "example.substack.com"
            current = NoteDiskCache(host / ("a" * 24) / "notes")
            previous = PublishedPostsDiskCache(host / ("b" * 24) / "post-index")
            current.write("123", {"id": "123"})
            current.write("456", {"id": "456"})
            previous.write([{"id": 789}])
            stale = [current.directory / "123.json", previous.directory / "published.json"]
            for path in stale:
                record = json.loads(path.read_text(encoding="utf-8"))
                record["fetched_at"] -= 7200
                path.write_text(json.dumps(record), encoding="utf-8")

            self.assertEqual(prune_analytics_caches(host), 2)
            self.assertTrue((current.directory / "456.json").exists())
            self.assertTrue(all(not path.exists() for path in stale))

    def test_read_periodically_prunes_other_expired_records(self):
        with TemporaryDirectory() as directory:
            cache = NoteDiskCache(Path(directory) / "notes")
            cache.write("123", {"id": "123"})
            cache.write("456", {"id": "456"})
            stale = cache.directory / "123.json"
            record = json.loads(stale.read_text(encoding="utf-8"))
            record["fetched_at"] -= 3601
            stale.write_text(json.dumps(record), encoding="utf-8")
            cache._last_pruned -= 3601

            self.assertEqual(cache.read("456")["id"], "456")
            self.assertFalse(stale.exists())


class PublicationCacheTests(TestCase):
    @patch("substack_local.analytics.cache._publication_today", return_value="2026-11-04")
    @patch("substack_local.analytics.service.fetch_posts", return_value=[])
    @patch("substack_local.analytics.service.fetch_dashboard", side_effect=[
        publication_snapshot("2026-11-04", 30, 1),
        publication_snapshot("2026-11-04", 30, 2),
    ])
    def test_mcp_and_dashboard_processes_share_refresh(self, fetch, posts, _today):
        with TemporaryDirectory() as directory:
            cache = PublicationDiskCache(Path(directory) / "publication")
            first = AnalyticsService(object(), object(), publication_disk_cache=cache)
            second = AnalyticsService(object(), object(), publication_disk_cache=cache)

            self.assertEqual(first.dashboard(30)["totals"]["views"], 1)
            self.assertEqual(second.dashboard(30)["totals"]["views"], 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(posts.call_count, 1)
            self.assertEqual(second.dashboard(30, refresh=True)["totals"]["views"], 2)
            self.assertEqual(first.dashboard(30)["totals"]["views"], 2)
            self.assertEqual(fetch.call_count, 2)

    @patch("substack_local.analytics.cache._publication_today", return_value="2026-11-04")
    def test_expired_or_incomplete_snapshots_are_not_served(self, _today):
        with TemporaryDirectory() as directory:
            cache = PublicationDiskCache(Path(directory) / "publication")
            cache.write(30, publication_snapshot("2026-11-04", 30, 1))
            path = cache.directory / "30.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["fetched_at"] -= 301
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertIsNone(cache.read(30))

            record["fetched_at"] = time.time()
            del record["data"]["subscriber_source_series"]
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertIsNone(cache.read(30))

    @patch("substack_local.analytics.cache._publication_today", return_value="2026-11-04")
    def test_period_and_new_york_day_must_match(self, today):
        with TemporaryDirectory() as directory:
            cache = PublicationDiskCache(Path(directory) / "publication")
            cache.write(30, publication_snapshot("2026-11-04", 30, 1))
            self.assertIsNone(cache.read(7))
            today.return_value = "2026-11-05"
            self.assertIsNone(cache.read(30))


class NoteCacheTests(TestCase):
    @patch("substack_local.analytics.service.note_stats",
           side_effect=lambda _api, note_id: {"id": note_id, "impressions": 1})
    def test_memory_fallback_is_bounded_and_expired_entries_are_pruned(self, fetch):
        service = AnalyticsService(object(), object())
        for note_id in range(1, 75):
            service.note(str(note_id))
        self.assertEqual(len(service.note_cache), 64)
        self.assertNotIn("1", service.note_cache)
        service.note_cache["74"] = (time.monotonic() - 3601, {"id": "74"})
        self.assertEqual(service.note("74")["impressions"], 1)
        self.assertEqual(fetch.call_count, 75)
        self.assertLessEqual(len(service.note_cache), 64)

    @patch("substack_local.analytics.service.note_stats",
           side_effect=lambda _api, note_id: {"id": note_id, "impressions": 1})
    def test_disk_cache_avoids_duplicate_ram_copy_and_failed_write_uses_fallback(self, fetch):
        with TemporaryDirectory() as directory:
            cache = NoteDiskCache(Path(directory) / "notes")
            service = AnalyticsService(object(), object(), cache)
            service.note("456")
            self.assertFalse(service.note_cache)
            with patch.object(cache, "write", side_effect=OSError("cache unavailable")):
                service.note("789")
                service.note("789")
            self.assertEqual(fetch.call_count, 2)
            self.assertIn("789", service.note_cache)

    def test_note_cache_survives_new_service_and_refresh_replaces_it(self):
        with TemporaryDirectory() as directory, patch(
            "substack_local.analytics.service.note_stats",
            side_effect=[{"id": "456", "impressions": 1},
                         {"id": "456", "impressions": 2}],
        ) as fetch:
            cache = NoteDiskCache(Path(directory) / "notes")
            first = AnalyticsService(object(), object(), cache)
            second = AnalyticsService(object(), object(), cache)

            self.assertEqual(first.note("456")["impressions"], 1)
            self.assertEqual(second.note("456")["impressions"], 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(second.note("456", refresh=True)["impressions"], 2)
            self.assertEqual(first.note("456")["impressions"], 2)
            self.assertEqual(fetch.call_count, 2)

    def test_expired_and_invalid_records_are_refetched(self):
        with TemporaryDirectory() as directory, patch(
            "substack_local.analytics.service.note_stats",
            side_effect=[{"id": "456", "impressions": 1},
                         {"id": "456", "impressions": 2}],
        ) as fetch:
            cache = NoteDiskCache(Path(directory) / "notes")
            first = AnalyticsService(object(), object(), cache)
            self.assertEqual(first.note("456")["impressions"], 1)
            path = cache.directory / "456.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["fetched_at"] -= 3601
            path.write_text(json.dumps(record), encoding="utf-8")
            second = AnalyticsService(object(), object(), cache)
            self.assertEqual(second.note("456")["impressions"], 2)
            self.assertEqual(fetch.call_count, 2)
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(cache.read("456"))

    def test_mismatched_note_id_is_not_served(self):
        with TemporaryDirectory() as directory:
            cache = NoteDiskCache(Path(directory) / "notes")
            cache.directory.mkdir()
            (cache.directory / "456.json").write_text(json.dumps({
                "schema_version": 1, "note_id": "456", "fetched_at": time.time(),
                "data": {"id": "789", "impressions": 1},
            }), encoding="utf-8")
            self.assertIsNone(cache.read("456"))


class PostCacheTests(TestCase):
    @patch("substack_local.analytics.service.post_note_shares", return_value={
        "status": "available", "last_sync_at": None,
        "notes": [{"id": "456", "link_clicks": None}],
    })
    @patch("substack_local.analytics.service.note_stats", return_value={
        "id": "456", "impressions": 100,
        "interactions": {"items": [{"title": "Link click", "value": 4}]},
    })
    @patch("substack_local.analytics.service.fetch_post", side_effect=[
        {"id": "123", "reach": {"views": 1}},
        {"id": "123", "reach": {"views": 2}},
    ])
    def test_refreshing_post_reuses_linked_note_stats(self, fetch, note_fetch, _shares):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = AnalyticsService(
                object(), object(), NoteDiskCache(root / "notes"),
                PostDiskCache(root / "posts"),
            )
            self.assertEqual(service.post("123")["direct_note_shares"]["notes"][0]["link_clicks"], 4)
            self.assertEqual(service.post("123", refresh=True)["direct_note_shares"]["notes"][0]["link_clicks"], 4)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(note_fetch.call_count, 1)

    @patch("substack_local.analytics.service.post_note_shares", return_value={
        "status": "available", "last_sync_at": None, "notes": [],
    })
    @patch("substack_local.analytics.service.fetch_post", side_effect=[
        {"id": "123", "reach": {"views": 1}},
        {"id": "123", "reach": {"views": 2}},
    ])
    def test_post_cache_survives_restart_and_refresh_replaces_it(self, fetch, shares):
        with TemporaryDirectory() as directory:
            cache = PostDiskCache(Path(directory) / "posts")
            first = AnalyticsService(object(), object(), post_disk_cache=cache)
            second = AnalyticsService(object(), object(), post_disk_cache=cache)
            self.assertEqual(first.post("123")["reach"]["views"], 1)
            self.assertEqual(second.post("123")["reach"]["views"], 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertNotIn("direct_note_shares", cache.read("123"))
            self.assertEqual(second.post("123", refresh=True)["reach"]["views"], 2)
            self.assertEqual(first.post("123")["reach"]["views"], 2)
            self.assertEqual(fetch.call_count, 2)

    @patch("substack_local.analytics.service.fetch_posts", side_effect=[
        [{"id": 123, "views": 1}], [{"id": 123, "views": 2}],
    ])
    def test_published_index_survives_restart_and_refresh_replaces_it(self, fetch):
        with TemporaryDirectory() as directory:
            cache = PublishedPostsDiskCache(Path(directory) / "post-index")
            first = AnalyticsService(object(), object(), published_posts_cache=cache)
            second = AnalyticsService(object(), object(), published_posts_cache=cache)
            self.assertEqual(first.posts()[0]["views"], 1)
            self.assertEqual(second.posts()[0]["views"], 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(second.posts(refresh=True)[0]["views"], 2)
            self.assertEqual(first.posts()[0]["views"], 2)
            self.assertEqual(fetch.call_count, 2)

    def test_expired_post_and_index_records_are_not_used(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            post_cache = PostDiskCache(root / "posts")
            index_cache = PublishedPostsDiskCache(root / "post-index")
            post_cache.write("123", {"id": "123"})
            index_cache.write([{"id": 123}])
            for path, seconds in ((root / "posts/123.json", 3601),
                                  (root / "post-index/published.json", 901)):
                record = json.loads(path.read_text(encoding="utf-8"))
                record["fetched_at"] -= seconds
                path.write_text(json.dumps(record), encoding="utf-8")
            self.assertIsNone(post_cache.read("123"))
            self.assertIsNone(index_cache.read())
