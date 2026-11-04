"""Check the local dashboard's public asset and API routes after layout changes."""

import json
from http.server import ThreadingHTTPServer
import threading
import unittest
from urllib.request import urlopen

from substack_local.dashboard.server import DashboardHandler, STATIC_FILES


class StubAnalytics:
    def dashboard(self, days, *, refresh=False):
        return {"days": days, "refresh": refresh}

    def post(self, post_id, *, refresh=False):
        return {"post_id": post_id, "refresh": refresh}

    def post_portfolio(self, *, refresh=False):
        return {"portfolio": True, "refresh": refresh}

    def note(self, note_id, *, refresh=False):
        return {"note_id": note_id, "refresh": refresh}

    def note_cohort(self, days=90):
        return {"days": days, "rows": [], "lenses": {}}


class DashboardRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DashboardHandler.service = StubAnalytics()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_every_declared_browser_asset_is_served(self):
        for route, (_, content_type) in STATIC_FILES.items():
            with self.subTest(route=route), urlopen(self.base_url + route) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], content_type)
                self.assertTrue(response.read())

    def test_dashboard_and_detail_api_routes(self):
        for route, expected in (
            ("/api/dashboard?days=30&refresh=1", {"days": 30, "refresh": True}),
            ("/api/post/123", {"post_id": "123", "refresh": False}),
            ("/api/post/123?refresh=1", {"post_id": "123", "refresh": True}),
            ("/api/post-portfolio?refresh=1", {"portfolio": True, "refresh": True}),
            ("/api/note/456", {"note_id": "456", "refresh": False}),
            ("/api/note/456?refresh=1", {"note_id": "456", "refresh": True}),
            ("/api/note-comparison?days=30", {"days": 30, "rows": [], "lenses": {}}),
        ):
            with self.subTest(route=route), urlopen(self.base_url + route) as response:
                self.assertEqual(json.load(response), expected)

    def test_each_view_can_be_opened_directly(self):
        for route in ("/posts", "/discovery", "/notes", "/notes/compare", "/posts/123", "/notes/456"):
            with self.subTest(route=route), urlopen(self.base_url + route) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers["Content-Type"])
                self.assertIn(b'id="view-briefing"', response.read())


if __name__ == "__main__":
    unittest.main()
