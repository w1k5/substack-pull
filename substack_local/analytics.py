#!/usr/bin/env python3
"""Shared read-only Substack analytics requests and aggregate data shapes."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
import threading
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "substack-pull" / "scripts"))
from substack_pull import (  # noqa: E402
    ApiClient,
    KeychainStore,
    PullError,
    host_for,
    load_config,
    paginate_posts,
    query_path,
)

CONFIG = ROOT / ".substack-pull.json"
ALLOWED_DAYS = {30, 90, 180, 365}


def metric(row: dict, name: str) -> int | float:
    for item in row.get("metrics") or []:
        if item.get("name", "").lower() == name.lower():
            return item.get("total") or 0
    return 0


def source_row(row: dict, *, parent: str | None = None) -> dict:
    return {
        "name": row.get("sourceName") or row.get("source") or "Unknown",
        "category": row.get("category") or "Other",
        "parent": parent,
        "visitors": metric(row, "Traffic"),
        "subscribers": metric(row, "Subscribers"),
    }


def note_stats(api: ApiClient, note_id: str) -> dict:
    """Fetch one published Note's aggregate stats using the puller's numeric ID."""
    payload = api.get_json(f"/api/v1/note_stats/c-{note_id}")
    cards = {card.get("cardId"): card for card in payload.get("cards") or []}
    note = ((cards.get("note") or {}).get("note") or {}).get("note") or {}
    if str(note.get("id")) != f"c-{note_id}":
        raise ValueError("Substack returned stats for a different Note.")

    def header_value(card_id):
        headers = (cards.get(card_id) or {}).get("headers") or []
        return headers[0].get("value") if headers else None

    def rows(card_id):
        return [{key: item.get(key) for key in ("title", "value", "percent")}
                for item in (cards.get(card_id) or {}).get("items") or []]

    graph = (cards.get("impressions") or {}).get("graphData") or {}
    return {
        "id": note_id,
        "permalink": note.get("permalink"),
        "published_at": note.get("timestamp"),
        "last_updated_at": payload.get("lastUpdatedAt"),
        "impressions": header_value("impressions"),
        "impression_series": [{
            "label": series.get("label"),
            "is_primary": series.get("isPrimary"),
            "points": [{"timestamp": point.get("timestamp"), "value": point.get("value")}
                       for point in series.get("values") or []],
        } for series in graph.get("series") or []],
        "shares": header_value("shareValues"),
        "surfaces": rows("surfaces"),
        "audience": rows("audience"),
        "interactions": {
            "total": header_value("interactions"),
            "items": [{"title": item.get("title"), "value": item.get("value")}
                      for item in (cards.get("interactions") or {}).get("items") or []],
        },
    }


def fetch_posts(api: ApiClient) -> list[dict]:
    posts = paginate_posts(api, "/api/v1/post_management/published", "post_date")
    rows = []
    for post in posts:
        stats = post.get("stats") or {}
        rows.append({
            "id": post.get("id"),
            "title": post.get("title") or post.get("draft_title") or "Untitled",
            "date": post.get("post_date"),
            "views": stats.get("views"),
            "opens": stats.get("opened"),
            "sent": stats.get("sent"),
            "open_rate": stats.get("open_rate"),
            "shares": stats.get("shares"),
            "signups": stats.get("signups"),
            "engagement_rate": stats.get("engagement_rate"),
        })
    return rows


def fetch_dashboard(api: ApiClient, days: int, today=None) -> dict:
    today = today or datetime.now(ZoneInfo("America/New_York")).date()
    start = today - timedelta(days=days - 1)
    start_iso, end_iso = start.isoformat(), today.isoformat()

    # Substack's daily timeseries treats `from` as exclusive. Longer ranges
    # switch to weekly buckets, whose first bucket already includes the start.
    series_start = start - timedelta(days=1) if days <= 90 else start
    series = api.get_json(query_path(
        "/api/v1/publication/stats/publication_traffic/timeseries",
        {"from": series_start.isoformat(), "to": end_iso, "category": ""},
    ))
    growth = api.get_json(query_path(
        "/api/v1/publication/stats/growth/sources",
        {"order_by": "users", "order_direction": "desc", "from_date": start_iso,
         "to_date": end_iso},
    ))
    events = api.get_json(query_path(
        "/api/v1/publication/stats/growth/events",
        {"from_date": start_iso, "to_date": end_iso},
    ))
    visitors = []
    offset = 0
    while True:
        page = api.get_json(query_path(
            "/api/v1/publication/stats/visitor_sources",
            {"from_date": start_iso, "to_date": end_iso, "offset": offset,
             "limit": 20, "order_by": "views", "order_direction": "desc"},
        ))
        rows = page.get("rows") or []
        visitors.extend(rows)
        offset += len(rows)
        if not rows or offset >= page.get("total", offset):
            break
    post_rows = fetch_posts(api)

    source_rows = []
    for item in growth.get("sourceMetrics") or []:
        source_rows.append(source_row(item))
        for child in item.get("children") or []:
            source_rows.append(source_row(child, parent=item.get("sourceName")))
    totals = {item.get("name"): item.get("total") for item in growth.get("totals") or []}

    return {
        "publication": api.base_url,
        "refreshed_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "range": {"start": start_iso, "end": end_iso, "days": days},
        "totals": {"views": sum(int(row.get("views") or 0) for row in visitors),
                   "visitors": totals.get("traffic"),
                   "subscribers": totals.get("subscribers")},
        "series": series,
        "publication_events": [{
            "id": event.get("id"),
            "day": datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(
                ZoneInfo("America/New_York")
            ).date().isoformat(),
            "title": event.get("title") or ("Note" if event.get("type") == "note" else "Post"),
            "type": event.get("type"),
        } for event in events.get("pubEvents") or []
            if event.get("date") and event.get("type") in {"note", "text"}],
        "growth_sources": source_rows,
        "traffic_sources": [{
            "name": row.get("source"), "category": row.get("source_category"),
            "views": row.get("views"), "users": row.get("users"),
            "free_signups": row.get("free_signup"),
            "paid_signups": row.get("subscribed"),
        } for row in visitors],
        "posts": post_rows,
    }


def fetch_post(api: ApiClient, post_id: str) -> dict:
    """Fetch the aggregate post detail used by both the dashboard and MCP."""
    detail = api.get_json(f"/api/v1/post_management/detail/{post_id}")
    post = next((p for p in detail.get("posts", []) if str(p.get("id")) == post_id), None)
    if post is None:
        raise LookupError("Post not found")
    stats = post.get("stats") or {}
    first_week = stats.get("firstWeekDailyStats") or []
    dated_rows = [row["dt"][:10] for row in first_week if row.get("dt")]
    if dated_rows:
        first_day = min(dated_rows)
    else:
        first_day = datetime.fromisoformat(post["post_date"].replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")
        ).date().isoformat()
    last_day = (datetime.fromisoformat(first_day).date() + timedelta(days=6)).isoformat()
    activity = api.get_json(query_path(
        "/api/v1/publication/stats/growth/events",
        {"from_date": first_day, "to_date": last_day},
    ))
    notes = []
    for event in activity.get("pubEvents") or []:
        if event.get("type") != "note" or not event.get("date"):
            continue
        event_day = datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")
        ).date().isoformat()
        if first_day <= event_day <= last_day:
            notes.append({"id": event.get("id"), "day": event_day, "date": event["date"],
                          "title": event.get("title") or "Note"})

    # These three requests mirror Reach, Engagement, and Growth. Exclude
    # recipient lists and user details from the returned aggregate data.
    def optional_stats(section):
        try:
            return api.get_json(f"/api/v1/post_management/detail/{post_id}/{section}") or {}
        except PullError:
            return {}

    traffic = optional_stats("traffic")
    engagement = optional_stats("engagement")
    growth = optional_stats("growth")
    return {
        "id": post_id,
        "title": post.get("title") or "Untitled",
        "date": post.get("post_date"),
        "first_week": first_week,
        "notes": notes,
        "comps": stats.get("comps") or {},
        "links": stats.get("links") or [],
        "has_more_links": bool(stats.get("has_more_links")),
        "reach": {key: stats.get(key) for key in (
            "sent", "delivered", "opened", "clicked", "open_rate",
            "click_through_rate", "engagement_rate", "shares", "views",
        )},
        "traffic": {
            "categories": traffic.get("categories") or [],
            "devices": traffic.get("devices") or [],
            "referrers": [{key: row.get(key) for key in (
                "source", "source_category", "views", "percent_of_total_views",
                "signups", "subscribes",
            )} for row in traffic.get("referrers") or []],
        },
        "engagement": {
            "likes": (engagement.get("likes") or {}).get("count"),
            "comments": (engagement.get("commentSummary") or {}).get("total"),
            "commenters": (engagement.get("commenters") or {}).get("count"),
            "scroll_depth": engagement.get("scrollDepth") or {},
        },
        "growth": {
            "signups": (growth.get("signups") or {}).get("total"),
            "subscribes": ((growth.get("subscribes") or {}).get("totals") or {}).get("subscribes"),
            "unsubscribes": (growth.get("unsubscribes") or {}).get("total"),
        },
    }


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
