"""Evidence-backed writer observations from the existing publication snapshot."""

from __future__ import annotations

from .derived import number


def _percent(value: float) -> str:
    return f"{value:+.0f}%"


def editorial_observations(data: dict) -> list[dict]:
    """Return a few defensible observations, never an invented success score."""
    changes = (data.get("briefing") or {}).get("changes") or {}
    days = (data.get("range") or {}).get("days")
    observations = []
    views, subscribers = changes.get("views") or {}, changes.get("subscribers") or {}
    view_change, signup_change = number(views.get("percent")), number(subscribers.get("percent"))
    current_totals = data.get("totals") or {}
    prior_totals = (data.get("previous") or {}).get("totals") or {}
    current_views, prior_views = number(current_totals.get("views")), number(prior_totals.get("views"))
    current_signups = number(current_totals.get("subscribers"))
    prior_signups = number(prior_totals.get("subscribers"))
    ratio_context = ""
    yield_comparison = None
    if (current_views or 0) >= 1000 and (prior_views or 0) >= 1000 \
            and current_signups is not None and prior_signups is not None:
        ratio_context = (f" That is {1000 * current_signups / current_views:.1f} new subscribers "
                         f"per 1,000 publication views, compared with "
                         f"{1000 * prior_signups / prior_views:.1f} previously.")
        yield_comparison = {
            "current": f"{1000 * current_signups / current_views:.1f}",
            "previous": f"{1000 * prior_signups / prior_views:.1f}",
        }
    if view_change is not None and signup_change is not None:
        if view_change >= 20 and signup_change <= 0:
            observations.append({
                "title": "More exposure, without more subscribers",
                "detail": (f"Views changed {_percent(view_change)} while new subscribers changed "
                           f"{_percent(signup_change)} versus the preceding {days} days.{ratio_context}"),
                "path": "/discovery", "basis": "Equal-length publication periods · publication-level ratio",
            })
        elif signup_change >= 20 and signup_change > view_change + 10:
            observations.append({
                "title": "Subscriber growth outpaced views",
                "detail": (f"New subscribers changed {_percent(signup_change)} while views changed "
                           f"{_percent(view_change)} versus the preceding {days} days.{ratio_context}"),
                "path": "/discovery", "basis": "Equal-length publication periods · publication-level ratio",
            })
        if observations:
            observations[0]["comparison"] = {
                "days": days,
                "subscribers": _percent(signup_change),
                "views": _percent(view_change),
                "yield": yield_comparison,
            }
    for key, label in (("subscribers", "New subscribers"), ("views", "Publication views")):
        if observations:
            break
        comparison = changes.get(key) or {}
        delta = number(comparison.get("percent"))
        if delta is not None and abs(delta) >= 10 and len(observations) < 2:
            observations.append({
                "title": f"{label} {'rose' if delta > 0 else 'fell'} {_percent(delta).lstrip('+')}",
                "detail": f"Compared with the preceding {days} days of equal length.",
                "path": "/discovery" if key == "subscribers" else "/",
                "basis": "Equal-length publication periods",
            })

    period = data.get("range") or {}
    posts = [row for row in data.get("posts") or []
             if period.get("start") and period.get("end")
             and period["start"] <= (row.get("publication_day") or "") <= period["end"]]
    candidates = [row for row in posts if number(row.get("signups")) is not None]
    eligible = [row for row in posts if number(row.get("views")) is not None
                and number(row["views"]) >= 1000 and number(row.get("signup_yield")) is not None]
    yield_leader = max(eligible, key=lambda row: row["signup_yield"], default=None)
    if candidates:
        top = max(candidates, key=lambda row: number(row.get("signups")) or 0)
        if (number(top.get("signups")) or 0) > 0:
            detail = (f"{top.get('title') or 'Untitled post'} brought in "
                      f"{int(number(top['signups'])):,} lifetime signups.")
            if len(eligible) >= 2 and yield_leader and top["id"] == yield_leader["id"]:
                detail += (f" It also led {len(eligible)} recent posts with at least 1,000 views "
                           f"at {top['signup_yield']:.1f} signups per 1,000 lifetime views.")
            observations.append({
                "title": "Most signups from a recent post",
                "detail": detail,
                "path": f"/posts/{top['id']}", "basis": "Posts published in this period · lifetime totals",
            })
    if len(eligible) >= 2 and yield_leader and (not candidates or yield_leader["id"] != top["id"]):
        top = yield_leader
        observations.append({
            "title": "Strongest signup yield among recent posts",
            "detail": (f"{top.get('title') or 'Untitled post'} earned "
                       f"{top['signup_yield']:.1f} signups per 1,000 lifetime views."),
            "path": f"/posts/{top['id']}",
            "basis": f"{len(eligible)} posts published in this period with at least 1,000 views",
        })
    return observations[:4]
