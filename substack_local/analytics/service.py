"""Cached analytics service shared by the dashboard and MCP server."""

import threading
import time
import math
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

from .cache import (
    NOTE_TTL_SECONDS, PUBLICATION_TTL_SECONDS, NoteDiskCache, PostDiskCache,
    PostWeekDiskCache, PublishedPostsDiskCache, PublicationDiskCache,
    prune_analytics_caches,
)
from .client import ApiClient, CONFIG, ROOT, KeychainStore, PullError, host_for, load_config
from .derived import dashboard_metrics, post_detail_metrics, post_index_metrics
from .note import note_stats
from .note_comparison import note_comparison_metrics, summarize_note_cohort
from .note_shares import post_note_shares, public_note_preview
from .post import fetch_post, fetch_post_week, first_week_summary
from .post_comparison import summarize_post_portfolio
from .publication import fetch_dashboard, fetch_posts

ALLOWED_DAYS = {7, 30, 90, 180, 365}
MEMORY_ENTRY_LIMIT = 64
COMPARISON_TTL_SECONDS = 300


def _today() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _prune_memory(cache: dict, ttl_seconds: int) -> None:
    now = time.monotonic()
    for key, (loaded_at, _) in list(cache.items()):
        if now - loaded_at >= ttl_seconds:
            del cache[key]
    while len(cache) > MEMORY_ENTRY_LIMIT:
        cache.pop(next(iter(cache)))


def _remember(cache: dict, key, value, ttl_seconds: int) -> None:
    _prune_memory(cache, ttl_seconds)
    cache.pop(key, None)
    cache[key] = (time.monotonic(), value)
    _prune_memory(cache, ttl_seconds)

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
                 post_week_cache: PostWeekDiskCache | None = None,
                 publication_disk_cache: PublicationDiskCache | None = None):
        self.api = api
        self.note_api = note_api
        self.note_disk_cache = note_disk_cache
        self.post_disk_cache = post_disk_cache
        self.published_posts_cache = published_posts_cache
        self.post_week_cache = post_week_cache
        self.publication_disk_cache = publication_disk_cache
        self.cache: dict[int, tuple[float, dict]] = {}
        self.post_cache: dict[str, tuple[float, dict]] = {}
        self.note_cache: dict[str, tuple[float, dict]] = {}
        self.note_cohort_cache: dict[tuple[int, str], tuple[float, dict]] = {}
        self.portfolio_cache: dict[tuple[int, str], tuple[float, dict]] = {}
        self.note_cohort_generation = 0
        self.portfolio_generation = 0
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
        prune_analytics_caches(cache_root.parent)
        return cls(ApiClient(config["publication"], token),
                   ApiClient("https://substack.com", token),
                   NoteDiskCache(cache_root / "notes"),
                   PostDiskCache(cache_root / "posts"),
                   PublishedPostsDiskCache(cache_root / "post-index"),
                   PostWeekDiskCache(cache_root / "post-week"),
                   PublicationDiskCache(cache_root / "publication"))

    def dashboard(self, days: int = 90, *, refresh: bool = False) -> dict:
        if days not in ALLOWED_DAYS:
            raise ValueError("Choose 7, 30, 90, 180, or 365 days.")
        with self.lock:
            if refresh:
                self.note_cohort_cache.clear()
                self.note_cohort_generation += 1
            _prune_memory(self.cache, PUBLICATION_TTL_SECONDS)
            if not refresh:
                if self.publication_disk_cache:
                    value = self.publication_disk_cache.read(days)
                    if value is not None:
                        self.cache.pop(days, None)
                        return dashboard_metrics(value)
                saved = self.cache.get(days)
                if saved and saved[1].get("range", {}).get("end") == _today():
                    return saved[1]
                self.cache.pop(days, None)
            value = dashboard_metrics(fetch_dashboard(self.api, days, post_rows=self.posts(refresh=refresh)))
            cached_on_disk = False
            if self.publication_disk_cache:
                try:
                    self.publication_disk_cache.write(days, value)
                    cached_on_disk = True
                except (OSError, ValueError, TypeError):
                    # A cache write failure must not hide a successful live fetch.
                    pass
            if cached_on_disk:
                self.cache.pop(days, None)
            else:
                _remember(self.cache, days, value, PUBLICATION_TTL_SECONDS)
            return value

    def post(self, post_id: str, *, refresh: bool = False) -> dict:
        post_id = numeric_id(post_id, "post")
        with self.lock:
            if refresh:
                self.portfolio_cache.clear()
                self.portfolio_generation += 1
            _prune_memory(self.post_cache, 300)
            value = self.post_disk_cache.read(post_id) if self.post_disk_cache and not refresh else None
            if value is not None:
                self.post_cache.pop(post_id, None)
            if value is None and not refresh:
                saved = self.post_cache.get(post_id)
                value = saved[1] if saved else None
            if value is None:
                value = fetch_post(self.api, post_id)
                cached_on_disk = False
                if self.post_disk_cache:
                    try:
                        self.post_disk_cache.write(post_id, value)
                        cached_on_disk = True
                    except (OSError, ValueError, TypeError):
                        pass
                if cached_on_disk:
                    self.post_cache.pop(post_id, None)
                else:
                    _remember(self.post_cache, post_id, value, 300)
            direct_note_shares = post_note_shares(ROOT / "substack" / "published-notes", post_id)
            for share in direct_note_shares["notes"]:
                try:
                    # Refreshing a post should not refetch unrelated Note stats.
                    stats = self.note(share["id"])
                    share["link_clicks"] = next(
                        (item.get("value") for item in stats.get("interactions", {}).get("items", [])
                         if item.get("title") == "Link click"), 0
                    )
                except (PullError, LookupError, ValueError, TypeError, KeyError):
                    # The public attachment still establishes the link when
                    # owner-only Note statistics are temporarily unavailable.
                    pass
            index_post = None
            if self.published_posts_cache or self.posts_cache:
                try:
                    index_post = next((row for row in self.posts() if str(row["id"]) == post_id), None)
                except (PullError, ValueError, TypeError, KeyError):
                    pass
            engagement = {**(value.get("engagement") or {}),
                          "restacks": index_post.get("restacks") if index_post else None}
            if index_post:
                # The index refreshes more often than the cached post detail.
                for name in ("likes", "comments"):
                    if index_post.get(name) is not None:
                        engagement[name] = index_post[name]
            return post_detail_metrics({**value, "engagement": engagement,
                                        "direct_note_shares": direct_note_shares})

    def posts(self, *, refresh: bool = False) -> list[dict]:
        with self.lock:
            if refresh:
                self.portfolio_cache.clear()
                self.portfolio_generation += 1
            if self.posts_cache and time.monotonic() - self.posts_cache[0] >= 300:
                self.posts_cache = None
            value = (self.published_posts_cache.read()
                     if self.published_posts_cache and not refresh else None)
            if value is not None:
                self.posts_cache = None
            if value is None and not refresh and self.posts_cache:
                value = self.posts_cache[1]
            if value is None:
                value = fetch_posts(self.api)
                cached_on_disk = False
                if self.published_posts_cache:
                    try:
                        self.published_posts_cache.write(value)
                        cached_on_disk = True
                    except (OSError, ValueError, TypeError):
                        pass
                self.posts_cache = None if cached_on_disk else (time.monotonic(), value)
            return post_index_metrics(value)

    def post_week(self, post_id: str, *, refresh: bool = False) -> dict | None:
        post_id = numeric_id(post_id, "post")
        with self.lock:
            if refresh:
                self.portfolio_cache.clear()
                self.portfolio_generation += 1
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
        cache_key = (limit, _today())
        with self.lock:
            _prune_memory(self.portfolio_cache, COMPARISON_TTL_SECONDS)
            if not refresh and cache_key in self.portfolio_cache:
                return self.portfolio_cache[cache_key][1]
            generation = self.portfolio_generation
        all_posts = post_index_metrics(self.posts())
        posts = sorted(all_posts, key=lambda row: row.get("date") or "", reverse=True)[:limit]
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
                rows.append({**summary, "title": post["title"],
                             "signup_yield": 1000 * summary["signups"] / summary["views"] if summary["views"] else None,
                             "lifetime_views": post.get("views"),
                             "lifetime_signups": post.get("signups"),
                             "lifetime_shares": post.get("shares"),
                             "lifetime_likes": post.get("likes"),
                             "lifetime_comments": post.get("comments"),
                             "lifetime_restacks": post.get("restacks"),
                             "share_rate": post.get("shares_per_1k"),
                             "likes_rate": post.get("likes_per_1k"),
                             "comments_rate": post.get("comments_per_1k"),
                             "restacks_rate": post.get("restacks_per_1k"),
                             "later_views": later_views,
                             "later_multiple": later_views / summary["views"]
                             if later_views is not None and summary["views"] else None})
        result = {"rows": rows, "considered": len(posts), "total": len(all_posts),
                  "incomplete": incomplete, "unavailable": unavailable,
                  "comparison": summarize_post_portfolio(rows)}
        with self.lock:
            if refresh or self.portfolio_generation == generation:
                _remember(self.portfolio_cache, cache_key, result, COMPARISON_TTL_SECONDS)
        return result

    def note(self, note_id: str, *, refresh: bool = False) -> dict:
        note_id = numeric_id(note_id, "Note")
        with self.lock:
            if refresh:
                self.note_cohort_cache.clear()
                self.note_cohort_generation += 1
            _prune_memory(self.note_cache, NOTE_TTL_SECONDS)
            if self.note_disk_cache and not refresh:
                disk_value = self.note_disk_cache.read(note_id)
                if disk_value is not None:
                    self.note_cache.pop(note_id, None)
                    disk_value = {**disk_value, "comparison": note_comparison_metrics(disk_value)}
                    if "preview" not in disk_value:
                        disk_value = {**disk_value, "preview": public_note_preview(
                            ROOT / "substack" / "published-notes", note_id
                        )}
                    return disk_value
            saved = self.note_cache.get(note_id)
            if saved and not refresh:
                return saved[1]
            value = note_stats(self.note_api, note_id)
            value = {**value, "comparison": note_comparison_metrics(value)}
            cached_on_disk = False
            if self.note_disk_cache:
                try:
                    self.note_disk_cache.write(note_id, value)
                    cached_on_disk = True
                except (OSError, ValueError, TypeError):
                    # A cache write failure must not hide a successful live fetch.
                    pass
            if cached_on_disk:
                self.note_cache.pop(note_id, None)
            else:
                _remember(self.note_cache, note_id, value, NOTE_TTL_SECONDS)
            return value

    def note_cohort(self, days: int = 90, *, retry_unavailable: bool = False) -> dict:
        """Compare published Notes in one period, sharing the same result with UI and MCP."""
        if days not in ALLOWED_DAYS:
            raise ValueError("Choose 7, 30, 90, 180, or 365 days.")
        cache_key = (days, _today())
        with self.lock:
            _prune_memory(self.note_cohort_cache, COMPARISON_TTL_SECONDS)
            if not retry_unavailable and cache_key in self.note_cohort_cache:
                return self.note_cohort_cache[cache_key][1]
            generation = self.note_cohort_generation
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
        result = {"days": days, "total": len(events), "rows": rows,
                  "unavailable_ids": unavailable_ids,
                  "lenses": summarize_note_cohort(rows)}
        with self.lock:
            if self.note_cohort_generation == generation:
                _remember(self.note_cohort_cache, cache_key, result, COMPARISON_TTL_SECONDS)
        return result
