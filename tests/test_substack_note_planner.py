"""The Note planner must keep complete draft text for review and scheduling."""

import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from substack_local.workflows.notes import NotePlanner


class FakeNotes:
    def load_private_notes(self, _directory):
        return [
            {"id": "draft", "body": "A" * 300, "edited_at": "2026-11-05"},
            {"id": "scheduled", "body": "Scheduled", "trigger_at": "2026-11-06"},
        ]

    def load_zone(self, _zone_name):
        return ZoneInfo("UTC")

    def runway_payload(self, *_args, **_kwargs):
        return {"events": []}

    def item_id(self, note):
        return note["id"]

    def note_body(self, note):
        return note["body"]

    def read_json(self, *_args):
        return {}


class NotePlannerSnapshotTests(unittest.TestCase):
    def test_simultaneous_identical_refreshes_share_one_sync(self):
        planner = NotePlanner()
        notes = Mock()
        planner._context = lambda: (notes, {}, Path("/tmp"), "UTC")
        planner.snapshot = Mock(return_value={"runway": {"days": 90}})
        started, waiting = Event(), Event()

        class ObservableFuture(Future):
            def result(self, timeout=None):
                waiting.set()
                return super().result(timeout)

        def sync(**_kwargs):
            started.set()
            self.assertTrue(waiting.wait(5))

        notes.PrivateNotesSync.return_value.sync.side_effect = sync
        with patch("substack_local.workflows.notes.Future", ObservableFuture), ThreadPoolExecutor(2) as pool:
            first = pool.submit(planner.refresh)
            self.assertTrue(started.wait(5))
            second = pool.submit(planner.refresh)
            self.assertIs(first.result(5), second.result(5))
        notes.PrivateNotesSync.return_value.sync.assert_called_once_with(days=90, minimum_spacing=3, export_runway=False)
        planner.snapshot.assert_called_once_with(days=90, spacing=3)

    def test_drafts_include_complete_text_for_selection(self):
        planner = NotePlanner()
        planner._context = lambda: (FakeNotes(), None, Path("/tmp"), "UTC")

        drafts = planner.snapshot()["drafts"]

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["text"], "A" * 300)
        self.assertEqual(drafts[0]["preview"], "A" * 240)


if __name__ == "__main__":
    unittest.main()
