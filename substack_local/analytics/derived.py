"""Writer-facing metrics derived from normalized Substack responses."""

from __future__ import annotations

from datetime import datetime
import math
from zoneinfo import ZoneInfo

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
        signups = number(row.get("signups")) or 0
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
        result.append({**row, "publication_day": day, **rates,
                       "signup_yield": 1000 * signups / views if views is not None and views >= 1000 else None})
    return result


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
    return {**data,
            "posts": post_index_metrics(data.get("posts") or []),
            "traffic_sources": sources,
            "briefing": {
                "changes": {key: change(totals.get(key), previous.get(key))
                            for key in ("views", "visitors", "subscribers")},
                "notes_attributed": notes_count,
                "notes_share": notes_count / subscribers if notes_count is not None and subscribers and subscribers > 0 else None,
                "substack_attributed": substack_count,
                "substack_share": substack_count / subscribers if substack_count is not None and subscribers and subscribers > 0 else None,
            }}


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
