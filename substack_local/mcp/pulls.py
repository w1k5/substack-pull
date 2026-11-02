"""MCP adapters for the existing post and Note puller CLIs.

The CLIs own syncing, reconciliation, authentication, and readable rendering.
Running them as child processes keeps their JSON output off MCP's stdio stream.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
POST_CONFIG = ROOT / ".substack-pull.json"
NOTE_CONFIG = ROOT / ".substack-notes-pull.json"
POST_CLI = ROOT / "skills/substack-pull/scripts/substack_pull.py"
NOTE_CLI = ROOT / "skills/substack-notes-pull/scripts/substack_notes_pull.py"


def _run_json(script: Path, args: list[str], *, timeout: int = 270) -> dict:
    try:
        completed = subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Substack command timed out after {timeout} seconds.") from exc
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        message = completed.stderr.strip() or "Substack command returned no JSON."
        raise RuntimeError(message[:1000]) from exc
    if not isinstance(value, dict):
        raise RuntimeError("Substack command returned an unexpected result.")
    if completed.returncode:
        value["incomplete"] = True
    return value


def _post_args(command: str, publication_url: str | None = None) -> list[str]:
    args = ["--config", str(POST_CONFIG), command]
    if publication_url is not None:
        args += ["--publication", _public_post_url(publication_url), "--directory", str(_public_post_dir(publication_url))]
    return args


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
    for name, script, args in (
        ("posts", POST_CLI, _post_args("status")),
        ("notes", NOTE_CLI, ["--config", str(NOTE_CONFIG), "status"]),
    ):
        try:
            result[name] = _run_json(script, args)
        except RuntimeError as exc:
            result[name] = {"error": str(exc)}
    return result


def pull_own_posts(refresh_published: bool = False) -> dict:
    args = _post_args("pull")
    if refresh_published:
        args.append("--refresh-published")
    return _run_json(POST_CLI, args)


def pull_public_posts(publication_url: str, refresh_published: bool = False) -> dict:
    args = _post_args("pull", publication_url) + ["--public"]
    if refresh_published:
        args.append("--refresh-published")
    return _run_json(POST_CLI, args)


def find_post_copies(query: str = "", category: str = "all", limit: int = 20,
                     publication_url: str | None = None) -> dict:
    if category not in {"all", "drafts", "scheduled", "published"}:
        raise ValueError("Choose all, drafts, scheduled, or published.")
    if publication_url is not None and category not in {"all", "published"}:
        raise ValueError("Public backups contain only published posts.")
    args = _post_args("list", publication_url) + ["--category", category, "--limit", str(_bounded_limit(limit))]
    if query:
        args += ["--query", query]
    return _run_json(POST_CLI, args)


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
    return _run_json(NOTE_CLI, ["--config", str(NOTE_CONFIG), "pull", "--days", str(days),
                                "--minimum-spacing", str(minimum_spacing)])


def find_note_copies(query: str = "", status: str = "all", limit: int = 20,
                     include_preview: bool = False) -> dict:
    if status not in {"all", "draft", "scheduled"}:
        raise ValueError("Choose all, draft, or scheduled.")
    args = ["--config", str(NOTE_CONFIG), "list", "--status", status, "--limit", str(_bounded_limit(limit))]
    if query:
        args += ["--query", query]
    result = _run_json(NOTE_CLI, args)
    if not include_preview:
        for item in result.get("items", []):
            item.pop("preview", None)
    return result


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
    return _run_json(NOTE_CLI, ["--config", str(NOTE_CONFIG), "visualize", "--days", str(days),
                                "--minimum-spacing", str(minimum_spacing)])


def pull_published_notes(profile: str, refresh: bool = False) -> dict:
    profile = _profile(profile)
    args = ["public", "--config", str(NOTE_CONFIG), "pull", "--profile", profile,
            "--directory", str(_public_note_dir(profile))]
    if refresh:
        args.append("--refresh")
    return _run_json(NOTE_CLI, args)


def find_published_notes(profile: str, query: str = "", sort_by: str = "recent",
                         limit: int = 20) -> dict:
    profile = _profile(profile)
    if sort_by not in {"recent", "reactions", "restacks", "replies"}:
        raise ValueError("Choose recent, reactions, restacks, or replies.")
    args = ["public", "--config", str(NOTE_CONFIG), "list", "--profile", profile,
            "--directory", str(_public_note_dir(profile)), "--sort", sort_by,
            "--limit", str(_bounded_limit(limit))]
    if query:
        args += ["--query", query]
    return _run_json(NOTE_CLI, args)
