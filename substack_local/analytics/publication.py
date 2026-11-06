"""Publication traffic, growth sources, events, and post index."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .client import ApiClient, PullError, paginate_posts, query_path

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


def fetch_public_restacks(api: ApiClient, post_ids: set[str]) -> dict[str, int]:
    """Match published posts to public archive restack totals in paginated batches."""
    if not post_ids:
        return {}
    archive = ApiClient(api.base_url)
    found: dict[str, int] = {}
    offset = 0
    while len(found) < len(post_ids):
        page = archive.get_json(query_path(
            "/api/v1/archive", {"sort": "new", "search": "", "offset": offset, "limit": 50},
        ))
        posts = page if isinstance(page, list) else page.get("posts") if isinstance(page, dict) else None
        if not isinstance(posts, list) or any(not isinstance(post, dict) for post in posts):
            raise PullError("Unexpected public archive response.")
        for post in posts:
            post_id = str(post.get("id") or "")
            restacks = post.get("restacks")
            if post_id in post_ids and isinstance(restacks, int) and not isinstance(restacks, bool):
                found[post_id] = restacks
        offset += len(posts)
        total = page.get("total") if isinstance(page, dict) else None
        if not posts or (isinstance(total, int) and offset >= total) or (total is None and len(posts) < 50):
            break
    return found


def fetch_posts(api: ApiClient) -> list[dict]:
    posts = paginate_posts(api, "/api/v1/post_management/published", "post_date")
    try:
        restacks = fetch_public_restacks(api, {str(post.get("id")) for post in posts if post.get("id")})
    except (PullError, ValueError, TypeError, KeyError):
        # The authenticated index remains useful when the public archive is unavailable.
        restacks = {}
    rows = []
    for post in posts:
        stats = post.get("stats") or {}
        reactions = post.get("reactions") or {}
        rows.append({
            "id": post.get("id"),
            "title": post.get("title") or post.get("draft_title") or "Untitled",
            "date": post.get("post_date"),
            "views": stats.get("views"),
            "opens": stats.get("opened"),
            "sent": stats.get("sent"),
            "open_rate": stats.get("open_rate"),
            "shares": stats.get("shares"),
            "likes": reactions.get("❤", post.get("reaction_count")),
            "comments": post.get("comment_count"),
            "restacks": restacks.get(str(post.get("id"))),
            "signups": stats.get("signups"),
            "engagement_rate": stats.get("engagement_rate"),
        })
    return rows


def fetch_visitor_sources(api: ApiClient, start_iso: str, end_iso: str) -> list[dict]:
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
    return visitors


def growth_totals(growth: dict, visitors: list[dict]) -> dict:
    totals = {item.get("name"): item.get("total") for item in growth.get("totals") or []}
    return {"views": sum(int(row.get("views") or 0) for row in visitors),
            "visitors": totals.get("traffic"),
            "subscribers": totals.get("subscribers")}


def fetch_subscriber_source_series(api: ApiClient, growth: dict,
                                   start_iso: str, end_iso: str) -> list[dict]:
    """Fetch the source lines from Substack's growth chart in one request.

    Only top-level sources are selected: parent and child lines can overlap.
    Substack's chart allows up to 20 selected sources.
    """
    roots = sorted(
        (row for row in growth.get("sourceMetrics") or []
         if metric(row, "Subscribers") > 0),
        key=lambda row: metric(row, "Subscribers"), reverse=True,
    )[:20]
    if not roots:
        return []
    keys = [row.get("originalSourceName") or row.get("source") for row in roots]
    names = {row.get("originalSourceName") or row.get("source"): row.get("sourceName")
             for row in roots}
    response = api.post_json(
        "/api/v1/publication/stats/growth/partial-timeseries",
        {"order_by": "users", "order_direction": "desc", "from_date": start_iso,
         "to_date": end_iso, "sources": keys},
    )
    lines = []
    for row in response.get("timeseries") or []:
        subscriber = next((item for item in row.get("metrics") or []
                           if item.get("name", "").lower() == "subscribers"), None)
        if not subscriber:
            continue
        lines.append({
            "key": row.get("originalSourceName") or row.get("source"),
            "name": names.get(row.get("originalSourceName") or row.get("source"))
                    or row.get("sourceName") or row.get("source") or "Unknown",
            "subscribers": subscriber.get("total") or 0,
            "points": [[point["date"].replace("/", "-"), point.get("value") or 0]
                       for point in subscriber.get("timeseries") or []
                       if point.get("date")],
        })
    return sorted(lines, key=lambda line: line["subscribers"], reverse=True)


def fetch_dashboard(api: ApiClient, days: int, today=None,
                    post_rows: list[dict] | None = None) -> dict:
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
    try:
        source_series = fetch_subscriber_source_series(api, growth, start_iso, end_iso)
        source_series_error = None
    except (PullError, ValueError, TypeError, KeyError):
        source_series = []
        source_series_error = "Subscriber source trends are unavailable right now."
    events = api.get_json(query_path(
        "/api/v1/publication/stats/growth/events",
        {"from_date": start_iso, "to_date": end_iso},
    ))
    visitors = fetch_visitor_sources(api, start_iso, end_iso)
    previous_start = start - timedelta(days=days)
    previous_end = start - timedelta(days=1)
    previous_growth = api.get_json(query_path(
        "/api/v1/publication/stats/growth/sources",
        {"order_by": "users", "order_direction": "desc",
         "from_date": previous_start.isoformat(), "to_date": previous_end.isoformat()},
    ))
    previous_visitors = fetch_visitor_sources(
        api, previous_start.isoformat(), previous_end.isoformat()
    )
    if post_rows is None:
        post_rows = fetch_posts(api)

    source_rows = []
    for item in growth.get("sourceMetrics") or []:
        source_rows.append(source_row(item))
        for child in item.get("children") or []:
            source_rows.append(source_row(child, parent=item.get("sourceName")))
    return {
        "publication": api.base_url,
        "refreshed_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "range": {"start": start_iso, "end": end_iso, "days": days},
        "totals": growth_totals(growth, visitors),
        "previous": {
            "range": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
            "totals": growth_totals(previous_growth, previous_visitors),
        },
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
        "subscriber_source_series": source_series,
        "subscriber_source_series_error": source_series_error,
        "traffic_sources": [{
            "name": row.get("source"), "category": row.get("source_category"),
            "views": row.get("views"), "users": row.get("users"),
            "free_signups": row.get("free_signup"),
            "paid_signups": row.get("subscribed"),
        } for row in visitors],
        "posts": post_rows,
    }
