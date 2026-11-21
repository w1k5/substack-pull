"""MCP tools for local post and Note backups through shared workflows."""

from __future__ import annotations

from ..workflows import backups as workflows
from ..pullers import note_conversations
from .pull_jobs import PullJobs
from .registry import LOCAL_BUILD, LOCAL_READ, LOCAL_WRITE, READ_ONLY, mcp

public_pull_jobs = PullJobs(workflows.ROOT / "substack" / ".pull-jobs")


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
    """Start an anonymous public *.substack.com backup. Poll public_pull_status with the returned job_id before relying on the backup."""
    target = workflows.normalize_publication_url(publication_url)
    return public_pull_jobs.start(
        "public_posts", target, refresh_published,
        lambda progress: workflows.pull_public_posts(target, refresh_published, progress=progress),
    )


@mcp.tool(annotations=LOCAL_READ)
def public_pull_status(job_id: str) -> dict:
    """Check a public post or Note pull by job ID. If running, check again in about 10 seconds. Terminal states are completed, partially_completed, and failed."""
    return public_pull_jobs.status(job_id)


@mcp.tool(annotations=LOCAL_READ)
def find_post_copies(query: str = "", category: str = "all", limit: int = 20,
                     publication_url: str | None = None, offset: int = 0,
                     include_missing: bool = False) -> dict:
    """Page through local post copies by title or ID. Set include_missing to inspect preserved copies absent remotely."""
    return workflows.find_post_copies(query, category, limit, publication_url, offset, include_missing)


@mcp.tool(annotations=LOCAL_READ)
def read_post_copy(post_id: str, publication_url: str | None = None,
                   max_chars: int = 16000, include_missing: bool = False) -> dict:
    """Read one post's local Markdown copy by ID, including a preserved missing copy when requested."""
    return workflows.read_post_copy(post_id, publication_url, max_chars, include_missing)


@mcp.tool(annotations=LOCAL_WRITE)
def pull_post_conversation(post: str) -> dict:
    """Back up visible Note replies on a Substack post by numeric ID or /note/p-ID URL, using the saved account session."""
    return workflows.pull_post_conversation(post)


@mcp.tool(annotations=LOCAL_READ)
def post_conversation_status(post: str) -> dict:
    """Report saved reply counts, pull time, and any child-count gaps for a post conversation."""
    return workflows.post_conversation_status(post)


@mcp.tool(annotations=LOCAL_READ)
def find_post_replies(post: str, query: str = "", limit: int = 20,
                      offset: int = 0, include_preview: bool = False) -> dict:
    """Search and page through locally saved post replies; body previews are opt-in."""
    return workflows.find_post_replies(post, query, limit, offset, include_preview)


@mcp.tool(annotations=LOCAL_READ)
def read_post_reply(post: str, reply_id: str) -> dict:
    """Read one full reply from a locally saved post conversation."""
    return workflows.read_post_reply(post, reply_id)


@mcp.tool(annotations=LOCAL_READ)
def read_post_thread(post: str, reply_id: str, limit: int = 100, offset: int = 0) -> dict:
    """Page through the saved thread containing a reply, including its root and descendants."""
    return workflows.read_post_thread(post, reply_id, limit, offset)


@mcp.tool(annotations=READ_ONLY)
def read_note_conversation(note: str) -> dict:
    """Read a Note or /note/c-ID reply URL, its ancestors, and all visible replies using the saved account session."""
    private = workflows.private_notes()
    config = private.load_config(workflows.NOTE_CONFIG)
    token = private.reusable_session(workflows.NOTE_CONFIG, config)
    api = private.PrivateApiClient(token, request_delay=0.25)
    return note_conversations.read_note_conversation(note, api=api)


@mcp.tool(annotations=LOCAL_WRITE)
def pull_notes(days: int = 90, minimum_spacing: int = 3) -> dict:
    """Back up this account's draft and scheduled Notes and rebuild the planning runway. No Note is published or scheduled."""
    return workflows.pull_notes(days, minimum_spacing)


@mcp.tool(annotations=LOCAL_READ)
def find_note_copies(query: str = "", status: str = "all", limit: int = 20,
                     include_preview: bool = False, offset: int = 0) -> dict:
    """Page through local draft and scheduled Notes by ID or text. Body previews are opt-in."""
    return workflows.find_note_copies(query, status, limit, include_preview, offset)


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
    """When asked for published Note history, start an anonymous backup of authored Notes. Poll public_pull_status with the returned job_id before relying on the backup."""
    target = workflows.normalize_note_profile(profile)
    return public_pull_jobs.start(
        "published_notes", target, refresh,
        lambda progress: workflows.pull_published_notes(target, refresh, progress=progress),
    )


@mcp.tool(annotations=LOCAL_READ)
def published_notes_status(profile: str) -> dict:
    """Report one profile's local published Note sync time, crawl progress, and preserved missing count."""
    return workflows.published_notes_status(profile)


@mcp.tool(annotations=LOCAL_READ)
def find_published_notes(profile: str, query: str = "", sort_by: str = "recent",
                         limit: int = 20, offset: int = 0,
                         include_missing: bool = False,
                         include_preview: bool = False) -> dict:
    """Page through a profile's pulled published Notes. Results omit full bodies; previews are opt-in."""
    return workflows.find_published_notes(profile, query, sort_by, limit, offset,
                                          include_missing, include_preview)


@mcp.tool(annotations=LOCAL_READ)
def read_published_note(profile: str, note_id: str, max_chars: int = 16000,
                        include_missing: bool = False) -> dict:
    """Read one published Note's local Markdown by ID after pulling its profile."""
    return workflows.read_published_note(profile, note_id, max_chars, include_missing)
