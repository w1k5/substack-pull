#!/usr/bin/env python3
"""Local dashboard for publication analytics and private Note planning."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from ..analytics import AnalyticsService, PullError
from ..workflows.notes import NotePlanner

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/css/shell.css": ("css/shell.css", "text/css; charset=utf-8"),
    "/css/overview.css": ("css/overview.css", "text/css; charset=utf-8"),
    "/css/post.css": ("css/post.css", "text/css; charset=utf-8"),
    "/css/post-trajectory.css": ("css/post-trajectory.css", "text/css; charset=utf-8"),
    "/css/post-note-reach.css": ("css/post-note-reach.css", "text/css; charset=utf-8"),
    "/css/loading.css": ("css/loading.css", "text/css; charset=utf-8"),
    "/css/post-insights.css": ("css/post-insights.css", "text/css; charset=utf-8"),
    "/css/post-portfolio.css": ("css/post-portfolio.css", "text/css; charset=utf-8"),
    "/css/views.css": ("css/views.css", "text/css; charset=utf-8"),
    "/css/planner.css": ("css/planner.css", "text/css; charset=utf-8"),
    "/js/app.js": ("js/app.js", "text/javascript; charset=utf-8"),
    "/js/shared.js": ("js/shared.js", "text/javascript; charset=utf-8"),
    "/js/export.js": ("js/export.js", "text/javascript; charset=utf-8"),
    "/js/notes-page.js": ("js/notes-page.js", "text/javascript; charset=utf-8"),
    "/js/planner.js": ("js/planner.js", "text/javascript; charset=utf-8"),
    "/js/notes-compare.js": ("js/notes-compare.js", "text/javascript; charset=utf-8"),
    "/js/notes-map.js": ("js/notes-map.js", "text/javascript; charset=utf-8"),
    "/js/timeline.js": ("js/timeline.js", "text/javascript; charset=utf-8"),
    "/js/publication-events.js": ("js/publication-events.js", "text/javascript; charset=utf-8"),
    "/js/source-trend.js": ("js/source-trend.js", "text/javascript; charset=utf-8"),
    "/js/source-labels.js": ("js/source-labels.js", "text/javascript; charset=utf-8"),
    "/js/views/publication.js": ("js/views/publication.js", "text/javascript; charset=utf-8"),
    "/js/views/tables.js": ("js/views/tables.js", "text/javascript; charset=utf-8"),
    "/js/post/index.js": ("js/post/index.js", "text/javascript; charset=utf-8"),
    "/js/post/notes.js": ("js/post/notes.js", "text/javascript; charset=utf-8"),
    "/js/post/trajectory.js": ("js/post/trajectory.js", "text/javascript; charset=utf-8"),
    "/js/post/insights.js": ("js/post/insights.js", "text/javascript; charset=utf-8"),
    "/js/post/portfolio.js": ("js/post/portfolio.js", "text/javascript; charset=utf-8"),
}


class DashboardHandler(BaseHTTPRequestHandler):
    service: AnalyticsService
    planner: NotePlanner = NotePlanner()

    def log_message(self, fmt, *args):
        # Keep query strings and private analytics out of terminal logs.
        pass

    def send_json(self, value: dict, status=200):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected_host:
            self.send_error(403)
            return
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected_host}":
            self.send_error(403)
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/planner":
                params = parse_qs(parsed.query)
                days = int(params.get("days", ["90"])[0])
                spacing = int(params.get("spacing", ["3"])[0])
                refresh = params.get("refresh", ["0"])[0] == "1"
                self.send_json(self.planner.refresh(days=days, spacing=spacing) if refresh
                               else self.planner.snapshot(days=days, spacing=spacing))
                return
            if parsed.path == "/api/note-comparison":
                params = parse_qs(parsed.query)
                days = int(params.get("days", ["90"])[0])
                retry = params.get("retry", ["0"])[0] == "1"
                self.send_json(self.service.note_cohort(days, retry_unavailable=retry))
                return
            if parsed.path == "/api/post-portfolio":
                params = parse_qs(parsed.query)
                refresh = params.get("refresh", ["0"])[0] == "1"
                self.send_json(self.service.post_portfolio(refresh=refresh))
                return
            if parsed.path.startswith("/api/note/"):
                refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
                self.send_json(self.service.note(
                    parsed.path.removeprefix("/api/note/"), refresh=refresh
                ))
                return
            if parsed.path.startswith("/api/post/"):
                refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
                self.send_json(self.service.post(
                    parsed.path.removeprefix("/api/post/"), refresh=refresh
                ))
                return
            if parsed.path == "/api/dashboard":
                params = parse_qs(parsed.query)
                days = int(params.get("days", ["90"])[0])
                refresh = params.get("refresh", ["0"])[0] == "1"
                self.send_json(self.service.dashboard(days, refresh=refresh))
                return
        except LookupError as exc:
            self.send_json({"error": str(exc)}, 404)
            return
        except (ValueError, RuntimeError, PullError, TypeError, KeyError, OSError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return

        route = parsed.path
        if route in {"/posts", "/discovery", "/notes", "/notes/compare", "/planner"} or re.fullmatch(
            r"/(?:posts|notes)/[0-9]+", route
        ):
            route = "/"
        if route not in STATIC_FILES:
            self.send_error(404)
            return
        name, content_type = STATIC_FILES[route]
        body = (STATIC / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        if (self.headers.get("Host") != expected_origin.removeprefix("http://")
                or self.headers.get("Origin") != expected_origin):
            self.send_error(403)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send_json({"error": "Send JSON for Note actions."}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 20_000:
                raise ValueError("Note request is too large or empty.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
            if self.path in {"/api/planner/preview-draft", "/api/planner/create-draft"}:
                text = payload.get("text")
                if not isinstance(text, str):
                    raise ValueError("Note text is required.")
                result = (self.planner.preview_draft(text) if self.path.endswith("preview-draft")
                          else self.planner.create_draft(text))
            elif self.path in {"/api/planner/preview-schedule", "/api/planner/schedule"}:
                note_id, at = payload.get("note_id"), payload.get("at")
                if (not isinstance(note_id, str) or not note_id.isascii() or not note_id.isdecimal()
                        or not isinstance(at, str)):
                    raise ValueError("A numeric Note ID and date/time are required.")
                result = (self.planner.preview_schedule(note_id, at)
                          if self.path.endswith("preview-schedule") else self.planner.schedule(note_id, at))
            else:
                self.send_error(404)
                return
            self.send_json(result)
        except (ValueError, RuntimeError, TypeError, KeyError, OSError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    DashboardHandler.service = AnalyticsService.from_saved_session()
    DashboardHandler.planner = NotePlanner()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Substack analytics: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
