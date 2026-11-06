"""Incremental backup of private Note drafts and schedules."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .api import PrivateApiClient, paginate_private_notes
from .constants import STATE_VERSION
from .files import (atomic_write_json, atomic_write_text, fingerprint,
                    read_json, utc_now)
from .model import (PrivateNotesError, item_id, load_zone, note_category,
                    note_markdown, notes_overview)
from .planning import write_runway


class PrivateNotesSync:
    def __init__(
        self,
        api: PrivateApiClient,
        output_dir: Path,
        *,
        zone_name: str,
        now: Callable[[], str] = utc_now,
    ):
        self.api = api
        self.output_dir = output_dir
        self.zone_name = zone_name
        self.zone = load_zone(zone_name)
        self.now = now
        self.state_path = output_dir / ".private-sync" / "state.json"

    def _load_state(self) -> dict[str, Any]:
        state = read_json(self.state_path, None)
        if state is None:
            return {"schema_version": STATE_VERSION, "items": {}, "last_sync_at": None}
        if not isinstance(state, dict) or state.get("schema_version") != STATE_VERSION:
            raise PrivateNotesError(f"Unsupported Notes state in {self.state_path}.")
        if not isinstance(state.get("items"), dict):
            raise PrivateNotesError(f"Invalid Notes state in {self.state_path}.")
        return state

    def sync(self, *, days: int = 90, minimum_spacing: int = 3) -> dict[str, Any]:
        notes = paginate_private_notes(self.api)
        state = self._load_state()
        entries: dict[str, dict[str, Any]] = state["items"]
        synced_at = self.now()
        seen: set[str] = set()
        counts = Counter()
        fetched = 0
        unchanged = 0
        for note in notes:
            note_id = item_id(note)
            category = note_category(note)
            counts[category] += 1
            seen.add(note_id)
            relative_json = Path(category) / f"{note_id}.json"
            relative_markdown = Path(category) / f"{note_id}.md"
            current = fingerprint(note)
            previous = entries.get(note_id, {})
            should_write = (
                previous.get("fingerprint") != current
                or previous.get("file") != relative_json.as_posix()
                or not (self.output_dir / relative_json).is_file()
                or not (self.output_dir / relative_markdown).is_file()
            )
            if should_write:
                envelope = {
                    "schema_version": 1,
                    "synced_at": synced_at,
                    "category": category,
                    "source": note,
                    "content": note,
                }
                atomic_write_json(self.output_dir / relative_json, envelope)
                atomic_write_text(
                    self.output_dir / relative_markdown,
                    note_markdown(note, self.zone),
                )
                fetched += 1
            else:
                unchanged += 1
            entries[note_id] = {
                "category": category,
                "fingerprint": current,
                "file": relative_json.as_posix(),
                "readable_file": relative_markdown.as_posix(),
                "trigger_at": note.get("trigger_at"),
                "last_seen_at": synced_at,
                "last_fetched_at": synced_at if should_write else previous.get("last_fetched_at"),
                "remote_status": "present",
            }
            entries[note_id].pop("missing_since", None)
        missing = 0
        for note_id, entry in entries.items():
            if note_id not in seen:
                entry["remote_status"] = "missing"
                entry.setdefault("missing_since", synced_at)
                missing += 1
        state["last_sync_at"] = synced_at
        state["timezone"] = self.zone_name
        atomic_write_json(self.state_path, state)

        drafts = [note for note in notes if note_category(note) == "note-drafts"]
        scheduled = [note for note in notes if note_category(note) == "note-scheduled"]
        overview_path = self.output_dir / "notes.md"
        atomic_write_text(
            overview_path,
            notes_overview(drafts, scheduled, synced_at, self.zone),
        )
        runway_path, runway = write_runway(
            self.output_dir,
            notes,
            start=datetime.now(self.zone).date(),
            days=days,
            zone_name=self.zone_name,
            minimum_spacing=minimum_spacing,
        )
        return {
            "directory": str(self.output_dir.resolve()),
            "synced_at": synced_at,
            "counts": {
                "drafts": counts["note-drafts"],
                "scheduled": counts["note-scheduled"],
            },
            "fetched": fetched,
            "unchanged": unchanged,
            "missing_local_preserved": missing,
            "overview_file": str(overview_path.resolve()),
            "runway_file": str(runway_path),
            "runway": {
                key: runway[key]
                for key in ("start", "end", "days", "timezone", "scheduledInWindow")
            },
        }
