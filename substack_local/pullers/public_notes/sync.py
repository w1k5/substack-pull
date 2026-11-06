"""Incremental published Note backup with restartable full scans."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import urllib.parse

from .api import ApiClient, query_path
from .common import STATE_VERSION, PullError
from .files import atomic_write_json, atomic_write_text, read_json, utc_now
from .model import (authored_note, note_content_fingerprint, note_markdown,
                    note_permalink, note_snapshot_fingerprint)


class SyncEngine:
    def __init__(
        self,
        api: ApiClient,
        output_dir: Path,
        profile: dict[str, Any],
        *,
        overlap: int = 24,
        now: Callable[[], str] = utc_now,
    ):
        self.api = api
        self.output_dir = output_dir
        self.profile = profile
        self.overlap = max(1, overlap)
        self.now = now
        self.state_path = output_dir / ".sync" / "state.json"

    def _new_state(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_VERSION,
            "profile": self.profile,
            "last_sync_at": None,
            "notes": {},
        }

    def _load_state(self) -> dict[str, Any]:
        state = read_json(self.state_path, None)
        if state is None:
            return self._new_state()
        if not isinstance(state, dict) or state.get("schema_version") != STATE_VERSION:
            raise PullError(f"Unsupported sync state in {self.state_path}.")
        saved_profile = state.get("profile")
        if not isinstance(saved_profile, dict) or str(saved_profile.get("id")) != str(
            self.profile["id"]
        ):
            raise PullError(
                f"{self.output_dir} already belongs to another profile. "
                "Choose a separate --directory."
            )
        if not isinstance(state.get("notes"), dict):
            raise PullError(f"Invalid notes index in {self.state_path}.")
        state["profile"] = self.profile
        return state

    def _write_note(
        self, item: dict[str, Any], note: dict[str, Any], synced_at: str
    ) -> tuple[str, str]:
        note_id = str(note["id"])
        relative_json = Path("notes") / f"{note_id}.json"
        relative_markdown = Path("notes") / f"{note_id}.md"
        envelope = {
            "schema_version": 1,
            "synced_at": synced_at,
            "profile": self.profile,
            "permalink": note_permalink(self.profile, note),
            "note": note,
            "feed_item": item,
        }
        atomic_write_json(self.output_dir / relative_json, envelope)
        atomic_write_text(
            self.output_dir / relative_markdown,
            note_markdown(self.profile, note),
        )
        return relative_json.as_posix(), relative_markdown.as_posix()

    def _page(self, cursor: str | None) -> tuple[list[dict[str, Any]], str | None]:
        path = query_path(
            f"/api/v1/reader/feed/profile/{urllib.parse.quote(str(self.profile['id']), safe='')}",
            {"types": "note", "cursor": cursor},
        )
        payload = self.api.get_json(path)
        if not isinstance(payload, dict):
            raise PullError("Substack returned an unexpected Notes feed shape.")
        items = payload.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise PullError("Substack returned an unexpected Notes items list.")
        next_cursor = payload.get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise PullError("Substack returned an unexpected Notes cursor.")
        return items, next_cursor or None

    def sync(self, *, refresh: bool = False) -> dict[str, Any]:
        state = self._load_state()
        entries: dict[str, dict[str, Any]] = state["notes"]
        checkpoint = state.get("crawl")
        resumed = isinstance(checkpoint, dict)

        if resumed:
            mode = str(checkpoint.get("mode") or "initial")
            cursor = checkpoint.get("next_cursor")
            seen = {str(value) for value in checkpoint.get("seen_ids", [])}
        else:
            mode = "refresh" if refresh else ("initial" if not entries else "incremental")
            cursor = None
            seen: set[str] = set()
            if mode != "incremental":
                state["crawl"] = {
                    "mode": mode,
                    "started_at": self.now(),
                    "next_cursor": None,
                    "seen_ids": [],
                }
                atomic_write_json(self.state_path, state)

        synced_at = self.now()
        known_streak = 0
        page_count = 0
        feed_items = 0
        authored = 0
        created = 0
        updated = 0
        unchanged = 0
        ignored = 0
        fetched_items: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()
        exhausted = False

        while True:
            if cursor is not None:
                if cursor in seen_cursors:
                    raise PullError("Substack repeated a Notes cursor; stopping safely.")
                seen_cursors.add(cursor)
            items, next_cursor = self._page(cursor)
            page_count += 1
            feed_items += len(items)

            for item in items:
                note = authored_note(item, str(self.profile["id"]))
                if note is None:
                    ignored += 1
                    continue
                note_id = str(note["id"])
                if note_id in seen:
                    continue
                seen.add(note_id)
                authored += 1
                previous = entries.get(note_id)
                content_hash = note_content_fingerprint(note)
                snapshot_hash = note_snapshot_fingerprint(item)
                json_default = Path("notes") / f"{note_id}.json"
                markdown_default = Path("notes") / f"{note_id}.md"
                json_relative = str(
                    previous.get("file", json_default.as_posix())
                    if previous
                    else json_default.as_posix()
                )
                markdown_relative = str(
                    previous.get("readable_file", markdown_default.as_posix())
                    if previous
                    else markdown_default.as_posix()
                )
                json_exists = (self.output_dir / json_relative).is_file()
                content_unchanged = bool(
                    previous
                    and previous.get("content_fingerprint") == content_hash
                    and json_exists
                )

                should_write = bool(
                    not previous
                    or previous.get("snapshot_fingerprint") != snapshot_hash
                    or not json_exists
                    or not (self.output_dir / markdown_relative).is_file()
                )
                if should_write:
                    json_relative, markdown_relative = self._write_note(
                        item, note, synced_at
                    )
                    if previous:
                        updated += 1
                    else:
                        created += 1
                    fetched_items.append(
                        {
                            "id": note_id,
                            "date": note.get("date"),
                            "permalink": note_permalink(self.profile, note),
                            "file": str((self.output_dir / json_relative).resolve()),
                            "readable_file": str(
                                (self.output_dir / markdown_relative).resolve()
                            ),
                        }
                    )
                else:
                    unchanged += 1

                entries[note_id] = {
                    "content_fingerprint": content_hash,
                    "snapshot_fingerprint": snapshot_hash,
                    "file": json_relative,
                    "readable_file": markdown_relative,
                    "date": note.get("date"),
                    "edited_at": note.get("edited_at"),
                    "permalink": note_permalink(self.profile, note),
                    "last_seen_at": synced_at,
                    "last_fetched_at": (
                        synced_at
                        if should_write
                        else (previous or {}).get("last_fetched_at")
                    ),
                    "remote_status": "present",
                }
                entries[note_id].pop("missing_since", None)

                if mode == "incremental" and content_unchanged:
                    known_streak += 1
                elif mode == "incremental":
                    known_streak = 0

            cursor = next_cursor
            if mode != "incremental":
                state["crawl"] = {
                    **state["crawl"],
                    "next_cursor": cursor,
                    "seen_ids": sorted(seen),
                    "checkpoint_at": synced_at,
                }
            atomic_write_json(self.state_path, state)

            if cursor is None:
                exhausted = True
                break
            if mode == "incremental" and known_streak >= self.overlap:
                break

        missing = 0
        if mode != "incremental" and exhausted:
            for note_id, entry in entries.items():
                if note_id not in seen:
                    entry["remote_status"] = "missing"
                    entry.setdefault("missing_since", synced_at)
                    missing += 1
            state.pop("crawl", None)

        state["last_sync_at"] = synced_at
        atomic_write_json(self.state_path, state)
        return {
            "profile": self.profile,
            "directory": str(self.output_dir.resolve()),
            "mode": mode,
            "resumed": resumed,
            "complete": mode == "incremental" or exhausted,
            "exhausted_feed": exhausted,
            "pages": page_count,
            "feed_items": feed_items,
            "authored_notes_seen": authored,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "ignored_non_authored_items": ignored,
            "missing_local_preserved": missing,
            "fetched_items": fetched_items,
            "synced_at": synced_at,
        }
