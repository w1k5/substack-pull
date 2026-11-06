"""Local backup workflows shared by the MCP and other callers."""

from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlparse

from .modules import (
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
    return "@" + public_notes().normalize_handle(value)


def _public_note_dir(profile: str) -> Path:
    return ROOT / "substack" / "published-notes" / _profile(profile)[1:]


def _bounded_limit(limit: int) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Choose a limit from 1 to 100.")
    return limit


def _page(items: list[dict], limit: int, offset: int) -> dict:
    limit = _bounded_limit(limit)
    if offset < 0:
        raise ValueError("Choose an offset of zero or greater.")
    total = len(items)
    page = items[offset:offset + limit]
    next_offset = offset + len(page) if offset + len(page) < total else None
    return {"count": len(page), "total": total, "offset": offset,
            "next_offset": next_offset, "items": page}


def _published_note_backup(profile: str):
    profile = _profile(profile)
    public = public_notes()
    config = public.load_config(NOTE_CONFIG, profile)
    directory = public.resolve_output_dir(NOTE_CONFIG, config, str(_public_note_dir(profile)))
    return public, config, directory


def _post_backup(publication_url: str | None):
    publication_url = _public_post_url(publication_url) if publication_url else None
    post = post_puller()
    config = post.load_config(POST_CONFIG, publication_url)
    directory = post.resolve_output_dir(
        POST_CONFIG, config,
        str(_public_post_dir(publication_url)) if publication_url else None,
    )
    return post, config, directory


def _private_note_backup():
    private = private_notes()
    config = private.load_config(NOTE_CONFIG)
    directory = private.output_dir_from(NOTE_CONFIG, config, None)
    return private, config, directory


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
        result["posts"] = post.local_status(directory)
    except (OSError, ValueError, post.PullError) as exc:
        result["posts"] = {"error": str(exc)}
    private = private_notes()
    try:
        config = private.load_config(NOTE_CONFIG)
        directory = private.output_dir_from(NOTE_CONFIG, config, None)
        result["notes"] = private.local_status(NOTE_CONFIG, config, directory)
    except (OSError, ValueError, private.PrivateNotesError) as exc:
        result["notes"] = {"error": str(exc)}
    return result


def pull_own_posts(refresh_published: bool = False) -> dict:
    return _pull_posts(None, refresh_published)


def pull_public_posts(publication_url: str, refresh_published: bool = False) -> dict:
    return _pull_posts(_public_post_url(publication_url), refresh_published)


def _pull_posts(publication_url: str | None, refresh_published: bool) -> dict:
    post, config, directory = _post_backup(publication_url)
    token = None if publication_url else post.KeychainStore().get(post.host_for(config["publication"]))
    api = post.ApiClient(config["publication"], token)
    summary = post.SyncEngine(api, directory, public_only=publication_url is not None).sync(
        refresh_published=refresh_published,
    )
    if summary.get("errors"):
        summary["incomplete"] = True
    return summary


def find_post_copies(query: str = "", category: str = "all", limit: int = 20,
                     publication_url: str | None = None, offset: int = 0,
                     include_missing: bool = False) -> dict:
    if category not in {"all", "drafts", "scheduled", "published"}:
        raise ValueError("Choose all, drafts, scheduled, or published.")
    if publication_url is not None and category not in {"all", "published"}:
        raise ValueError("Public backups contain only published posts.")
    post, config, directory = _post_backup(publication_url)
    items = post.collect_local_posts(
        directory, category=None if category == "all" else category,
        include_missing=include_missing, query=query,
    )
    return {
        "publication": config["publication"], "directory": str(directory),
        "query": query, "category": category, "include_missing": include_missing,
        **_page(items, limit, offset),
    }


def read_post_copy(post_id: str, publication_url: str | None = None,
                   max_chars: int = 16000, include_missing: bool = False) -> dict:
    if not re.fullmatch(r"[0-9]+", post_id):
        raise ValueError("Use a numeric post ID.")
    post, _, directory = _post_backup(publication_url)
    matches = post.collect_local_posts(
        directory, include_missing=include_missing, query=post_id,
    )
    item = next((row for row in matches if row["id"] == post_id), None)
    if item is None:
        raise LookupError("Post ID is not in the local backup. Pull posts first.")
    if not item.get("readable_file"):
        raise LookupError("This post has no readable Markdown copy. Pull posts again.")
    return {key: item[key] for key in ("id", "title", "category", "updated_at")} | _read_markdown(
        item["readable_file"], str(directory), max_chars
    )


def pull_notes(days: int = 90, minimum_spacing: int = 3) -> dict:
    private, config, directory = _private_note_backup()
    zone_name = private.zone_name_from(config, None)
    token = private.reusable_session(NOTE_CONFIG, config)
    api = private.PrivateApiClient(token, request_delay=0.25)
    return private.PrivateNotesSync(api, directory, zone_name=zone_name).sync(
        days=days, minimum_spacing=minimum_spacing,
    )


def find_note_copies(query: str = "", status: str = "all", limit: int = 20,
                     include_preview: bool = False, offset: int = 0) -> dict:
    private, config, directory = _private_note_backup()
    items = private.collect_local_notes(
        directory, private.zone_name_from(config, None),
        status=status, query=query, include_preview=include_preview,
    )
    return {"status": status, **_page(items, limit, offset)}


def read_note_copy(note_id: str, max_chars: int = 16000) -> dict:
    if not re.fullmatch(r"(?:c-)?[0-9]+", note_id):
        raise ValueError("Use a numeric or c-prefixed Note ID.")
    normalized_id = note_id.removeprefix("c-")
    private, config, directory = _private_note_backup()
    matches = private.collect_local_notes(
        directory, private.zone_name_from(config, None),
        query=normalized_id, include_preview=False,
    )
    item = next((row for row in matches if row["id"] == normalized_id), None)
    if item is None:
        raise LookupError("Note ID is not in the local draft/scheduled backup. Pull Notes first.")
    category = "note-scheduled" if item["status"] == "scheduled" else "note-drafts"
    path = directory / category / f"{normalized_id}.md"
    return {key: item[key] for key in ("id", "status", "scheduled_at", "edited_at")} | _read_markdown(
        str(path), str(directory), max_chars
    )


def note_schedule_runway(days: int = 90, minimum_spacing: int = 3) -> dict:
    private, config, directory = _private_note_backup()
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
    public, config, directory = _published_note_backup(profile)
    api = public.ApiClient()
    resolved = public.resolve_profile(api, config["profile"])
    return public.SyncEngine(api, directory, resolved).sync(refresh=refresh)


def published_notes_status(profile: str) -> dict:
    """Get the saved public Note crawl state for one profile."""
    public, _, directory = _published_note_backup(profile)
    return public.local_status(directory)


def find_published_notes(profile: str, query: str = "", sort_by: str = "recent",
                         limit: int = 20, offset: int = 0,
                         include_missing: bool = False,
                         include_preview: bool = False) -> dict:
    if sort_by not in {"recent", "reactions", "restacks", "replies"}:
        raise ValueError("Choose recent, reactions, restacks, or replies.")
    public, config, directory = _published_note_backup(profile)
    items = public.collect_local_notes(
        directory, query=query, sort_by=sort_by,
        include_missing=include_missing, include_body=False,
        include_preview=include_preview,
    )
    page = _page(items, limit, offset)
    for item in page["items"]:
        item.pop("file", None)
        item.pop("readable_file", None)
    return {
        "profile": config["profile"], "directory": str(directory),
        "query": query, "sort": sort_by, "include_missing": include_missing,
        **page,
    }


def read_published_note(profile: str, note_id: str, max_chars: int = 16000,
                        include_missing: bool = False) -> dict:
    """Read one published Note's local Markdown copy, including a preserved missing copy when requested."""
    normalized_id = note_id.removeprefix("c-")
    if not re.fullmatch(r"[0-9]+", normalized_id):
        raise ValueError("Use a numeric or c-prefixed Note ID.")
    public, config, directory = _published_note_backup(profile)
    matches = public.collect_local_notes(
        directory, query=normalized_id, include_missing=include_missing,
        include_body=False, include_preview=False,
    )
    item = next((row for row in matches if row["id"] == normalized_id), None)
    if item is None:
        raise LookupError("Note ID is not in the local published backup. Pull published Notes first.")
    return {
        "profile": config["profile"],
        **{key: item[key] for key in ("id", "date", "edited_at", "permalink", "remote_status")},
        **_read_markdown(item["readable_file"], str(directory), max_chars),
    }
