"""Read-only MCP tools backed by the shared analytics service."""

from __future__ import annotations

from functools import lru_cache

from ..analytics import AnalyticsService
from .registry import READ_ONLY, mcp


@lru_cache(maxsize=1)
def service() -> AnalyticsService:
    # Resolve the saved session only when a tool is called. Tool discovery does
    # not need Keychain access and credentials never enter MCP responses.
    return AnalyticsService.from_saved_session()


@mcp.tool(annotations=READ_ONLY)
def publication_summary(days: int = 90, refresh: bool = False) -> dict:
    """Get publication totals for 7, 30, 90, 180, or 365 days. Refresh bypasses the five-minute shared cache."""
    data = service().dashboard(days, refresh=refresh)
    return {key: data[key] for key in ("publication", "refreshed_at", "range", "totals", "previous")}


@mcp.tool(annotations=READ_ONLY)
def publication_timeline(days: int = 90, refresh: bool = False) -> dict:
    """Get publication traffic and dated post/Note events. Refresh bypasses the five-minute shared cache."""
    data = service().dashboard(days, refresh=refresh)
    return {key: data[key] for key in ("refreshed_at", "range", "series", "publication_events")}


@mcp.tool(annotations=READ_ONLY)
def publication_sources(days: int = 90, limit: int = 20, refresh: bool = False) -> dict:
    """Compare subscriber and traffic sources. Refresh bypasses the five-minute shared cache."""
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    data = service().dashboard(days, refresh=refresh)
    return {
        "refreshed_at": data["refreshed_at"],
        "range": data["range"],
        "growth_sources": data["growth_sources"][:limit],
        "subscriber_source_series": data["subscriber_source_series"][:limit],
        "subscriber_source_series_error": data["subscriber_source_series_error"],
        "traffic_sources": data["traffic_sources"][:limit],
    }


@mcp.tool(annotations=READ_ONLY)
def list_posts(limit: int = 20, sort_by: str = "date", refresh: bool = False) -> dict:
    """List published posts; the 15-minute disk cache is bypassed when refresh is true. Sort by date, views, opens, shares, signups, or open rate."""
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    if sort_by not in {"date", "views", "opens", "shares", "signups", "open_rate"}:
        raise ValueError("Unsupported sort field.")
    posts = service().posts(refresh=refresh)
    ordered = sorted(posts, key=lambda row: row.get(sort_by) or ("" if sort_by == "date" else 0), reverse=True)
    return {"total": len(posts), "sort_by": sort_by, "posts": ordered[:limit]}


@mcp.tool(annotations=READ_ONLY)
def post_portfolio(limit: int = 60) -> dict:
    """Compare completed first-week views and signups across recent posts, with lifetime context."""
    return service().post_portfolio(limit=limit)


@mcp.tool(annotations=READ_ONLY)
def post_performance(post_id: str, refresh: bool = False) -> dict:
    """Get post reach, traffic, growth, and Note links. Refresh bypasses the one-hour local post cache."""
    return service().post(post_id, refresh=refresh)


@mcp.tool(annotations=READ_ONLY)
def note_performance(note_id: str, include_series: bool = False, refresh: bool = False) -> dict:
    """Get a published Note's reach, surfaces, audience, and interactions. Refresh bypasses the one-hour local cache."""
    data = service().note(note_id.removeprefix("c-"), refresh=refresh)
    if include_series:
        return data
    return {key: value for key, value in data.items() if key != "impression_series"}


@mcp.tool(annotations=READ_ONLY)
def compare_notes(days: int = 90, lens: str = "responses", limit: int = 30) -> dict:
    """Rank published Notes by age-matched reach or reader outcome using the dashboard's comparison math."""
    if lens not in {"pace", "responses", "visits", "clicks", "unconnected"}:
        raise ValueError("Choose pace, responses, visits, clicks, or unconnected.")
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    cohort = service().note_cohort(days)
    by_id = {row["id"]: row for row in cohort["rows"]}
    ranked = [by_id[note_id] for note_id in cohort["lenses"][lens]["ranked_ids"]]
    return {"days": days, "lens": lens, "total": cohort["total"],
            "unavailable_ids": cohort["unavailable_ids"],
            "summary": cohort["lenses"][lens], "rows": ranked[:limit]}
