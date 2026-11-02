"""Publication traffic, growth sources, events, and post index."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .client import ApiClient, paginate_posts, query_path

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
