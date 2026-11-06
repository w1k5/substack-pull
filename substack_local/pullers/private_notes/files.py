"""Private Note backup files and local searches."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .constants import NOTE_CATEGORIES
from .model import (PrivateNotesError, item_id, load_zone, local_timestamp,
                    note_body, note_category)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)

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
        raise PrivateNotesError(f"Invalid JSON in {path}: {exc}") from exc

def unwrap_note(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    for key in ("content", "source", "note"):
        nested = value.get(key)
        if isinstance(nested, dict) and (nested.get("id") is not None or nested.get("post_id") is not None):
            return nested
    if value.get("id") is not None or value.get("post_id") is not None:
        return value
    return None

def load_private_notes(output_dir: Path) -> list[dict[str, Any]]:
    state = read_json(output_dir / ".private-sync" / "state.json", None)
    paths: list[Path] = []
    if isinstance(state, dict) and isinstance(state.get("items"), dict):
        for entry in state["items"].values():
            if isinstance(entry, dict) and entry.get("remote_status") == "present" and entry.get("file"):
                paths.append(output_dir / str(entry["file"]))
    else:
        for category in NOTE_CATEGORIES:
            paths.extend(sorted((output_dir / category).glob("*.json")))
    found: dict[str, dict[str, Any]] = {}
    for path in paths:
        note = unwrap_note(read_json(path, None))
        if note is None:
            continue
        found[item_id(note)] = note
    return list(found.values())

def collect_local_notes(
    output_dir: Path, zone_name: str, *, status: str = "all",
    query: str = "", include_preview: bool = True,
) -> list[dict[str, Any]]:
    """Search the local draft and scheduled Note backup in display order."""
    if status not in {"all", "draft", "scheduled"}:
        raise PrivateNotesError("Choose all, draft, or scheduled.")
    zone = load_zone(zone_name)
    notes = load_private_notes(output_dir)
    items: list[dict[str, Any]] = []
    for note in notes:
        category = note_category(note)
        note_status = "scheduled" if category == "note-scheduled" else "draft"
        if status != "all" and status != note_status:
            continue
        body = note_body(note)
        note_id = item_id(note)
        if query and query.casefold() not in f"{note_id} {body}".casefold():
            continue
        item = {
            "id": note_id,
            "status": note_status,
            "scheduled_at": note.get("trigger_at"),
            "scheduled_local": local_timestamp(note.get("trigger_at"), zone) if note.get("trigger_at") else None,
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
        key=lambda item: (str(item.get("edited_at") or ""), item["id"]),
        reverse=True,
    )
    return [*scheduled_items, *draft_items]
