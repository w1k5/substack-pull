"""Cached analytics service shared by the dashboard and MCP server."""

import threading
import time
import math
from hashlib import sha256

from .cache import NOTE_TTL_SECONDS, NoteDiskCache, PostDiskCache, PostWeekDiskCache, PublishedPostsDiskCache
from .client import ApiClient, CONFIG, ROOT, KeychainStore, PullError, host_for, load_config
from .note import note_stats
from .note_comparison import note_comparison_metrics, summarize_note_cohort
from .note_shares import post_note_shares, public_note_preview
from .post import fetch_post, fetch_post_week, first_week_summary
from .publication import fetch_dashboard, fetch_posts

ALLOWED_DAYS = {7, 30, 90, 180, 365}

def numeric_id(value: str, kind: str) -> str:
    value = str(value)
    if not value.isascii() or not value.isdecimal():
        raise ValueError(f"Invalid {kind} ID")
    return value


class AnalyticsService:
    """One request and normalization layer for the HTTP UI and MCP tools."""

    def __init__(self, api: ApiClient, note_api: ApiClient,
                 note_disk_cache: NoteDiskCache | None = None,
                 post_disk_cache: PostDiskCache | None = None,
                 published_posts_cache: PublishedPostsDiskCache | None = None,
                 post_week_cache: PostWeekDiskCache | None = None):
        self.api = api
        self.note_api = note_api
        self.note_disk_cache = note_disk_cache
        self.post_disk_cache = post_disk_cache
        self.published_posts_cache = published_posts_cache
        self.post_week_cache = post_week_cache
        self.cache: dict[int, tuple[float, dict]] = {}
        self.post_cache: dict[str, tuple[float, dict]] = {}
        self.note_cache: dict[str, tuple[float, dict]] = {}
        self.posts_cache: tuple[float, list[dict]] | None = None
        self.lock = threading.RLock()

    @classmethod
    def from_saved_session(cls) -> "AnalyticsService":
        config = load_config(CONFIG, None)
        host = host_for(config["publication"])
        token = KeychainStore().get(host)
        # Keep private owner analytics separate across publications and sessions.
        session_scope = sha256(token.encode("utf-8")).hexdigest()[:24]
        cache_root = ROOT / "substack" / ".analytics-cache" / host / session_scope
        return cls(ApiClient(config["publication"], token),
                   ApiClient("https://substack.com", token),
                   NoteDiskCache(cache_root / "notes"),
                   PostDiskCache(cache_root / "posts"),
                   PublishedPostsDiskCache(cache_root / "post-index"),
                   PostWeekDiskCache(cache_root / "post-week"))

    def dashboard(self, days: int = 90, *, refresh: bool = False) -> dict:
        if days not in ALLOWED_DAYS:
            raise ValueError("Choose 7, 30, 90, 180, or 365 days.")
        with self.lock:
            saved = self.cache.get(days)
            if saved and not refresh and time.monotonic() - saved[0] < 300:
                return saved[1]
            value = fetch_dashboard(self.api, days, post_rows=self.posts(refresh=refresh))
            self.cache[days] = (time.monotonic(), value)
            return value

    def post(self, post_id: str, *, refresh: bool = False) -> dict:
        post_id = numeric_id(post_id, "post")
        with self.lock:
            if self.post_disk_cache:
                value = self.post_disk_cache.read(post_id) if not refresh else None
            else:
                saved = self.post_cache.get(post_id) if not refresh else None
                value = saved[1] if saved and time.monotonic() - saved[0] < 300 else None
            if value is None:
                value = fetch_post(self.api, post_id)
                if self.post_disk_cache:
                    try:
                        self.post_disk_cache.write(post_id, value)
                    except (OSError, ValueError, TypeError):
                        pass
            self.post_cache[post_id] = (time.monotonic(), value)
            shares = post_note_shares(ROOT / "substack" / "published-notes", post_id)
            for share in shares["notes"]:
                try:
                    stats = self.note(share["id"], refresh=refresh)
                    share["link_clicks"] = next(
                        (item.get("value") for item in stats.get("interactions", {}).get("items", [])
                         if item.get("title") == "Link click"), 0
                    )
                except (PullError, LookupError, ValueError, TypeError, KeyError):
                    # The public attachment still establishes the link when
                    # owner-only Note statistics are temporarily unavailable.
                    pass
            return {**value, "direct_note_shares": shares}

    def posts(self, *, refresh: bool = False) -> list[dict]:
        with self.lock:
            if self.published_posts_cache:
                value = self.published_posts_cache.read() if not refresh else None
            else:
                value = (self.posts_cache[1] if self.posts_cache and not refresh
                         and time.monotonic() - self.posts_cache[0] < 300 else None)
            if value is None:
                value = fetch_posts(self.api)
                if self.published_posts_cache:
                    try:
                        self.published_posts_cache.write(value)
                    except (OSError, ValueError, TypeError):
                        pass
            self.posts_cache = (time.monotonic(), value)
            return value

    def post_week(self, post_id: str, *, refresh: bool = False) -> dict | None:
        post_id = numeric_id(post_id, "post")
        with self.lock:
            value = self.post_week_cache.read(post_id) if self.post_week_cache and not refresh else None
            if value is not None:
                return value
            detail = self.post_disk_cache.read(post_id) if self.post_disk_cache and not refresh else None
            if detail is not None:
                comps = detail.get("comps") or {}
                value = first_week_summary(post_id, {
                    "post_date": detail.get("date"), "type": comps.get("post_type"),
                    "audience": comps.get("audience"),
                    "stats": {"firstWeekDailyStats": detail.get("first_week")},
                })
            if value is None:
                value = fetch_post_week(self.api, post_id)
            if value is not None and self.post_week_cache:
                try:
                    self.post_week_cache.write(post_id, value)
                except (OSError, ValueError, TypeError):
                    pass
            return value

    def post_portfolio(self, *, limit: int = 60, refresh: bool = False) -> dict:
        if not 1 <= limit <= 60:
            raise ValueError("Choose a limit from 1 to 60.")
        posts = sorted(self.posts(), key=lambda row: row.get("date") or "", reverse=True)[:limit]
        rows, incomplete, unavailable = [], 0, 0
        for post in posts:
            try:
                summary = self.post_week(str(post["id"]), refresh=refresh)
            except (PullError, LookupError, ValueError, TypeError, KeyError):
                unavailable += 1
                continue
            if summary is None:
                incomplete += 1
            else:
                try:
                    lifetime_views = float(post.get("views"))
                except (TypeError, ValueError):
                    lifetime_views = None
                later_views = (int(lifetime_views - summary["views"])
                               if lifetime_views is not None and math.isfinite(lifetime_views)
                               and lifetime_views >= summary["views"] else None)
                try:
                    lifetime_shares = float(post.get("shares"))
                except (TypeError, ValueError):
                    lifetime_shares = None
                share_rate = (1000 * lifetime_shares / lifetime_views
                              if lifetime_views is not None and math.isfinite(lifetime_views)
                              and lifetime_views >= 1000 and lifetime_shares is not None
                              and math.isfinite(lifetime_shares) and lifetime_shares >= 0 else None)
                rows.append({**summary, "title": post["title"],
                             "lifetime_views": post.get("views"),
                             "lifetime_signups": post.get("signups"),
                             "lifetime_shares": post.get("shares"),
                             "share_rate": share_rate,
                             "later_views": later_views,
                             "later_multiple": later_views / summary["views"]
                             if later_views is not None and summary["views"] else None})
        return {"rows": rows, "considered": len(posts), "total": len(self.posts()),
                "incomplete": incomplete, "unavailable": unavailable}

    def note(self, note_id: str, *, refresh: bool = False) -> dict:
        note_id = numeric_id(note_id, "Note")
        with self.lock:
            if self.note_disk_cache and not refresh:
                disk_value = self.note_disk_cache.read(note_id)
                if disk_value is not None:
                    disk_value = {**disk_value, "comparison": note_comparison_metrics(disk_value)}
                    if "preview" not in disk_value:
                        disk_value = {**disk_value, "preview": public_note_preview(
                            ROOT / "substack" / "published-notes", note_id
                        )}
                    return disk_value
            saved = self.note_cache.get(note_id)
            if saved and not refresh and time.monotonic() - saved[0] < NOTE_TTL_SECONDS:
                return saved[1]
            value = note_stats(self.note_api, note_id)
            value = {**value, "comparison": note_comparison_metrics(value)}
            self.note_cache[note_id] = (time.monotonic(), value)
            if self.note_disk_cache:
                try:
                    self.note_disk_cache.write(note_id, value)
                except (OSError, ValueError, TypeError):
                    # A cache write failure must not hide a successful live fetch.
                    pass
            return value

    def note_cohort(self, days: int = 90) -> dict:
        """Compare published Notes in one period, sharing the same result with UI and MCP."""
        data = self.dashboard(days)
        events = sorted(
            (event for event in data.get("publication_events", [])
             if event.get("type") == "note" and str(event.get("id", "")).isascii()
             and str(event.get("id", "")).isdecimal()),
            key=lambda event: (event.get("day") or "", int(event["id"])), reverse=True,
        )
        rows, unavailable_ids = [], []
        for event in events:
            note_id = str(event["id"])
            try:
                stats = self.note(note_id)
            except (PullError, LookupError, ValueError, TypeError, KeyError):
                unavailable_ids.append(note_id)
                continue
            rows.append({"id": note_id, "title": event.get("title") or "Note",
                         "day": event.get("day"), **stats["comparison"]})
        return {"days": days, "total": len(events), "rows": rows,
                "unavailable_ids": unavailable_ids,
                "lenses": summarize_note_cohort(rows)}
