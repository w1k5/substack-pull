"""The Note planner must keep complete draft text for review and scheduling."""

import unittest
from pathlib import Path
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
    def test_drafts_include_complete_text_for_selection(self):
        planner = NotePlanner()
        planner._context = lambda: (FakeNotes(), None, Path("/tmp"), "UTC")

        drafts = planner.snapshot()["drafts"]

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["text"], "A" * 300)
        self.assertEqual(drafts[0]["preview"], "A" * 240)


if __name__ == "__main__":
    unittest.main()
