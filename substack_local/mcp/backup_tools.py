"""MCP tools for local post and Note backups through the existing CLIs."""

from __future__ import annotations

from . import pulls as workflows
from .registry import LOCAL_BUILD, LOCAL_READ, LOCAL_WRITE, mcp


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
