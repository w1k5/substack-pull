from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from substack_notes_pull import (
    ApiClient,
    PullError,
    SyncEngine,
    authored_note,
    collect_local_notes,
    normalize_handle,
    parse_preloads,
    resolve_profile,
    save_config,
)


PROFILE_ID = "700"


def comment(
    note_id: int,
    body: str,
    *,
    user_id: str = PROFILE_ID,
    ancestor_path: str = "",
    reactions: int = 0,
    attachments: list[dict] | None = None,
) -> dict:
    return {
        "type": "comment",
        "context": {"type": "note"},
        "comment": {
            "id": note_id,
            "user_id": int(user_id),
            "type": "feed",
            "date": f"2026-10-{note_id // 10:02d}T12:00:00.000Z",
            "edited_at": None,
            "ancestor_path": ancestor_path,
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
            "attachments": attachments or [],
            "reaction_count": reactions,
            "restacks": 1,
            "children_count": 2,
        },
        "trackingParameters": {"item": str(note_id)},
    }


class MockState:
    def __init__(self):
        self.fail_page_two = False
        self.requests: list[str] = []
        self.cookies: list[str | None] = []
        self.page_one = [
            comment(
                30,
                "Newest note",
                reactions=3,
                attachments=[
                    {
                        "type": "image",
                        "id": "image-1",
                        "imageUrl": "https://example.com/image.jpg",
                    }
                ],
            ),
            comment(29, "Somebody else's note", user_id="999"),
            comment(28, "A reply", ancestor_path="30.28"),
            {"type": "post", "context": {"type": "post"}, "post": {"id": 1}},
        ]
        self.page_two = [comment(20, "Middle note", reactions=8), comment(10, "Old note")]


class MockHandler(BaseHTTPRequestHandler):
    server: "MockServer"

    def log_message(self, format, *args):
        return

    def send_bytes(self, payload: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, value, status: int = 200):
        self.send_bytes(json.dumps(value).encode(), "application/json", status)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.server.state.requests.append(self.path)
        self.server.state.cookies.append(self.headers.get("Cookie"))

        if parsed.path == "/@writer":
            preload = {
                "profile": {
                    "id": int(PROFILE_ID),
                    "handle": "writer",
                    "name": "The Writer",
                    "bio": "Notes for testing",
                }
            }
            literal = json.dumps(json.dumps(preload))
            html = f"<script>window._preloads = JSON.parse({literal})</script>"
            self.send_bytes(html.encode(), "text/html")
            return

        if parsed.path == f"/api/v1/reader/feed/profile/{PROFILE_ID}":
            if query.get("types") != ["note"]:
                self.send_json({"error": "types=note required"}, 400)
                return
            cursor = query.get("cursor", [None])[0]
            if cursor is None:
                self.send_json({"items": self.server.state.page_one, "nextCursor": "page-two"})
                return
            if cursor == "page-two":
                if self.server.state.fail_page_two:
                    self.send_json({"error": "temporary"}, 500)
                else:
                    self.send_json({"items": self.server.state.page_two, "nextCursor": None})
                return
        self.send_json({"error": "not found"}, 404)


class MockServer(ThreadingHTTPServer):
    def __init__(self, state: MockState):
        super().__init__(("127.0.0.1", 0), MockHandler)
        self.state = state


class ServerFixture:
    def __enter__(self):
        self.state = MockState()
        self.server = MockServer(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class ProfileTests(unittest.TestCase):
    def test_normalizes_supported_profile_forms(self):
        self.assertEqual(normalize_handle("@Writer"), "writer")
        self.assertEqual(normalize_handle("https://substack.com/@Writer/notes"), "writer")
        self.assertEqual(normalize_handle("https://writer.substack.com"), "writer")
        self.assertEqual(normalize_handle("writer.substack.com"), "writer")

    def test_rejects_non_substack_url(self):
        with self.assertRaises(PullError):
            normalize_handle("https://example.com/@writer")

    def test_decodes_profile_preload_and_resolves_id(self):
        preload = {"profile": {"id": 7, "handle": "writer", "name": "Writer"}}
        html = f"window._preloads = JSON.parse({json.dumps(json.dumps(preload))})"
        self.assertEqual(parse_preloads(html), preload)

        with ServerFixture() as fixture:
            profile = resolve_profile(
                ApiClient(fixture.url, request_delay=0), "@writer"
            )
        self.assertEqual(profile["id"], PROFILE_ID)
        self.assertEqual(profile["handle"], "writer")

    def test_decodes_embedded_profile_preload(self):
        preload = {"profile": {"id": 7, "handle": "writer", "name": "Writer"}}
        html = (
            f'<script id="preloads-json" type="application/json">'
            f"{json.dumps(preload)}</script>"
            '<script>window._preloads = JSON.parse(document.querySelector('
            "'script#preloads-json').textContent)</script>"
        )
        self.assertEqual(parse_preloads(html), preload)

    def test_authored_note_filters_restacks_replies_and_posts(self):
        own = comment(1, "own")
        self.assertEqual(authored_note(own, PROFILE_ID)["id"], 1)
        self.assertIsNone(authored_note(comment(2, "other", user_id="999"), PROFILE_ID))
        self.assertIsNone(
            authored_note(comment(3, "reply", ancestor_path="1.3"), PROFILE_ID)
        )
        self.assertIsNone(authored_note({"type": "post"}, PROFILE_ID))

    def test_public_config_save_preserves_private_planner_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            save_config(
                path,
                {
                    "profile": "@writer",
                    "directory": "public-notes",
                    "notes_directory": "draft-notes",
                    "timezone": "America/New_York",
                },
            )

            saved = json.loads(path.read_text())

        self.assertEqual(saved["notes_directory"], "draft-notes")
        self.assertEqual(saved["timezone"], "America/New_York")


class SyncTests(unittest.TestCase):
    def engine(self, fixture: ServerFixture, output: str, overlap: int = 1) -> SyncEngine:
        api = ApiClient(fixture.url, request_delay=0, attempts=1)
        profile = resolve_profile(api, "@writer")
        return SyncEngine(
            api,
            Path(output),
            profile,
            overlap=overlap,
            now=lambda: "2026-10-10T12:00:00Z",
        )

    def test_first_pull_paginates_filters_and_writes_lossless_and_readable_files(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            summary = self.engine(fixture, temp).sync()

            self.assertEqual(summary["mode"], "initial")
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["pages"], 2)
            self.assertEqual(summary["created"], 3)
            self.assertEqual(summary["ignored_non_authored_items"], 3)
            self.assertTrue((Path(temp) / "notes" / "30.json").is_file())
            markdown = (Path(temp) / "notes" / "30.md").read_text()
            self.assertIn("Newest note", markdown)
            self.assertIn("https://example.com/image.jpg", markdown)
            envelope = json.loads((Path(temp) / "notes" / "30.json").read_text())
            self.assertIn("feed_item", envelope)
            self.assertEqual(envelope["note"]["reaction_count"], 3)
            self.assertEqual(set(fixture.state.cookies), {None})
            feed_requests = [
                request
                for request in fixture.state.requests
                if "/reader/feed/profile/" in request
            ]
            self.assertTrue(all("types=note" in request for request in feed_requests))
            self.assertTrue(any("cursor=page-two" in request for request in feed_requests))

    def test_incremental_pull_stops_after_known_overlap_but_updates_engagement(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.engine(fixture, temp)
            engine.sync()
            fixture.state.requests.clear()
            fixture.state.page_one[0]["comment"]["reaction_count"] = 9

            summary = engine.sync()

            self.assertEqual(summary["mode"], "incremental")
            self.assertEqual(summary["pages"], 1)
            self.assertEqual(summary["updated"], 1)
            envelope = json.loads((Path(temp) / "notes" / "30.json").read_text())
            self.assertEqual(envelope["note"]["reaction_count"], 9)
            self.assertFalse(
                any("cursor=page-two" in request for request in fixture.state.requests)
            )

    def test_incremental_pull_ignores_volatile_attachment_tracking(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            attachment = fixture.state.page_one[0]["comment"]["attachments"][0]
            attachment["trackingParameters"] = {"impression_id": "first-request"}
            engine = self.engine(fixture, temp)
            engine.sync()
            attachment["trackingParameters"]["impression_id"] = "second-request"

            summary = engine.sync()

            self.assertEqual(summary["pages"], 1)
            self.assertEqual(summary["updated"], 0)
            self.assertEqual(summary["unchanged"], 1)

    def test_new_note_is_pulled_and_older_edit_waits_for_refresh(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.engine(fixture, temp)
            engine.sync()
            fixture.state.page_one.insert(0, comment(40, "Brand new"))
            fixture.state.page_two[1] = comment(10, "Edited old note")

            incremental = engine.sync()

            self.assertEqual(incremental["created"], 1)
            self.assertTrue((Path(temp) / "notes" / "40.md").is_file())
            self.assertNotIn(
                "Edited old note", (Path(temp) / "notes" / "10.md").read_text()
            )

            refreshed = engine.sync(refresh=True)
            self.assertEqual(refreshed["mode"], "refresh")
            self.assertIn(
                "Edited old note", (Path(temp) / "notes" / "10.md").read_text()
            )

    def test_refresh_marks_removed_note_missing_without_deleting_it(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.engine(fixture, temp)
            engine.sync()
            existing = Path(temp) / "notes" / "10.json"
            fixture.state.page_two = fixture.state.page_two[:1]

            summary = engine.sync(refresh=True)

            self.assertEqual(summary["missing_local_preserved"], 1)
            self.assertTrue(existing.is_file())
            state = json.loads((Path(temp) / ".sync" / "state.json").read_text())
            self.assertEqual(state["notes"]["10"]["remote_status"], "missing")

    def test_failed_initial_crawl_resumes_from_saved_cursor(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            fixture.state.fail_page_two = True
            engine = self.engine(fixture, temp)

            with self.assertRaises(PullError):
                engine.sync()

            state = json.loads((Path(temp) / ".sync" / "state.json").read_text())
            self.assertEqual(state["crawl"]["next_cursor"], "page-two")
            self.assertTrue((Path(temp) / "notes" / "30.json").is_file())
            fixture.state.fail_page_two = False
            fixture.state.requests.clear()

            summary = engine.sync()

            self.assertTrue(summary["resumed"])
            self.assertEqual(summary["pages"], 1)
            self.assertTrue((Path(temp) / "notes" / "10.json").is_file())
            self.assertTrue(
                any("cursor=page-two" in request for request in fixture.state.requests)
            )

    def test_local_list_can_rank_by_reactions_and_search_body(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            self.engine(fixture, temp).sync()
            popular = collect_local_notes(Path(temp), sort_by="reactions")
            searched = collect_local_notes(Path(temp), query="old NOTE")

            self.assertEqual(popular[0]["id"], "20")
            self.assertEqual([item["id"] for item in searched], ["10"])


class RetryTests(unittest.TestCase):
    class Response:
        def __init__(self, payload: bytes):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.payload

    def test_429_honors_retry_after_and_retries(self):
        calls = 0
        sleeps: list[float] = []

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "rate limited",
                    {"Retry-After": "0"},
                    io.BytesIO(b"rate limited"),
                )
            return self.Response(b'{"ok": true}')

        client = ApiClient(
            "http://127.0.0.1",
            request_delay=0,
            attempts=2,
            opener=opener,
            sleeper=sleeps.append,
        )

        self.assertEqual(client.get_json("/test"), {"ok": True})
        self.assertEqual(calls, 2)
        self.assertEqual(sleeps, [0.0])


if __name__ == "__main__":
    unittest.main()
