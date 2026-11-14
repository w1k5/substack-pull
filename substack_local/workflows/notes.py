"""Private Note planning and actions shared by the dashboard and MCP."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import Future
from datetime import date, datetime, timedelta
from threading import Lock, RLock

from .modules import NOTE_CONFIG, private_notes


def suggested_openings(runway: dict) -> list[str]:
    """Choose centered gaps in lightly scheduled weeks at the requested spacing."""
    counts = Counter(event["date"] for event in runway["events"])
    scheduled = [date.fromisoformat(day) for day in counts]
    if not scheduled:
        return []
    spacing = runway["minimumSpacing"]
    start, end = date.fromisoformat(runway["start"]), date.fromisoformat(runway["end"])

    def distance(day: date) -> int:
        return min(abs((day - other).days) for other in scheduled)

    openings = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day.isoformat() in counts:
            continue
        monday = day - timedelta(days=day.weekday())
        week_count = sum(counts[(monday + timedelta(days=i)).isoformat()] for i in range(7))
        nearest = distance(day)
        if (nearest >= spacing and week_count <= 2
                and nearest >= distance(day - timedelta(days=1))
                and nearest >= distance(day + timedelta(days=1))):
            openings.append(day.isoformat())
    return openings


class NotePlanner:
    def __init__(self):
        self.lock = RLock()
        self._refresh_lock = Lock()
        self._refreshes: dict[tuple[int, int], Future] = {}

    def _context(self):
        notes = private_notes()
        config = notes.load_config(NOTE_CONFIG)
        directory = notes.output_dir_from(NOTE_CONFIG, config, None)
        zone_name = notes.zone_name_from(config, None)
        return notes, config, directory, zone_name

    def snapshot(self, *, days: int = 90, spacing: int = 3) -> dict:
        with self.lock:
            notes, _, directory, zone_name = self._context()
            local = notes.load_private_notes(directory)
            payload = notes.runway_payload(
                local, start=datetime.now(notes.load_zone(zone_name)).date(),
                days=days, zone_name=zone_name, minimum_spacing=spacing,
            )
            drafts = []
            for note in local:
                if note.get("trigger_at"):
                    continue
                text = notes.note_body(note)
                drafts.append({
                    "id": notes.item_id(note),
                    "text": text,
                    "preview": text[:240],
                    "edited_at": note.get("edited_at"),
                })
            drafts.sort(key=lambda item: (str(item["edited_at"] or ""), item["id"]), reverse=True)
            state = notes.read_json(directory / ".private-sync" / "state.json", {})
            events_by_day = {}
            for event in payload["events"]:
                events_by_day.setdefault(event["date"], []).append(event)
            return {
                "runway": payload,
                "events_by_day": events_by_day,
                "opening_days": suggested_openings(payload),
                "drafts": drafts,
                "last_sync_at": state.get("last_sync_at") if isinstance(state, dict) else None,
            }

    def refresh(self, *, days: int = 90, spacing: int = 3) -> dict:
        key = (days, spacing)
        with self._refresh_lock:
            pending = self._refreshes.get(key)
            leader = pending is None
            if leader:
                pending = self._refreshes[key] = Future()
        if not leader:
            return pending.result()
        try:
            with self.lock:
                notes, config, directory, zone_name = self._context()
                token = notes.reusable_session(NOTE_CONFIG, config)
                api = notes.PrivateApiClient(token, request_delay=0.25)
                notes.PrivateNotesSync(api, directory, zone_name=zone_name).sync(
                    days=days, minimum_spacing=spacing, export_runway=False,
                )
                snapshot = self.snapshot(days=days, spacing=spacing)
            pending.set_result(snapshot)
            return snapshot
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._refresh_lock:
                self._refreshes.pop(key)

    def preview_draft(self, text: str) -> dict:
        return private_notes().create_note_draft(text, config_path=NOTE_CONFIG)

    def create_draft(self, text: str) -> dict:
        with self.lock:
            return private_notes().create_note_draft(text, apply=True, config_path=NOTE_CONFIG, export_runway=False)

    def preview_schedule(self, note_id: str, at: str) -> dict:
        with self.lock:
            return private_notes().schedule_note(note_id, at, config_path=NOTE_CONFIG)

    def schedule(self, note_id: str, at: str) -> dict:
        with self.lock:
            return private_notes().schedule_note(note_id, at, apply=True, config_path=NOTE_CONFIG, export_runway=False)
