"""Direct MCP access to the Note draft and schedule logic shared with the CLI."""

from __future__ import annotations

from ..workflows.modules import NOTE_CONFIG, private_notes
from .registry import LOCAL_READ, READ_ONLY, REMOTE_WRITE, mcp


@mcp.tool(annotations=LOCAL_READ)
def preview_note_draft(text: str) -> dict:
    """Preview the normalized body of a new unpublished text Note. Makes no Substack request."""
    return private_notes().create_note_draft(text, config_path=NOTE_CONFIG)


@mcp.tool(annotations=REMOTE_WRITE)
def create_note_draft(text: str) -> dict:
    """After approval of the exact preview, create and verify one unpublished Note draft; never publishes it."""
    return private_notes().create_note_draft(text, apply=True, config_path=NOTE_CONFIG)


@mcp.tool(annotations=LOCAL_READ)
def preview_note_drafts(texts: list[str]) -> dict:
    """Preview 1 to 20 exact unpublished Note bodies for a single batch."""
    return private_notes().create_note_drafts(texts, config_path=NOTE_CONFIG)


@mcp.tool(annotations=REMOTE_WRITE)
def create_note_drafts(texts: list[str]) -> dict:
    """After approval, create a bounded batch sequentially with one initial read and one final verification sync."""
    return private_notes().create_note_drafts(texts, apply=True, config_path=NOTE_CONFIG)


@mcp.tool(annotations=READ_ONLY)
def preview_note_schedule(note_id: str, at: str) -> dict:
    """Fetch a draft or scheduled Note and preview its proposed schedule in the configured time zone."""
    return private_notes().schedule_note(note_id, at, config_path=NOTE_CONFIG)


@mcp.tool(annotations=REMOTE_WRITE)
def schedule_note(note_id: str, at: str) -> dict:
    """After approval of the exact Note and time, schedule or reschedule it and verify the result."""
    return private_notes().schedule_note(note_id, at, apply=True, config_path=NOTE_CONFIG)
