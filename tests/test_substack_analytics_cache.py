"""The MCP and dashboard can reuse post and Note stats across process lifetimes."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch

from substack_local.analytics.cache import NoteDiskCache, PostDiskCache, PublishedPostsDiskCache
from substack_local.analytics.service import AnalyticsService


class NoteCacheTests(TestCase):
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
