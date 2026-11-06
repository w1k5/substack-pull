"""Published post interactions are fetched once per index, with archive fallback."""

from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from substack_local.analytics.publication import fetch_posts
from substack_local.analytics.client import PullError
from substack_local.analytics.cache import PublishedPostsDiskCache
from substack_local.analytics.service import AnalyticsService


class ArchiveApi:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get_json(self, path):
        self.calls.append(path)
        return self.pages[len(self.calls) - 1]


class PostIndexTests(TestCase):
    def test_counts_keep_restacks_separate_from_share_actions(self):
        published = [{"id": 101, "title": "One", "post_date": "2026-01-01",
                      "reaction_count": 9, "reactions": {"❤": 8}, "comment_count": 3,
                      "stats": {"views": 2000, "shares": 5}},
                     {"id": 102, "title": "Two", "post_date": "2026-01-02",
                      "reaction_count": 4, "comment_count": 2, "stats": {"views": 1000}}]
        archive = ArchiveApi([{"posts": [{"id": 101, "restacks": 7},
                                         {"id": 102, "restacks": 0}], "total": 2}])
        with patch("substack_local.analytics.publication.paginate_posts", return_value=published), \
             patch("substack_local.analytics.publication.ApiClient", return_value=archive):
            rows = fetch_posts(type("Auth", (), {"base_url": "https://example.substack.com"})())
        self.assertEqual((rows[0]["likes"], rows[0]["comments"], rows[0]["restacks"], rows[0]["shares"]),
                         (8, 3, 7, 5))
        self.assertEqual(rows[1]["restacks"], 0)
        self.assertEqual(len(archive.calls), 1)
        self.assertIn("/api/v1/archive?", archive.calls[0])

    def test_missing_archive_leaves_restacks_unknown(self):
        published = [{"id": 101, "reaction_count": 9, "comment_count": 3, "stats": {"shares": 5}}]
        archive = ArchiveApi([{"posts": [], "total": 0}])
        with patch("substack_local.analytics.publication.paginate_posts", return_value=published), \
             patch("substack_local.analytics.publication.ApiClient", return_value=archive):
            row = fetch_posts(type("Auth", (), {"base_url": "https://example.substack.com"})())[0]
        self.assertIsNone(row["restacks"])
        self.assertEqual(row["shares"], 5)

    def test_archive_error_preserves_authenticated_index(self):
        published = [{"id": 101, "reaction_count": 9, "comment_count": 3}]
        archive = ArchiveApi([])
        archive.get_json = lambda _path: (_ for _ in ()).throw(PullError("unavailable"))
        with patch("substack_local.analytics.publication.paginate_posts", return_value=published), \
             patch("substack_local.analytics.publication.ApiClient", return_value=archive):
            row = fetch_posts(type("Auth", (), {"base_url": "https://example.substack.com"})())[0]
        self.assertEqual((row["likes"], row["comments"], row["restacks"]), (9, 3, None))

    def test_post_story_uses_fresher_index_response_totals(self):
        with TemporaryDirectory() as directory:
            service = AnalyticsService(object(), object(),
                                       published_posts_cache=PublishedPostsDiskCache(Path(directory)))
            with patch("substack_local.analytics.service.fetch_post", return_value={
                "id": "101", "reach": {"views": 1000, "shares": 9},
                "engagement": {"likes": 5, "comments": 1},
            }), patch("substack_local.analytics.service.fetch_posts", return_value=[{
                "id": 101, "views": 1000, "likes": 8, "comments": 3, "restacks": 7,
            }]):
                post = service.post("101")
        self.assertEqual((post["engagement"]["likes"], post["engagement"]["comments"],
                          post["engagement"]["restacks"]), (8, 3, 7))
        self.assertEqual(post["insights"]["response_rates"]["restacks"], 7)
