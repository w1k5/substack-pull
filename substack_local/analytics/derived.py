"""Writer-facing metrics derived from normalized Substack responses."""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime
import math
from zoneinfo import ZoneInfo

from .leaderboard import post_rows

ZONE = ZoneInfo("America/New_York")


def number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def ratio_label(actual, typical) -> str:
    actual, typical = number(actual), number(typical)
    if actual is None or typical is None or typical <= 0:
        return "—"
    ratio = actual / typical
    if ratio >= 3:
        return f"{ratio:.1f}× typical"
    change = math.floor((ratio - 1) * 100 + 0.5)
    return f"{'+' if actual >= typical else ''}{change}%"


def change(current, previous) -> dict:
    current, previous = number(current), number(previous)
    if current is None or previous is None:
        return {"status": "unavailable", "previous": previous, "percent": None}
    if previous == 0:
        return {"status": "new" if current else "unchanged", "previous": previous, "percent": None}
    return {"status": "measured", "previous": previous,
            "percent": 100 * (current - previous) / previous}


def post_index_metrics(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        views = number(row.get("views"))
        signups = number(row.get("signups"))
        published = row.get("date")
        try:
            day = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(ZONE).date().isoformat()
        except (AttributeError, ValueError):
            day = None
        rates = {}
        for name in ("likes", "comments", "restacks", "shares"):
            count = number(row.get(name))
            rates[f"{name}_per_1k"] = (1000 * count / views if views is not None and views >= 1000
                                        and count is not None and count >= 0 else None)
        result.append({**row, "publication_day": day, "meets_view_floor": views is not None and views >= 1000, **rates,
                       "signup_yield": 1000 * signups / views
                       if views is not None and views >= 1000 and signups is not None else None})
    return result


def activity_period(period, series):
    bucket_days = 7 if period.get("days", 0) > 90 else 1
    last = series[-1] if series else None
    try:
        elapsed = (date.fromisoformat(period["end"]) -
                   date.fromisoformat(last[0].replace("/", "-"))).days if last else None
    except (KeyError, ValueError, TypeError, AttributeError):
        elapsed = None
    return {"bucket_days": bucket_days,
            "last_bucket_partial": elapsed is not None and 0 <= elapsed < bucket_days}


def publication_buckets(events, views, source_dates, bucket_days):
    """Match events to their published traffic and subscriber chart buckets."""
    view_dates = []
    for index, point in enumerate(views):
        try:
            view_dates.append((date.fromisoformat(point[0].replace("/", "-")), index))
        except (IndexError, KeyError, TypeError, ValueError, AttributeError):
            continue
    view_dates.sort()
    starts = [start for start, _ in view_dates]
    result = []
    for event in events:
        try:
            day = date.fromisoformat(event["day"])
        except (KeyError, TypeError, ValueError):
            continue
        index = bisect_right(starts, day) - 1
        view_index = (view_dates[index][1]
                      if index >= 0 and (day - starts[index]).days < bucket_days else None)
        source_index = bisect_right(source_dates, event["day"]) - 1
        source_day = source_dates[source_index] if source_index >= 0 else None
        if bucket_days == 1 and source_day != event["day"]:
            source_day = None
        result.append({**event, "view_bucket_index": view_index, "subscriber_bucket_day": source_day})
    return result


def ranked_growth_sources(growth):
    children = {}
    parents = []
    for row in growth:
        if (number(row.get("subscribers")) or 0) <= 0:
            continue
        if row.get("parent"):
            children.setdefault(row["parent"], []).append(row)
        else:
            parents.append(row)
    def subscribers(row):
        return number(row.get("subscribers")) or 0
    return [item for parent in sorted(parents, key=subscribers, reverse=True)
            for item in [parent, *sorted(children.get(parent.get("name"), []), key=subscribers, reverse=True)]]


def discovery_rankings(data, posts):
    attribution = data.get("notes_source_attribution") or {}
    known = {
        "post": {str(row["id"]) for row in posts if row.get("id") is not None},
        "note": {str(row["id"]) for row in data.get("publication_events") or []
                 if row.get("type") == "note" and row.get("id") is not None},
    }
    return {kind: [
        {**item, "in_dashboard": str(item.get("id")) in ids}
        for item in attribution.get("items") or []
        if item.get("kind") == kind and item.get("ownership") != "outside_label"
        and (number(item.get("subscribers")) or 0) > 0
    ][:3] for kind, ids in known.items()}


def dashboard_metrics(data: dict) -> dict:
    totals = data.get("totals") or {}
    previous = (data.get("previous") or {}).get("totals") or {}
    growth = data.get("growth_sources") or []
    subscribers = number(totals.get("subscribers"))
    notes = next((row for row in growth if row.get("parent") == "Substack" and row.get("name") == "Notes"), None)
    substack = next((row for row in growth if not row.get("parent") and row.get("name") == "Substack"), None)
    notes_count = number(notes.get("subscribers")) if notes else None
    substack_count = number(substack.get("subscribers")) if substack else None
    sources = []
    for row in data.get("traffic_sources") or []:
        free, paid = number(row.get("free_signups")), number(row.get("paid_signups"))
        users = number(row.get("users"))
        signups = (free or 0) + (paid or 0) if free is not None or paid is not None else None
        sources.append({**row, "signups": signups,
                        "signup_rate": signups / users if signups is not None and users and users > 0 else None})
    posts = post_index_metrics(data.get("posts") or [])
    period = data.get("range") or {}
    for post in posts:
        day = post["publication_day"]
        post["published_in_period"] = bool(day and period.get("start", "") <= day <= period.get("end", ""))
    views = data.get("series") or []
    activity = activity_period(period, views)
    source_dates = sorted({point[0] for line in data.get("subscriber_source_series") or []
                           for point in line["points"]})
    result = {**data,
            "posts": posts,
            "publication_events": publication_buckets(data.get("publication_events") or [], views,
                                                      source_dates, activity["bucket_days"]),
            "leaderboard_rows": post_rows(posts),
            "activity_period": activity,
            "ranked_growth_sources": ranked_growth_sources(growth),
            "discovery_rankings": discovery_rankings(data, posts),
            "traffic_sources": sources,
            "briefing": {
                "changes": {key: change(totals.get(key), previous.get(key))
                            for key in ("views", "visitors", "subscribers")},
                "notes_attributed": notes_count,
                "notes_share": notes_count / subscribers if notes_count is not None and subscribers and subscribers > 0 else None,
                "substack_attributed": substack_count,
                "substack_share": substack_count / subscribers if substack_count is not None and subscribers and subscribers > 0 else None,
            }}
    from .editorial import editorial_observations
    return {**result, "editorial": {"observations": editorial_observations(result)}}


def post_detail_metrics(post: dict, *, today=None) -> dict:
    today = today or datetime.now(ZONE).date().isoformat()
    daily = sorted((dict(row) for row in post.get("first_week") or []),
                   key=lambda row: number(row.get("day_n")) or 0)
    for metric in ("views", "signups"):
        previous, previous_typical = 0, 0
        for row in daily:
            actual = number(row.get(f"cumulative_{metric}")) or 0
            typical = number((row.get("comps") or {}).get(f"avg_cumulative_{metric}")) or 0
            row[f"daily_{metric}"] = actual - previous
            row[f"typical_daily_{metric}"] = typical - previous_typical
            previous, previous_typical = actual, typical
    complete = [row for row in daily if not row.get("dt") or row["dt"][:10] < today]
    latest = complete[-1] if complete else daily[-1] if daily else None
    week = next((row for row in reversed(complete) if (number(row.get("day_n")) or -1) >= 6), None)
    after_week = []
    if week:
        for name, first, lifetime in (
            ("Views", number(week.get("cumulative_views")), number((post.get("reach") or {}).get("views"))),
            ("Free signups", number(week.get("cumulative_signups")), number((post.get("growth") or {}).get("signups"))),
        ):
            if first is not None and lifetime is not None:
                later = max(0, lifetime - first)
                after_week.append({"name": name, "first": first, "later": later, "lifetime": lifetime,
                                   "first_share": first / lifetime if lifetime else 0,
                                   "later_share": later / lifetime if lifetime else 0})
    performance = None
    if latest:
        views, signups = number(latest.get("cumulative_views")), number(latest.get("cumulative_signups"))
        comps = latest.get("comps") or {}
        typical_views = number(comps.get("avg_cumulative_views"))
        typical_signups = number(comps.get("avg_cumulative_signups"))
        yield_rate = 1000 * signups / views if views and signups is not None else None
        typical_yield = (1000 * typical_signups / typical_views
                         if typical_views and typical_signups is not None else None)
        performance = {
            "day": int(number(latest.get("day_n")) or 0) + 1,
            "current_day": not complete,
            "has_partial_day": len(complete) < len(daily),
            "views": views, "signups": signups, "signup_yield": yield_rate,
            "views_vs_typical": ratio_label(views, typical_views),
            "signups_vs_typical": ratio_label(signups, typical_signups),
            "yield_vs_typical": ratio_label(yield_rate, typical_yield),
        }
    reach = post.get("reach") or {}
    engagement = post.get("engagement") or {}
    traffic = post.get("traffic") or {}
    sources = []
    for row in traffic.get("referrers") or []:
        views = number(row.get("views")) or 0
        if views <= 0:
            continue
        signups = (number(row.get("signups")) or 0) + (number(row.get("subscribes")) or 0)
        sources.append({**row, "attributed_signups": signups,
                        "view_share": number(row.get("percent_of_total_views")) or 0})
    sources.sort(key=lambda row: (-row["attributed_signups"], -(number(row.get("views")) or 0)))
    attributed = sum(row["attributed_signups"] for row in sources)
    leading = [row for row in sources if (number(row.get("views")) or 0) >= 20][:5]
    if not leading:
        leading = sources[:5]
    leading_ids = {id(row) for row in leading}
    sources = [{**row, "signup_share": row["attributed_signups"] / attributed if attributed else 0,
                "leading": id(row) in leading_ids} for row in sources]

    sent = number(reach.get("sent"))
    delivered = number(reach.get("delivered"))
    depth = (engagement.get("scroll_depth") or {}).get("full_post") or (engagement.get("scroll_depth") or {}).get("preview")
    readers = number(depth.get("readers")) if depth else None
    devices = traffic.get("devices") or []
    device_total = sum(number(row.get("views")) or 0 for row in devices)
    lifetime_views = number(reach.get("views"))
    responses = {name: (number(value) * 1000 / lifetime_views
                        if number(value) is not None and lifetime_views and lifetime_views > 0 else None)
                 for name, value in (("likes", engagement.get("likes")),
                                     ("comments", engagement.get("comments")),
                                     ("restacks", engagement.get("restacks")),
                                     ("shares", reach.get("shares")))}
    return {**post, "first_week": daily,
            "story": {"after_week": after_week, "performance": performance},
            "insights": {
                "sources": sources, "attributed_signups": attributed,
                "signup_sources": [row for row in sources if row["attributed_signups"] > 0],
                "delivered_share": delivered / sent if delivered is not None and sent and sent > 0 else None,
                "reading_preview_only": bool(depth and not (engagement.get("scroll_depth") or {}).get("full_post")),
                "reading_shares": {key: (number(depth.get(key)) or 0) / readers if readers and readers > 0 else None
                                   for key in ("reached_25", "reached_50", "reached_75", "reached_100")}
                if depth else {},
                "devices": [{**row, "share": (number(row.get("views")) or 0) / device_total if device_total else None}
                            for row in devices],
                "device_total": device_total,
                "response_rates": responses,
            }}
