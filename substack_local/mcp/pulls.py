"""Direct local backup workflows used by MCP tools."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import re
from urllib.parse import urlparse

from ..workflows.modules import (
    NOTE_CONFIG, POST_CONFIG, ROOT, post_puller, private_notes, public_notes,
)


def _public_post_url(value: str) -> str:
    parsed = urlparse(value if "://" in value else "https://" + value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.substack\.com", host):
        raise ValueError("Use an HTTPS *.substack.com publication URL.")
    return f"https://{host}"


def _public_post_dir(publication_url: str) -> Path:
    host = urlparse(_public_post_url(publication_url)).hostname
    return ROOT / "substack" / "public-posts" / str(host)


def _profile(value: str) -> str:
    handle = value.removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", handle):
        raise ValueError("Use a Substack profile handle, such as @prettyhostile.")
    return "@" + handle.lower()


def _public_note_dir(profile: str) -> Path:
    return ROOT / "substack" / "published-notes" / _profile(profile)[1:]


def _bounded_limit(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    return limit


def _read_markdown(path: str, directory: str, max_chars: int) -> dict:
    if not 1 <= max_chars <= 50000:
        raise ValueError("Choose max_chars from 1 to 50000.")
    root = Path(directory).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(root) or target.suffix != ".md":
        raise ValueError("The backup did not return a safe Markdown path.")
    body = target.read_text(encoding="utf-8")
    return {
        "readable_file": str(target),
        "markdown": body[:max_chars],
        "total_chars": len(body),
        "truncated": len(body) > max_chars,
    }


def workspace_info() -> dict:
    """Describe the fixed workspace this local MCP instance is configured for."""
    posts = json.loads(POST_CONFIG.read_text(encoding="utf-8"))
    notes = json.loads(NOTE_CONFIG.read_text(encoding="utf-8"))
    post_dir = Path(posts.get("directory") or posts.get("output") or "substack")
    note_dir = Path(notes.get("notes_directory") or notes.get("private_directory") or "substack-notes")
    if not post_dir.is_absolute():
        post_dir = POST_CONFIG.parent / post_dir
    if not note_dir.is_absolute():
        note_dir = NOTE_CONFIG.parent / note_dir
    return {
        "workspace": str(ROOT),
        "publication": posts.get("publication"),
        "post_backup_directory": str(post_dir.resolve()),
        "note_backup_directory": str(note_dir.resolve()),
        "note_timezone": notes.get("timezone"),
        "public_backups_directory": str(ROOT / "substack"),
    }


def backup_status() -> dict:
    result = {}
    post = post_puller()
    try:
        config = post.load_config(POST_CONFIG, None)
        directory = post.resolve_output_dir(POST_CONFIG, config)
        state = post.read_json(directory / ".sync" / "state.json", None)
        if state is None:
            raise post.PullError(f"No sync state exists at {directory}. Run pull first.")
        result["posts"] = {
            "publication": state.get("publication"),
            "directory": str(directory),
            "last_sync_at": state.get("last_sync_at"),
            "categories": {
                category: {
                    "tracked": len(entries),
                    "present": sum(item.get("remote_status") == "present" for item in entries.values()),
                    "missing_local_preserved": sum(item.get("remote_status") == "missing" for item in entries.values()),
                }
                for category, entries in state.get("categories", {}).items()
            },
        }
    except (OSError, ValueError, post.PullError) as exc:
        result["posts"] = {"error": str(exc)}
    private = private_notes()
    try:
        config = private.load_config(NOTE_CONFIG)
        directory = private.output_dir_from(NOTE_CONFIG, config, None)
        notes = private.load_private_notes(directory)
        counts = Counter(private.note_category(note) for note in notes)
        state = private.read_json(directory / ".private-sync" / "state.json", {})
        result["notes"] = {
            "directory": str(directory),
            "last_sync_at": state.get("last_sync_at") if isinstance(state, dict) else None,
            "drafts": counts["note-drafts"],
            "scheduled": counts["note-scheduled"],
            "runway_exists": (directory / "note-runway.html").is_file(),
            "keychain_session_present": private.reusable_session_present(NOTE_CONFIG, config),
        }
    except (OSError, ValueError, private.PrivateNotesError) as exc:
        result["notes"] = {"error": str(exc)}
    return result


def pull_own_posts(refresh_published: bool = False) -> dict:
    return _pull_posts(None, refresh_published)


def pull_public_posts(publication_url: str, refresh_published: bool = False) -> dict:
    return _pull_posts(_public_post_url(publication_url), refresh_published)


def _pull_posts(publication_url: str | None, refresh_published: bool) -> dict:
    post = post_puller()
    config = post.load_config(POST_CONFIG, publication_url)
    directory = post.resolve_output_dir(
        POST_CONFIG, config,
        str(_public_post_dir(publication_url)) if publication_url else None,
    )
    token = None if publication_url else post.KeychainStore().get(post.host_for(config["publication"]))
    api = post.ApiClient(config["publication"], token)
    summary = post.SyncEngine(api, directory, public_only=publication_url is not None).sync(
        refresh_published=refresh_published,
    )
    if summary.get("errors"):
        summary["incomplete"] = True
    return summary


def find_post_copies(query: str = "", category: str = "all", limit: int = 20,
                     publication_url: str | None = None) -> dict:
    if category not in {"all", "drafts", "scheduled", "published"}:
        raise ValueError("Choose all, drafts, scheduled, or published.")
    if publication_url is not None and category not in {"all", "published"}:
        raise ValueError("Public backups contain only published posts.")
    post = post_puller()
    config = post.load_config(POST_CONFIG, _public_post_url(publication_url) if publication_url else None)
    directory = post.resolve_output_dir(
        POST_CONFIG, config,
        str(_public_post_dir(publication_url)) if publication_url else None,
    )
    items = post.collect_local_posts(directory, category=None if category == "all" else category)
    if query:
        needle = query.casefold()
        items = [item for item in items if needle in " ".join(
            str(item.get(key) or "") for key in ("title", "subtitle", "id", "category")
        ).casefold()]
    items = items[:_bounded_limit(limit)]
    return {
        "publication": config["publication"], "directory": str(directory),
        "query": query, "count": len(items), "items": items,
    }


def read_post_copy(post_id: str, publication_url: str | None = None,
                   max_chars: int = 16000) -> dict:
    if not re.fullmatch(r"[0-9]+", post_id):
        raise ValueError("Use a numeric post ID.")
    result = find_post_copies(post_id, limit=100, publication_url=publication_url)
    item = next((row for row in result["items"] if row["id"] == post_id), None)
    if item is None:
        raise LookupError("Post ID is not in the local backup. Pull posts first.")
    if not item.get("readable_file"):
        raise LookupError("This post has no readable Markdown copy. Pull posts again.")
    return {key: item[key] for key in ("id", "title", "category", "updated_at")} | _read_markdown(
        item["readable_file"], result["directory"], max_chars
    )


def pull_notes(days: int = 90, minimum_spacing: int = 3) -> dict:
    private = private_notes()
    config = private.load_config(NOTE_CONFIG)
    directory = private.output_dir_from(NOTE_CONFIG, config, None)
    zone_name = private.zone_name_from(config, None)
    token = private.reusable_session(NOTE_CONFIG, config)
    api = private.PrivateApiClient(token, request_delay=0.25)
    return private.PrivateNotesSync(api, directory, zone_name=zone_name).sync(
        days=days, minimum_spacing=minimum_spacing,
    )


def find_note_copies(query: str = "", status: str = "all", limit: int = 20,
                     include_preview: bool = False) -> dict:
    if status not in {"all", "draft", "scheduled"}:
        raise ValueError("Choose all, draft, or scheduled.")
    private = private_notes()
    config = private.load_config(NOTE_CONFIG)
    directory = private.output_dir_from(NOTE_CONFIG, config, None)
    zone = private.load_zone(private.zone_name_from(config, None))
    items = []
    for note in private.load_private_notes(directory):
        scheduled = private.note_category(note) == "note-scheduled"
        note_status = "scheduled" if scheduled else "draft"
        body = private.note_body(note)
        note_id = private.item_id(note)
        if status != "all" and status != note_status:
            continue
        if query and query.casefold() not in f"{note_id} {body}".casefold():
            continue
        item = {
            "id": note_id, "status": note_status,
            "scheduled_at": note.get("trigger_at"),
            "scheduled_local": private.local_timestamp(note.get("trigger_at"), zone) if scheduled else None,
            "edited_at": note.get("edited_at"),
        }
        if include_preview:
            item["preview"] = re.sub(r"\s+", " ", body).strip()[:240]
        items.append(item)
    scheduled_items = sorted(
        (item for item in items if item["status"] == "scheduled"),
        key=lambda item: (str(item.get("scheduled_at") or ""), item["id"]),
    )
    draft_items = sorted(
        (item for item in items if item["status"] == "draft"),
        key=lambda item: (str(item.get("edited_at") or ""), item["id"]), reverse=True,
    )
    items = [*scheduled_items, *draft_items][:_bounded_limit(limit)]
    return {"count": len(items), "items": items}


def read_note_copy(note_id: str, max_chars: int = 16000) -> dict:
    if not re.fullmatch(r"(?:c-)?[0-9]+", note_id):
        raise ValueError("Use a numeric or c-prefixed Note ID.")
    result = find_note_copies(note_id, limit=100)
    item = next((row for row in result["items"] if row["id"] == note_id), None)
    if item is None:
        raise LookupError("Note ID is not in the local draft/scheduled backup. Pull Notes first.")
    config = json.loads(NOTE_CONFIG.read_text(encoding="utf-8"))
    directory = Path(config.get("notes_directory") or config.get("private_directory") or "substack-notes")
    if not directory.is_absolute():
        directory = NOTE_CONFIG.parent / directory
    category = "note-scheduled" if item["status"] == "scheduled" else "note-drafts"
    path = directory / category / f"{note_id}.md"
    return {key: item[key] for key in ("id", "status", "scheduled_at", "edited_at")} | _read_markdown(
        str(path), str(directory), max_chars
    )


def note_schedule_runway(days: int = 90, minimum_spacing: int = 3) -> dict:
    private = private_notes()
    config = private.load_config(NOTE_CONFIG)
    directory = private.output_dir_from(NOTE_CONFIG, config, None)
    zone_name = private.zone_name_from(config, None)
    notes = private.load_private_notes(directory)
    if not notes:
        raise private.PrivateNotesError(f"No Note JSON files found in {directory}. Run pull first.")
    state = private.read_json(directory / ".private-sync" / "state.json", {})
    synced_at = state.get("last_sync_at") if isinstance(state, dict) else None
    overview_path = directory / "notes.md"
    private.atomic_write_text(overview_path, private.notes_overview(
        [note for note in notes if private.note_category(note) == "note-drafts"],
        [note for note in notes if private.note_category(note) == "note-scheduled"],
        str(synced_at or private.utc_now()), private.load_zone(zone_name),
    ))
    path, payload = private.write_runway(
        directory, notes, start=private.parse_start(None, zone_name),
        days=days, zone_name=zone_name, minimum_spacing=minimum_spacing,
    )
    return {
        "overview_file": str(overview_path.resolve()), "runway_file": str(path),
        "start": payload["start"], "end": payload["end"],
        "timezone": payload["timezone"],
        "scheduled_in_window": payload["scheduledInWindow"],
        "drafts_off_calendar": payload["draftCount"],
    }


def pull_published_notes(profile: str, refresh: bool = False) -> dict:
    profile = _profile(profile)
    public = public_notes()
    config = public.load_config(NOTE_CONFIG, profile)
    directory = public.resolve_output_dir(NOTE_CONFIG, config, str(_public_note_dir(profile)))
    api = public.ApiClient()
    resolved = public.resolve_profile(api, config["profile"])
    return public.SyncEngine(api, directory, resolved).sync(refresh=refresh)


def find_published_notes(profile: str, query: str = "", sort_by: str = "recent",
                         limit: int = 20) -> dict:
    profile = _profile(profile)
    if sort_by not in {"recent", "reactions", "restacks", "replies"}:
        raise ValueError("Choose recent, reactions, restacks, or replies.")
    public = public_notes()
    config = public.load_config(NOTE_CONFIG, profile)
    directory = public.resolve_output_dir(NOTE_CONFIG, config, str(_public_note_dir(profile)))
    items = public.collect_local_notes(directory, query=query, sort_by=sort_by)[:_bounded_limit(limit)]
    return {
        "profile": config["profile"], "directory": str(directory),
        "query": query, "sort": sort_by, "count": len(items), "items": items,
    }
