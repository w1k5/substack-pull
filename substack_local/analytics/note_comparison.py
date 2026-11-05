"""Shared, deterministic Note comparison metrics for the dashboard and MCP."""

from __future__ import annotations

from datetime import datetime
import math
from statistics import median


MIN_RATE_SAMPLE = 100
LENS_FIELDS = {
    "pace": "pace_ratio",
    "visits": "visitRate",
    "responses": "responseRate",
    "clicks": "clickRate",
    "unconnected": "unconnected",
}


def number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _value(items: list, title: str) -> float:
    return next((number(item.get("value")) or 0 for item in items
                 if str(item.get("title") or "").lower() == title), 0)


def _rate(count: float, denominator: float | None) -> float | None:
    return 1000 * count / denominator if denominator is not None and denominator >= MIN_RATE_SAMPLE else None


def _pace(stats: dict) -> dict:
    series = stats.get("impression_series") or []
    actual = next((row.get("points") or [] for row in series if row.get("is_primary")), [])
    typical = next((row.get("points") or [] for row in series if not row.get("is_primary")), [])
    a = number(actual[-1].get("value")) if actual else None
    b = number(typical[-1].get("value")) if typical else None
    age = "same age"
    if actual:
        try:
            first = datetime.fromisoformat(actual[0]["timestamp"].replace("Z", "+00:00"))
            last = datetime.fromisoformat(actual[-1]["timestamp"].replace("Z", "+00:00"))
            hours = (last - first).total_seconds() / 3600
            if math.isfinite(hours):
                age = f"{math.floor(hours + 0.5)}h"
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
    ratio = a / b if a is not None and b is not None and b > 0 else None
    if ratio is None:
        label = "—"
    elif ratio >= 3:
        label = f"{ratio:.1f}× typical"
    else:
        change = math.floor((ratio - 1) * 100 + 0.5)
        label = f"{'+' if a >= b else ''}{change}% vs typical"
    return {"actual": a, "typical": b, "age": age, "ratio": ratio, "label": label}


def note_comparison_metrics(stats: dict) -> dict:
    """Match the Notes table's denominators and sample floors in one place."""
    impressions = number(stats.get("impressions"))
    interactions = (stats.get("interactions") or {}).get("items") or []
    audience = stats.get("audience") or []
    visits = _value(interactions, "profile visit")
    responses = sum(number(item.get("value")) or 0 for item in interactions
                    if str(item.get("title") or "").lower() in {"like", "reply", "share", "restack"})
    clicks = _value(interactions, "link click")
    audience_count = sum(number(item.get("value")) or 0 for item in audience)
    unconnected_count = _value(audience, "unconnected")
    return {
        "impressions": impressions,
        "pace": _pace(stats),
        "visits": visits,
        "responses": responses,
        "clicks": clicks,
        "visitRate": _rate(visits, impressions),
        "responseRate": _rate(responses, impressions),
        "clickRate": _rate(clicks, impressions),
        "audienceCount": audience_count,
        "unconnectedCount": unconnected_count,
        "unconnected": unconnected_count / audience_count if audience_count >= MIN_RATE_SAMPLE else None,
    }


def summarize_note_cohort(rows: list[dict]) -> dict:
    """Return the medians and rank order used by both reader surfaces."""
    result = {}
    for lens, field in LENS_FIELDS.items():
        def outcome(row):
            return row["pace"]["ratio"] if lens == "pace" else row[field]

        ranked = sorted(rows, key=lambda row: (
            outcome(row) is None,
            -(outcome(row) or 0),
            -int(row["id"]),
        ))
        plotted = [row for row in rows if row["pace"]["ratio"] is not None
                   and row["pace"]["ratio"] > 0 and outcome(row) is not None]
        middle = median(outcome(row) for row in plotted) if plotted else None
        result[lens] = {
            "median": middle,
            "plotted": len(plotted),
            "plotted_ids": [str(row["id"]) for row in plotted],
            "standouts": sum(row["pace"]["ratio"] >= 1 and outcome(row) >= middle
                             for row in plotted) if middle is not None else 0,
            "standout_ids": [str(row["id"]) for row in plotted
                             if middle is not None and row["pace"]["ratio"] >= 1
                             and outcome(row) >= middle],
            "ranked_ids": [row["id"] for row in ranked],
        }
    return result
