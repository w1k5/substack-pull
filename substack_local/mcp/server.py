#!/usr/bin/env python3
"""Assemble the local Substack analytics and backup MCP tools."""

from .analytics_tools import (
    compare_notes, list_posts, note_performance, post_performance,
    post_portfolio, publication_sources, publication_summary,
    publication_timeline, service,
)
from .backup_tools import (
    backup_status, find_note_copies, find_post_copies,
    find_published_notes, note_schedule_runway, published_notes_status,
    pull_notes, pull_own_posts, pull_public_posts, pull_published_notes,
    read_note_copy, read_post_copy, read_published_note, workspace_info,
)
from .note_writes import (
    create_note_draft, create_note_drafts, preview_note_draft, preview_note_drafts,
    preview_note_schedule, schedule_note,
)
from .registry import LOCAL_BUILD, LOCAL_READ, LOCAL_WRITE, READ_ONLY, REMOTE_WRITE, mcp


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
