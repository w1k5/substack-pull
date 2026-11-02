"""Aggregate performance for one publication post."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .client import ApiClient, PullError, query_path

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
