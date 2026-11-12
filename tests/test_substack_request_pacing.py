"""Real Substack clients coordinate requests without exposing private URLs."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from email.message import Message
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from substack_local.pullers.pacing import _endpoint, paced_request


class RequestPacingTests(unittest.TestCase):
    def test_timing_label_omits_identifiers_and_query_values(self):
        self.assertEqual(_endpoint("/api/v1/notes/123?token=secret"), "/api/v1/notes")
        self.assertEqual(_endpoint("/api/v1/post_management/detail/123"), "/api/v1/post_management")

    def test_substack_requests_are_serial_and_spaced(self):
        with TemporaryDirectory() as directory, \
             patch("substack_local.pullers.pacing.data_root", return_value=Path(directory)):
            def request():
                with paced_request("https://substack.com", "/api/v1/notes/123",
                                   enabled=True, delay=0):
                    return time.monotonic()

            with ThreadPoolExecutor(max_workers=2) as pool:
                started = sorted(pool.map(lambda _: request(), range(2)))
            self.assertGreaterEqual(started[1] - started[0], 0.9)

    def test_local_and_injected_requests_are_not_delayed(self):
        with paced_request("http://127.0.0.1:8765", "/api/example", enabled=True):
            pass
        with paced_request("https://substack.com", "/api/example", enabled=False):
            pass

    def test_rate_limit_pause_is_shared_without_retrying_immediately(self):
        with TemporaryDirectory() as directory, \
             patch("substack_local.pullers.pacing.data_root", return_value=Path(directory)):
            headers = Message()
            headers["Retry-After"] = "600"
            with self.assertRaises(HTTPError):
                with paced_request("https://substack.com", "/api/v1/notes/123", enabled=True):
                    raise HTTPError("https://substack.com", 429, "Rate limited", headers, None)
            with self.assertRaisesRegex(RuntimeError, "long pause"):
                with paced_request("https://substack.com", "/api/v1/notes/456", enabled=True):
                    self.fail("A paused client must not send another request")


if __name__ == "__main__":
    unittest.main()
