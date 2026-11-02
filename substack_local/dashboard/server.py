#!/usr/bin/env python3
"""Local, read-only dashboard for a publication's authenticated Substack stats."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..analytics import AnalyticsService, PullError

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/css/shell.css": ("css/shell.css", "text/css; charset=utf-8"),
    "/css/overview.css": ("css/overview.css", "text/css; charset=utf-8"),
    "/css/post.css": ("css/post.css", "text/css; charset=utf-8"),
    "/js/app.js": ("js/app.js", "text/javascript; charset=utf-8"),
    "/js/shared.js": ("js/shared.js", "text/javascript; charset=utf-8"),
    "/js/post/index.js": ("js/post/index.js", "text/javascript; charset=utf-8"),
    "/js/post/notes.js": ("js/post/notes.js", "text/javascript; charset=utf-8"),
    "/js/post/trajectory.js": ("js/post/trajectory.js", "text/javascript; charset=utf-8"),
    "/js/post/insights.js": ("js/post/insights.js", "text/javascript; charset=utf-8"),
}


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

        if parsed.path not in STATIC_FILES:
            self.send_error(404)
            return
        name, content_type = STATIC_FILES[parsed.path]
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
