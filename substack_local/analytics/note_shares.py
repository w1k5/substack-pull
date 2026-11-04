"""Find explicit post shares in the public Notes backup.

Only a Note's post attachment establishes a direct link to a post. A Note
published near a post, or a comment that embeds a post, does not.
"""

import json
import re
from html import unescape
from pathlib import Path


def note_preview(note: dict) -> str:
    """Prefer the Note's own text, then the quoted selection of a shared post."""
    body = note.get("body") or note.get("text") or ""
    if not body:
        for attachment in note.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            selection = attachment.get("postSelection") or {}
            body = selection.get("text") or attachment.get("quoted_text") or ""
            if body:
                break
    plain = re.sub(r"<[^>]+>", " ", str(body))
    return " ".join(unescape(plain).split())[:180]


def public_note_preview(backup_root: Path, note_id: str) -> str:
    """Read a Note preview from any locally backed-up public profile."""
    if not backup_root.is_dir():
        return ""
    for path in backup_root.glob(f"*/notes/{note_id}.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        note = item.get("note") or {}
        if isinstance(note, dict) and str(note.get("id")) == note_id:
            return note_preview(note)
    return ""


def post_note_shares(backup_root: Path, post_id: str) -> dict:
    """Return direct shares from all locally backed-up published Note profiles."""
    profiles = [path for path in backup_root.iterdir() if path.is_dir()] if backup_root.is_dir() else []
    notes = []
    latest_sync = None
    for profile_dir in profiles:
        state_path = profile_dir / ".sync" / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict):
            continue
        synced_at = state.get("last_sync_at")
        if synced_at and (latest_sync is None or synced_at > latest_sync):
            latest_sync = synced_at
        for path in (profile_dir / "notes").glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            note = item.get("note") or {}
            if not isinstance(note, dict):
                continue
            # The backup may contain restacks and other feed items. Count only
            # Notes authored by the profile whose archive was pulled.
            profile = item.get("profile") or {}
            if str(note.get("user_id")) != str(profile.get("id")):
                continue
            if not any(
                attachment.get("type") == "post"
                and str((attachment.get("post") or {}).get("id")) == str(post_id)
                for attachment in note.get("attachments") or []
                if isinstance(attachment, dict)
            ):
                continue
            note_id = str(note.get("id") or "")
            if not note_id.isdecimal():
                continue
            record = (state.get("notes") or {}).get(note_id) or {}
            if record.get("remote_status") == "missing":
                continue
            notes.append({
                "id": note_id,
                "published_at": note.get("date"),
                "permalink": item.get("permalink"),
                "profile": profile.get("handle"),
                "preview": note_preview(note),
                "link_clicks": None,
            })
    unique = {note["id"]: note for note in notes}
    return {
        "status": "available" if latest_sync else "not_synced",
        "last_sync_at": latest_sync,
        "notes": sorted(unique.values(), key=lambda note: note["published_at"] or "", reverse=True),
    }
