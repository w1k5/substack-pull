from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from substack_pull import (
    ApiClient,
    PullError,
    SyncEngine,
    build_parser,
    load_config,
    normalize_publication,
    require_substack_host,
    save_config,
)


class MockState:
    def __init__(self):
        self.drafts = [
            {
                "id": 10,
                "draft_title": "Draft one",
                "draft_updated_at": "2026-08-01T00:00:00Z",
                "comment_count": 99,
            }
        ]
        self.scheduled = [
            {
                "id": 20,
                "draft_title": "Tomorrow",
                "draft_updated_at": "2026-08-02T00:00:00Z",
                "trigger_at": "2026-09-01T12:00:00Z",
            }
        ]
        self.published = [
            {"id": 30, "title": "Old", "slug": "old", "post_date": "2026-01-01"},
            {"id": 31, "title": "New", "slug": "new", "post_date": "2026-02-01"},
            {"id": 32, "title": "Newest", "slug": "newest", "post_date": "2026-03-01"},
        ]
        self.requests: list[str] = []
        self.cookies: list[str | None] = []


class MockHandler(BaseHTTPRequestHandler):
    server: "MockServer"

    def log_message(self, format, *args):
        return

    def send_json(self, value, status=200):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        self.server.state.requests.append(self.path)
        self.server.state.cookies.append(self.headers.get("Cookie"))
        query = urllib.parse.parse_qs(parsed.query)

        lists = {
            "/api/v1/post_management/drafts": self.server.state.drafts,
            "/api/v1/post_management/scheduled": self.server.state.scheduled,
            "/api/v1/post_management/published": self.server.state.published,
        }
        if path in lists:
            items = lists[path]
            offset = int(query.get("offset", [0])[0])
            limit = int(query.get("limit", [50])[0])
            self.send_json(
                {
                    "posts": items[offset : offset + limit],
                    "offset": offset,
                    "limit": limit,
                    "total": len(items),
                }
            )
            return

        if path.startswith("/api/v1/drafts/") and path.endswith("/scheduled_release"):
            post_id = path.split("/")[-2]
            self.send_json([{"draft_id": int(post_id), "trigger_at": "2026-09-01T12:00:00Z"}])
            return
        if path.startswith("/api/v1/drafts/"):
            post_id = path.rsplit("/", 1)[-1]
            self.send_json(
                {
                    "id": int(post_id),
                    "draft_title": f"Draft {post_id}",
                    "draft_body": f"<p>Body {post_id}</p>",
                }
            )
            return
        if path.startswith("/api/v1/posts/by-id/"):
            post_id = path.rsplit("/", 1)[-1]
            self.send_json(
                {
                    "post": {
                        "id": int(post_id),
                        "title": f"Post {post_id}",
                        "body_html": f"<p>Published {post_id}</p>",
                    }
                }
            )
            return
        self.send_json({"error": "not found"}, status=404)


class MockServer(ThreadingHTTPServer):
    def __init__(self, state):
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


class NormalizeTests(unittest.TestCase):
    def test_adds_https_and_removes_paths(self):
        self.assertEqual(
            normalize_publication("writer.substack.com/archive"),
            "https://writer.substack.com",
        )

    def test_rejects_insecure_remote_url(self):
        with self.assertRaises(PullError):
            normalize_publication("http://writer.substack.com")

    def test_refuses_to_send_auth_to_custom_domain(self):
        with self.assertRaises(PullError):
            require_substack_host("https://newsletter.example.com")

    def test_accepts_substack_subdomain(self):
        require_substack_host("https://writer.substack.com")

    def test_directory_flag_and_legacy_output_alias(self):
        parser = build_parser()
        current = parser.parse_args(["sync", "--directory", "/new/place"])
        legacy = parser.parse_args(["sync", "--output", "/old/name"])
        short = parser.parse_args(["sync", "-d", "/short"])
        self.assertEqual(current.directory, "/new/place")
        self.assertEqual(legacy.directory, "/old/name")
        self.assertEqual(short.directory, "/short")

    def test_old_output_config_migrates_to_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "publication": "https://writer.substack.com",
                        "output": "old-backup",
                    }
                )
            )
            config = load_config(path, None)
            self.assertEqual(config["directory"], "old-backup")
            save_config(path, config)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["directory"], "old-backup")
            self.assertNotIn("output", saved)


class SyncTests(unittest.TestCase):
    def make_engine(self, fixture, output):
        api = ApiClient(fixture.url, "test-session", request_delay=0)
        return SyncEngine(
            api,
            Path(output),
            page_limit=2,
            now=lambda: "2026-08-29T12:00:00Z",
        )

    def test_session_value_is_sent_under_safari_and_chromium_cookie_names(self):
        with ServerFixture() as fixture:
            api = ApiClient(fixture.url, "browser-session", request_delay=0)

            api.get_json("/api/v1/post_management/drafts?offset=0&limit=1")

            self.assertEqual(
                fixture.state.cookies[-1],
                "connect.sid=browser-session; substack.sid=browser-session",
            )

    def test_first_sync_paginates_and_writes_all_categories(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            summary = self.make_engine(fixture, temp).sync()

            self.assertEqual(summary["categories"]["drafts"]["fetched"], 1)
            self.assertEqual(summary["categories"]["scheduled"]["fetched"], 1)
            self.assertEqual(summary["categories"]["published"]["fetched"], 3)
            self.assertTrue((Path(temp) / "drafts" / "10.json").is_file())
            self.assertTrue((Path(temp) / "drafts" / "10.html").is_file())
            self.assertTrue((Path(temp) / "scheduled" / "20.json").is_file())
            self.assertTrue((Path(temp) / "published" / "32.json").is_file())
            self.assertTrue((Path(temp) / ".sync" / "state.json").is_file())

            published_list_requests = [
                request
                for request in fixture.state.requests
                if request.startswith("/api/v1/post_management/published")
            ]
            self.assertEqual(len(published_list_requests), 2)

    def test_unchanged_second_sync_skips_body_requests(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.make_engine(fixture, temp)
            engine.sync()
            fixture.state.requests.clear()

            summary = engine.sync()

            self.assertEqual(summary["categories"]["published"]["fetched"], 0)
            self.assertEqual(summary["categories"]["published"]["unchanged"], 3)
            body_requests = [
                request
                for request in fixture.state.requests
                if "/drafts/" in request or "/posts/by-id/" in request
            ]
            self.assertEqual(body_requests, [])

    def test_only_new_or_edited_items_are_refetched(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.make_engine(fixture, temp)
            engine.sync()
            fixture.state.requests.clear()
            fixture.state.drafts[0]["draft_updated_at"] = "2026-08-30T00:00:00Z"
            fixture.state.scheduled[0]["draft_updated_at"] = "2026-08-31T00:00:00Z"
            fixture.state.scheduled[0]["trigger_at"] = "2026-09-02T12:00:00Z"
            fixture.state.published.append(
                {"id": 33, "title": "Latest", "slug": "latest", "post_date": "2026-04-01"}
            )

            summary = engine.sync()

            self.assertEqual(summary["categories"]["drafts"]["fetched"], 1)
            self.assertEqual(summary["categories"]["scheduled"]["fetched"], 1)
            self.assertEqual(summary["categories"]["published"]["fetched"], 1)
            body_requests = [
                request
                for request in fixture.state.requests
                if "/drafts/" in request or "/posts/by-id/" in request
            ]
            self.assertEqual(
                sorted(body_requests),
                sorted(
                    [
                        "/api/v1/drafts/10",
                        "/api/v1/drafts/20",
                        "/api/v1/drafts/20/scheduled_release",
                        "/api/v1/posts/by-id/33",
                    ]
                ),
            )

    def test_missing_remote_item_is_preserved_locally(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.make_engine(fixture, temp)
            engine.sync()
            existing = Path(temp) / "published" / "30.json"
            self.assertTrue(existing.is_file())
            fixture.state.published = fixture.state.published[1:]

            summary = engine.sync()

            self.assertEqual(
                summary["categories"]["published"]["missing_local_preserved"], 1
            )
            self.assertTrue(existing.is_file())
            with (Path(temp) / ".sync" / "state.json").open() as handle:
                state = json.load(handle)
            self.assertEqual(
                state["categories"]["published"]["30"]["remote_status"], "missing"
            )

    def test_refresh_published_forces_only_published_bodies(self):
        with ServerFixture() as fixture, tempfile.TemporaryDirectory() as temp:
            engine = self.make_engine(fixture, temp)
            engine.sync()
            fixture.state.requests.clear()

            summary = engine.sync(refresh_published=True)

            self.assertEqual(summary["categories"]["drafts"]["fetched"], 0)
            self.assertEqual(summary["categories"]["scheduled"]["fetched"], 0)
            self.assertEqual(summary["categories"]["published"]["fetched"], 3)


if __name__ == "__main__":
    unittest.main()
