"""Cached analytics service shared by the dashboard and MCP server."""

import threading
import time

from .client import ApiClient, CONFIG, KeychainStore, host_for, load_config
from .note import note_stats
from .post import fetch_post
from .publication import fetch_dashboard, fetch_posts

ALLOWED_DAYS = {30, 90, 180, 365}

def numeric_id(value: str, kind: str) -> str:
    value = str(value)
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"Invalid {kind} ID")
    return value


class AnalyticsService:
    """One request and normalization layer for the HTTP UI and MCP tools."""

    def __init__(self, api: ApiClient, note_api: ApiClient):
        self.api = api
        self.note_api = note_api
        self.cache: dict[int, tuple[float, dict]] = {}
        self.post_cache: dict[str, tuple[float, dict]] = {}
        self.note_cache: dict[str, tuple[float, dict]] = {}
        self.posts_cache: tuple[float, list[dict]] | None = None
        self.lock = threading.Lock()

    @classmethod
    def from_saved_session(cls) -> "AnalyticsService":
        config = load_config(CONFIG, None)
        token = KeychainStore().get(host_for(config["publication"]))
        return cls(ApiClient(config["publication"], token), ApiClient("https://substack.com", token))

    def dashboard(self, days: int = 90, *, refresh: bool = False) -> dict:
        if days not in ALLOWED_DAYS:
            raise ValueError("Choose 30, 90, 180, or 365 days.")
        with self.lock:
            saved = self.cache.get(days)
            if saved and not refresh and time.monotonic() - saved[0] < 300:
                return saved[1]
            value = fetch_dashboard(self.api, days)
            self.cache[days] = (time.monotonic(), value)
            return value

    def post(self, post_id: str) -> dict:
        post_id = numeric_id(post_id, "post")
        with self.lock:
            saved = self.post_cache.get(post_id)
            if saved and time.monotonic() - saved[0] < 300:
                return saved[1]
            value = fetch_post(self.api, post_id)
            self.post_cache[post_id] = (time.monotonic(), value)
            return value

    def posts(self) -> list[dict]:
        with self.lock:
            if self.posts_cache and time.monotonic() - self.posts_cache[0] < 300:
                return self.posts_cache[1]
            value = fetch_posts(self.api)
            self.posts_cache = (time.monotonic(), value)
            return value

    def note(self, note_id: str) -> dict:
        note_id = numeric_id(note_id, "Note")
        with self.lock:
            saved = self.note_cache.get(note_id)
            if saved and time.monotonic() - saved[0] < 3600:
                return saved[1]
            value = note_stats(self.note_api, note_id)
            self.note_cache[note_id] = (time.monotonic(), value)
            return value
