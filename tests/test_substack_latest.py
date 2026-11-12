"""Latest writing stays separate from the selected analytics period."""

import unittest
from unittest.mock import Mock, patch

from substack_local.analytics.publication import fetch_recent_notes
from substack_local.analytics.service import AnalyticsService


class RecentNotesTests(unittest.TestCase):
    def test_recent_notes_filters_invalid_events_and_sorts_newest_first(self):
        api = Mock()
        api.get_json.return_value = {"pubEvents": [
            {"id": "20", "type": "note", "date": "2026-11-05T12:00:00Z", "title": "Older"},
            {"id": "21", "type": "text", "date": "2026-11-06T12:00:00Z"},
            {"id": "abc", "type": "note", "date": "2026-11-06T12:00:00Z"},
            {"id": "22", "type": "note", "date": "2026-11-06T12:00:00Z", "title": "Newer"},
        ]}
        notes = fetch_recent_notes(api)
        self.assertEqual([note["id"] for note in notes], ["22", "20"])
        self.assertIn("/api/v1/publication/stats/growth/events", api.get_json.call_args.args[0])


class LatestWritingTests(unittest.TestCase):
    @patch("substack_local.analytics.service.post_note_shares", return_value={"notes": [{"id": "2"}]})
    @patch("substack_local.analytics.service.fetch_recent_notes")
    def test_latest_uses_index_counts_without_post_detail_request(self, fetch_notes, shares):
        fetch_notes.return_value = [
            {"id": "3", "title": "Third", "published_at": "2026-11-06T12:00:00+00:00"},
            {"id": "2", "title": "Second", "published_at": "2026-11-05T12:00:00+00:00"},
            {"id": "1", "title": "First", "published_at": "2026-11-03T12:00:00+00:00"},
        ]
        service = AnalyticsService(object(), object())
        service.posts = Mock(return_value=[
            {"id": "10", "title": "Old", "date": "2026-10-20T12:00:00Z"},
            {"id": "11", "title": "Latest", "date": "2026-11-04T12:00:00Z",
             "views": 14602, "signups": 271, "likes": 1023, "comments": 141, "shares": 160},
        ])
        service.post = Mock(side_effect=AssertionError("The home card should use the post index"))
        service.note = Mock(return_value={"preview": "A Note", "impressions": 123})
        latest = service.latest()
        self.assertEqual(latest["post"]["id"], "11")
        self.assertEqual([note["id"] for note in latest["notes"]], ["3", "2"])
        self.assertEqual(latest["notes_since_post"], 2)
        self.assertEqual(latest["notes"][1]["relation"], "links to latest post")
        self.assertEqual(latest["notes"][0]["relation"], "published after latest post")
        self.assertEqual(latest["notes"][0]["impressions"], 123)
        self.assertEqual([latest["post"][key] for key in
                          ("views", "signups", "likes", "comments", "shares")],
                         [14602, 271, 1023, 141, 160])
        self.assertIs(latest, service.latest())
        fetch_notes.assert_called_once()
        shares.assert_called_once()


if __name__ == "__main__":
    unittest.main()
