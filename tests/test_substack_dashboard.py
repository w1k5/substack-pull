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

    def post(self, post_id):
        return {"post_id": post_id}

    def note(self, note_id):
        return {"note_id": note_id}


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
            ("/api/post/123", {"post_id": "123"}),
            ("/api/note/456", {"note_id": "456"}),
        ):
            with self.subTest(route=route), urlopen(self.base_url + route) as response:
                self.assertEqual(json.load(response), expected)


if __name__ == "__main__":
    unittest.main()
