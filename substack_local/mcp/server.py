#!/usr/bin/env python3
"""Substack analytics and backup MCP tools backed by the existing pullers."""

from __future__ import annotations

from functools import lru_cache

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..analytics import AnalyticsService
from . import pulls as workflows

mcp = FastMCP("Substack Data")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
LOCAL_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
LOCAL_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
LOCAL_BUILD = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@lru_cache(maxsize=1)
def service() -> AnalyticsService:
    # Resolve the saved session only when a tool is called. Tool discovery does
    # not need Keychain access and credentials never enter MCP responses.
    return AnalyticsService.from_saved_session()


@mcp.tool(annotations=READ_ONLY)
def publication_summary(days: int = 90) -> dict:
    """Get aggregate views, visitors, and subscribers for 30, 90, 180, or 365 days."""
    data = service().dashboard(days)
    return {key: data[key] for key in ("publication", "refreshed_at", "range", "totals")}


@mcp.tool(annotations=READ_ONLY)
def publication_timeline(days: int = 90) -> dict:
    """Get the publication traffic time series and dated post/Note events."""
    data = service().dashboard(days)
    return {key: data[key] for key in ("range", "series", "publication_events")}


@mcp.tool(annotations=READ_ONLY)
def publication_sources(days: int = 90, limit: int = 20) -> dict:
    """Compare subscriber growth sources with traffic sources for a selected range."""
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    data = service().dashboard(days)
    return {
        "range": data["range"],
        "growth_sources": data["growth_sources"][:limit],
        "traffic_sources": data["traffic_sources"][:limit],
    }


@mcp.tool(annotations=READ_ONLY)
def list_posts(limit: int = 20, sort_by: str = "date") -> dict:
    """List published posts, sorted by date, views, opens, shares, signups, or open rate."""
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    if sort_by not in {"date", "views", "opens", "shares", "signups", "open_rate"}:
        raise ValueError("Unsupported sort field.")
    posts = service().posts()
    ordered = sorted(posts, key=lambda row: row.get(sort_by) or ("" if sort_by == "date" else 0), reverse=True)
    return {"total": len(posts), "sort_by": sort_by, "posts": ordered[:limit]}


@mcp.tool(annotations=READ_ONLY)
def post_performance(post_id: str) -> dict:
    """Get a post's first-week momentum, Note events, reach, traffic, engagement, and growth."""
    return service().post(post_id)


@mcp.tool(annotations=READ_ONLY)
def note_performance(note_id: str, include_series: bool = False) -> dict:
    """Get a published Note's reach, surfaces, audience, and interactions by numeric Note ID."""
    data = service().note(note_id.removeprefix("c-"))
    if include_series:
        return data
    return {key: value for key, value in data.items() if key != "impression_series"}


@mcp.tool(annotations=LOCAL_READ)
def workspace_info() -> dict:
    """Identify this MCP server's publication, workspace, and local backup directories without reading credentials."""
    return workflows.workspace_info()


@mcp.tool(annotations=LOCAL_READ)
def backup_status() -> dict:
    """Get local post and Note backup status, including last sync times and counts."""
    return workflows.backup_status()


@mcp.tool(annotations=LOCAL_WRITE)
def pull_own_posts(refresh_published: bool = False) -> dict:
    """Incrementally back up this publication's drafts, scheduled posts, and published posts. Refresh published bodies and stats when requested."""
    return workflows.pull_own_posts(refresh_published)


@mcp.tool(annotations=LOCAL_WRITE)
def pull_public_posts(publication_url: str, refresh_published: bool = False) -> dict:
    """Anonymously back up a public *.substack.com publication, without reading or sending the saved session."""
    return workflows.pull_public_posts(publication_url, refresh_published)


@mcp.tool(annotations=LOCAL_READ)
def find_post_copies(query: str = "", category: str = "all", limit: int = 20,
                     publication_url: str | None = None) -> dict:
    """Search the local post backup by title or ID. Pass a publication URL for an already pulled public backup."""
    return workflows.find_post_copies(query, category, limit, publication_url)


@mcp.tool(annotations=LOCAL_READ)
def read_post_copy(post_id: str, publication_url: str | None = None,
                   max_chars: int = 16000) -> dict:
    """Read one post's local Markdown copy by ID; pull first when the newest version is needed."""
    return workflows.read_post_copy(post_id, publication_url, max_chars)


@mcp.tool(annotations=LOCAL_WRITE)
def pull_notes(days: int = 90, minimum_spacing: int = 3) -> dict:
    """Back up this account's draft and scheduled Notes and rebuild the planning runway. No Note is published or scheduled."""
    return workflows.pull_notes(days, minimum_spacing)


@mcp.tool(annotations=LOCAL_READ)
def find_note_copies(query: str = "", status: str = "all", limit: int = 20,
                     include_preview: bool = False) -> dict:
    """Search local draft and scheduled Notes by ID or text. Body previews are omitted unless requested."""
    return workflows.find_note_copies(query, status, limit, include_preview)


@mcp.tool(annotations=LOCAL_READ)
def read_note_copy(note_id: str, max_chars: int = 16000) -> dict:
    """Read the local Markdown copy of one draft or scheduled Note by ID."""
    return workflows.read_note_copy(note_id, max_chars)


@mcp.tool(annotations=LOCAL_BUILD)
def note_schedule_runway(days: int = 90, minimum_spacing: int = 3) -> dict:
    """Rebuild the local Note planning runway from the backup; this makes no Substack request."""
    return workflows.note_schedule_runway(days, minimum_spacing)


@mcp.tool(annotations=LOCAL_WRITE)
def pull_published_notes(profile: str, refresh: bool = False) -> dict:
    """Only when asked for published Note history: anonymously back up a profile's authored Notes, excluding replies and restacks."""
    return workflows.pull_published_notes(profile, refresh)


@mcp.tool(annotations=LOCAL_READ)
def find_published_notes(profile: str, query: str = "", sort_by: str = "recent",
                         limit: int = 20) -> dict:
    """Search or rank a profile's already pulled published Notes by recency or public engagement."""
    return workflows.find_published_notes(profile, query, sort_by, limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
