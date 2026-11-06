"""Published Note backup files, settings, and local search."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .api import normalize_handle
from .common import DEFAULT_OUTPUT, PullError
from .model import note_body


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = handle.name
    os.replace(temporary, path)

def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = handle.name
    os.replace(temporary, path)

def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise PullError(f"Invalid JSON in {path}: {exc}") from exc

def load_config(path: Path, profile_override: str | None) -> dict[str, Any]:
    config = read_json(path, {})
    if not isinstance(config, dict):
        raise PullError(f"Configuration in {path} must be a JSON object.")
    profile = profile_override or config.get("profile")
    if not profile:
        raise PullError(
            f"No profile configured. Run './substack-notes-pull configure "
            f"--profile @handle' first, or pass --profile."
        )
    config["profile"] = "@" + normalize_handle(str(profile))
    config.setdefault("directory", DEFAULT_OUTPUT)
    return config

def save_config(path: Path, config: dict[str, Any]) -> None:
    safe = {
        "profile": "@" + normalize_handle(str(config["profile"])),
        "directory": str(config.get("directory") or DEFAULT_OUTPUT),
    }
    for key in ("notes_directory", "timezone"):
        if config.get(key):
            safe[key] = str(config[key])
    if not safe.get("notes_directory") and config.get("private_directory"):
        safe["notes_directory"] = str(config["private_directory"])
    atomic_write_json(path, safe)

def config_path_from(args: argparse.Namespace) -> Path:
    return Path(args.config).expanduser().resolve()

def resolve_output_dir(
    config_path: Path, config: dict[str, Any], directory_override: str | None
) -> Path:
    value = directory_override or config.get("directory") or DEFAULT_OUTPUT
    result = Path(str(value)).expanduser()
    if not result.is_absolute():
        result = config_path.parent / result
    return result.resolve()

def collect_local_notes(
    output_dir: Path,
    *,
    query: str | None = None,
    include_missing: bool = False,
    include_body: bool = True,
    include_preview: bool = True,
    sort_by: str = "recent",
) -> list[dict[str, Any]]:
    state_path = output_dir / ".sync" / "state.json"
    state = read_json(state_path, None)
    if not isinstance(state, dict):
        raise PullError(f"No sync state exists at {state_path}. Run pull first.")
    results: list[dict[str, Any]] = []
    needle = query.casefold() if query else None
    for note_id, entry in state.get("notes", {}).items():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("remote_status") or "present")
        if status == "missing" and not include_missing:
            continue
        path = output_dir / str(entry.get("file") or "")
        envelope = read_json(path, None)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("note"), dict):
            continue
        note = envelope["note"]
        body = note_body(note)
        if needle and needle not in f"{note_id} {body}".casefold():
            continue
        item = {
            "id": str(note_id),
            "date": note.get("date"),
            "edited_at": note.get("edited_at"),
            "reactions": int(note.get("reaction_count") or 0),
            "restacks": int(note.get("restacks") or 0),
            "replies": int(note.get("children_count") or 0),
            "remote_status": status,
            "permalink": envelope.get("permalink"),
            "file": str(path.resolve()),
            "readable_file": str(path.with_suffix(".md").resolve()),
        }
        if include_body:
            item["body"] = body
        if include_preview:
            item["preview"] = re.sub(r"\s+", " ", body).strip()[:240]
        results.append(item)
    metric = {
        "recent": lambda item: (str(item.get("date") or ""), item["id"]),
        "reactions": lambda item: (item["reactions"], str(item.get("date") or "")),
        "restacks": lambda item: (item["restacks"], str(item.get("date") or "")),
        "replies": lambda item: (item["replies"], str(item.get("date") or "")),
    }[sort_by]
    results.sort(key=metric, reverse=True)
    return results

def local_status(output_dir: Path) -> dict[str, Any]:
    """Describe a public Note backup without contacting Substack."""
    state = read_json(output_dir / ".sync" / "state.json", None)
    if not isinstance(state, dict):
        raise PullError(f"No sync state exists in {output_dir}. Run pull first.")
    entries = state.get("notes", {})
    present = sum(
        1 for entry in entries.values() if entry.get("remote_status") == "present"
    )
    missing = sum(
        1 for entry in entries.values() if entry.get("remote_status") == "missing"
    )
    return {
        "profile": state.get("profile"),
        "directory": str(output_dir),
        "last_sync_at": state.get("last_sync_at"),
        "crawl_in_progress": isinstance(state.get("crawl"), dict),
        "tracked": len(entries),
        "present": present,
        "missing_local_preserved": missing,
    }
