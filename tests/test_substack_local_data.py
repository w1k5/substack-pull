from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from substack_local.analytics.history import AnalyticsHistory
from substack_local.analytics.service import AnalyticsService
from substack_local.pullers.posts.storage import atomic_write_json
from substack_local.workflows import local_data


class LocalDataTests(TestCase):
    def test_export_uses_manifest_and_clear_leaves_history_and_backups(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            backup = root / "backup"
            state = backup / ".sync" / "state.json"
            atomic_write_json(state, {"categories": {"drafts": {
                "123": {"file": "drafts/123.json"},
                "456": {"file": "../secrets.json"},
            }}})
            atomic_write_json(root / "secrets.json", {"private": "excluded"})
            atomic_write_json(backup / "drafts/123.json", {"source": {"title": "<draft>"}})
            markdown = backup / "drafts/123.md"
            markdown.write_text("Draft text", encoding="utf-8")
            cache = root / "cache"
            relative = Path("example.substack.com") / ("a" * 24) / "notes/123.json"
            atomic_write_json(cache / relative, {})
            saved = root / "history" / relative
            atomic_write_json(saved, {})
            with patch.object(local_data, "_sources", return_value=[("Posts", "posts", backup, ".sync")]):
                stream = BytesIO()
                local_data.export_backups(stream)
                with ZipFile(stream) as archive:
                    self.assertEqual(set(archive.namelist()), {"index.html", "posts/drafts/123.json",
                                                              "posts/drafts/123.md"})
                    self.assertIn(b'<a href="posts/drafts/123.md">&lt;draft&gt;</a>',
                                  archive.read("index.html"))
                with self.assertRaises(LookupError):
                    local_data.backup_markdown("../secrets.json")
            with patch.object(local_data, "CACHE", cache):
                self.assertEqual(local_data.clear_temporary_cache(), 1)
            self.assertTrue(saved.exists())
            self.assertTrue(markdown.exists())

    def test_saved_note_keeps_exact_checkpoints_and_post_week_is_reused(self):
        with TemporaryDirectory() as temporary:
            history = AnalyticsHistory(Path(temporary))
            published = datetime(2026, 11, 1, tzinfo=timezone.utc)

            def point(hour, value):
                return {"timestamp": (published + timedelta(hours=hour)).isoformat(), "value": value}

            note = {"id": "123", "published_at": published.isoformat(), "impression_series": [
                {"is_primary": True, "points": [point(6, 25), point(23, 50), point(48, 81)]},
                {"is_primary": False, "points": [point(6, 20), point(48, 66)]},
            ]}
            history.note(note)
            note["impression_series"][0]["points"] = [point(6, 26)]
            history.note(note)
            self.assertEqual(history.read("notes", "123")["data"]["checkpoints"], {
                "6": {"impressions": 26, "typical_impressions": 20},
                "48": {"impressions": 81, "typical_impressions": 66},
            })
            week = {"id": "789", "views": 70, "signups": 2, "daily": [{"day": 7, "views": 70, "signups": 2}]}
            history.save("posts", "789", week)
            service = AnalyticsService(object(), object(), history=history)
            with patch("substack_local.analytics.service.fetch_post_week") as fetch:
                self.assertEqual(service.post_week("789"), week)
                fetch.assert_not_called()
