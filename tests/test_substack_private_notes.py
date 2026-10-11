from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SCRIPT_DIR = ROOT / "skills" / "substack-notes-pull" / "scripts"
sys.path.insert(0, str(PRIVATE_SCRIPT_DIR))

from substack_draft_notes import (
    KEYCHAIN_SERVICE,
    LEGACY_KEYCHAIN_ACCOUNT,
    LEGACY_KEYCHAIN_SERVICE,
    PrivateApiClient,
    PrivateNotesSync,
    api_timestamp,
    load_private_notes,
    notes_overview,
    paginate_private_notes,
    parse_schedule_at,
    publication_account,
    runway_payload,
    schedule_payload,
    session_candidates,
    write_runway,
)
from zoneinfo import ZoneInfo


def private_note(
    note_id: int,
    body: str,
    *,
    trigger_at: str | None = None,
    edited_at: str = "2026-10-09T12:00:00.000Z",
) -> dict:
    return {
        "id": note_id,
        "user_id": 700,
        "type": "feed",
        "date": "2026-10-01T12:00:00.000Z",
        "edited_at": edited_at,
        "trigger_at": trigger_at,
        "ancestor_path": "",
        "body": body,
        "body_json": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}],
                }
            ],
        },
        "attachments": [],
    }


class FakeApi:
    def __init__(self, pages: list[list[dict]]):
        self.pages = pages
        self.paths: list[str] = []

    def get_json(self, path: str):
        self.paths.append(path)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)
        cursor = query.get("cursor", [None])[0]
        index = int(cursor.removeprefix("page-")) if cursor else 0
        next_cursor = f"page-{index + 1}" if index + 1 < len(self.pages) else None
        return {
            "drafts": self.pages[index],
            "hasMore": next_cursor is not None,
            "nextCursor": next_cursor,
        }


class PrivatePaginationTests(unittest.TestCase):
    def test_follows_cursor_until_has_more_is_false(self):
        api = FakeApi(
            [
                [private_note(1, "Draft")],
                [private_note(2, "Scheduled", trigger_at="2026-10-13T13:00:00Z")],
            ]
        )

        notes = paginate_private_notes(api)

        self.assertEqual([note["id"] for note in notes], [1, 2])
        self.assertEqual(len(api.paths), 2)
        self.assertIn("cursor=page-1", api.paths[1])


class SharedAuthenticationTests(unittest.TestCase):
    def test_reuses_substack_pull_keychain_account(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".substack-pull.json").write_text(
                json.dumps({"publication": "https://writer.substack.com"})
            )

            candidates = session_candidates(root / ".substack-notes-pull.json", {})

        self.assertEqual(candidates[0], (KEYCHAIN_SERVICE, "writer.substack.com"))
        self.assertEqual(
            candidates[-1], (LEGACY_KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_ACCOUNT)
        )

    def test_rejects_non_substack_authentication_hosts(self):
        with self.assertRaisesRegex(Exception, "substack.com"):
            publication_account("https://example.com")


class SchedulingTests(unittest.TestCase):
    class Response:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return self.payload

    def test_patch_uses_captured_substack_method_path_and_json(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return self.Response(b'{"ok":true}')

        client = PrivateApiClient(
            "test-session",
            base_url="http://127.0.0.1",
            request_delay=0,
            opener=opener,
        )
        payload = {"bodyJson": {"type": "doc"}, "trigger_at": "2026-10-30T13:30:00.000Z"}

        result = client.patch_json("/api/v1/feed/comment/123", payload)

        request = captured["request"]
        self.assertEqual(request.get_method(), "PATCH")
        self.assertEqual(request.full_url, "http://127.0.0.1/api/v1/feed/comment/123")
        self.assertEqual(json.loads(request.data), payload)
        self.assertEqual(result, {"ok": True})

    def test_schedule_payload_preserves_body_role_and_attachments(self):
        note = private_note(12, "Scheduled body")
        note["attachments"] = [{"id": "attachment-1", "type": "image"}]
        scheduled = datetime(2026, 10, 30, 13, 30, tzinfo=timezone.utc)

        payload = schedule_payload(note, scheduled)

        self.assertEqual(payload["bodyJson"], note["body_json"])
        self.assertEqual(payload["replyMinimumRole"], "everyone")
        self.assertEqual(payload["attachmentIds"], ["attachment-1"])
        self.assertEqual(payload["trigger_at"], "2026-10-30T13:30:00.000Z")

    def test_naive_schedule_time_uses_configured_timezone(self):
        scheduled = parse_schedule_at(
            "2026-10-30 09:30",
            "America/New_York",
            now=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc),
        )

        self.assertEqual(api_timestamp(scheduled), "2026-10-30T13:30:00.000Z")


class RunwayTests(unittest.TestCase):
    def test_classifies_drafts_and_uses_local_scheduled_dates(self):
        notes = [
            private_note(1, "Draft"),
            private_note(2, "Late UTC", trigger_at="2026-11-08T01:21:00Z"),
            private_note(3, "Same local day", trigger_at="2026-11-07T14:00:00Z"),
            private_note(4, "Later", trigger_at="2026-11-10T17:00:00Z"),
        ]

        payload = runway_payload(
            notes,
            start=date(2026, 11, 1),
            days=30,
            zone_name="America/New_York",
            minimum_spacing=3,
        )

        self.assertEqual(payload["draftCount"], 1)
        self.assertEqual(payload["scheduledInWindow"], 3)
        self.assertEqual(payload["activeDays"], 2)
        self.assertEqual([event["date"] for event in payload["events"][:2]], ["2026-11-07", "2026-11-07"])

    def test_writes_self_contained_interactive_html_with_scheduled_bodies_only(self):
        notes = [
            private_note(1, "Private draft text"),
            private_note(2, "Private scheduled text", trigger_at="2026-10-13T13:00:00Z"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path, payload = write_runway(
                Path(temp),
                notes,
                start=date(2026, 10, 10),
                days=90,
                zone_name="America/New_York",
                minimum_spacing=3,
            )
            html = path.read_text()

        self.assertEqual(payload["draftCount"], 1)
        self.assertIn("Note runway", html)
        self.assertIn("Minimum distance", html)
        self.assertIn('"scheduledInWindow":1', html)
        self.assertNotIn("Private draft text", html)
        self.assertIn("Private scheduled text", html)
        self.assertIn('className = "note-list"', html)
        self.assertIn("text.textContent = event.text", html)

    def test_loads_existing_lossless_envelopes_from_both_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for category, note in (
                ("note-drafts", private_note(1, "Draft")),
                (
                    "note-scheduled",
                    private_note(2, "Scheduled", trigger_at="2026-10-13T13:00:00Z"),
                ),
            ):
                folder = root / category
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{note['id']}.json").write_text(
                    json.dumps({"category": category, "content": note})
                )

            loaded = load_private_notes(root)

        self.assertEqual({note["id"] for note in loaded}, {1, 2})


class PrivateSyncTests(unittest.TestCase):
    def test_sync_writes_categories_overview_state_and_runway(self):
        notes = [
            private_note(10, "Draft"),
            private_note(20, "Scheduled", trigger_at="2026-10-13T13:00:00Z"),
        ]
        api = FakeApi([notes])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            engine = PrivateNotesSync(
                api,
                root,
                zone_name="America/New_York",
                now=lambda: "2026-10-10T12:00:00Z",
            )

            summary = engine.sync(days=90, minimum_spacing=3)

            self.assertEqual(summary["counts"], {"drafts": 1, "scheduled": 1})
            self.assertTrue((root / "note-drafts" / "10.json").is_file())
            self.assertTrue((root / "note-scheduled" / "20.md").is_file())
            self.assertTrue((root / "notes.md").is_file())
            self.assertTrue((root / "note-runway.html").is_file())
            state = json.loads((root / ".private-sync" / "state.json").read_text())
            self.assertEqual(state["items"]["20"]["category"], "note-scheduled")

    def test_overview_sorts_scheduled_notes_chronologically(self):
        early = private_note(1, "Early", trigger_at="2026-10-12T13:00:00Z")
        late = private_note(2, "Late", trigger_at="2026-11-12T13:00:00Z")

        overview = notes_overview([], [late, early], "2026-10-10T12:00:00Z", ZoneInfo("UTC"))

        self.assertLess(overview.index("Early"), overview.index("Late"))
        self.assertEqual(overview.count("**Status:** Scheduled"), 2)


if __name__ == "__main__":
    unittest.main()
