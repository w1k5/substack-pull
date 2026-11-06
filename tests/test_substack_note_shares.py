"""Direct post shares must come from explicit Note attachments."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from substack_local.analytics.note import note_stats
from substack_local.analytics.note_shares import note_preview, note_text, post_note_shares
from substack_local.analytics.service import AnalyticsService


class PostNoteSharesTests(TestCase):
    def test_full_note_text_and_short_preview(self):
        body = "A first paragraph.\n\n" + "A second paragraph with more words. " * 10
        note = {"id": "c-11", "body": body}
        self.assertEqual(note_text(note), body.strip())
        self.assertEqual(len(note_preview(note)), 180)

        class Api:
            def get_json(self, path):
                self.path = path
                return {"cards": [{"cardId": "note", "note": {"note": note}}]}

        api = Api()
        result = note_stats(api, "11")
        self.assertEqual(api.path, "/api/v1/note_stats/c-11")
        self.assertEqual(result["full_text"], body.strip())
        self.assertEqual(result["preview"], note_preview(note))

    def test_only_authored_post_attachments_match(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory) / "published-notes" / "writer"
            notes = profile / "notes"
            notes.mkdir(parents=True)
            state = profile / ".sync" / "state.json"
            state.parent.mkdir()
            state.write_text(json.dumps({"last_sync_at": "2026-11-02T10:00:00Z"}))
            for note_id, author, kind, post_id in [
                ("11", "7", "post", "123"),
                ("12", "7", "comment", "123"),
                ("13", "7", "post", "999"),
                ("14", "8", "post", "123"),
            ]:
                (notes / f"{note_id}.json").write_text(json.dumps({
                    "profile": {"id": "7", "handle": "writer"},
                    "permalink": f"https://substack.com/@writer/note/c-{note_id}",
                    "note": {"id": note_id, "user_id": author, "date": "2026-11-01T12:00:00Z",
                             "attachments": [{"type": kind, "post": {"id": post_id}}]},
                }))
            result = post_note_shares(Path(directory) / "published-notes", "123")
            self.assertEqual(result["status"], "available")
            self.assertEqual([note["id"] for note in result["notes"]], ["11"])

    @patch("substack_local.analytics.service.note_stats", return_value={
        "interactions": {"items": [{"title": "Link click", "value": 131}]},
    })
    @patch("substack_local.analytics.service.post_note_shares", return_value={
        "status": "available", "last_sync_at": "2026-11-02T10:00:00Z",
        "notes": [{"id": "11", "link_clicks": None}],
    })
    @patch("substack_local.analytics.service.fetch_post", return_value={"id": "123"})
    def test_post_includes_note_link_clicks(self, fetch_post, shares, note_stats):
        service = AnalyticsService(object(), object())
        result = service.post("123")
        self.assertEqual(result["direct_note_shares"]["notes"][0]["link_clicks"], 131)
        self.assertEqual(note_stats.call_count, 1)

    def test_missing_backup_is_explicit(self):
        with TemporaryDirectory() as directory:
            result = post_note_shares(Path(directory) / "missing", "123")
            self.assertEqual(result, {"status": "not_synced", "last_sync_at": None, "notes": []})
