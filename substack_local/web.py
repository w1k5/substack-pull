#!/usr/bin/env python3
"""Local, read-only dashboard for a publication's authenticated Substack stats."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analytics import AnalyticsService, PullError

STATIC = Path(__file__).resolve().parent / "ui"


class DashboardHandler(BaseHTTPRequestHandler):
    service: AnalyticsService

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
            if parsed.path.startswith("/api/note/"):
                self.send_json(self.service.note(parsed.path.removeprefix("/api/note/")))
                return
            if parsed.path.startswith("/api/post/"):
                self.send_json(self.service.post(parsed.path.removeprefix("/api/post/")))
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
        except (ValueError, PullError, TypeError, KeyError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return

        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/common.js": ("common.js", "text/javascript; charset=utf-8"),
                 "/post.js": ("post.js", "text/javascript; charset=utf-8"),
                 "/post_notes.js": ("post_notes.js", "text/javascript; charset=utf-8"),
                 "/post_trajectory.js": ("post_trajectory.js", "text/javascript; charset=utf-8"),
                 "/post_insights.js": ("post_insights.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if parsed.path not in files:
            self.send_error(404)
            return
        name, content_type = files[parsed.path]
        body = (STATIC / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    DashboardHandler.service = AnalyticsService.from_saved_session()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    print(f"Substack analytics: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
