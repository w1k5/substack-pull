"""Note runway and schedule time handling."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable

from .files import atomic_write_text, utc_now
from .model import (PrivateNotesError, item_id, load_zone, note_body, parse_iso)


def runway_payload(
    notes: list[dict[str, Any]],
    *,
    start: date,
    days: int,
    zone_name: str,
    minimum_spacing: int,
) -> dict[str, Any]:
    if days < 1 or days > 366:
        raise PrivateNotesError("--days must be between 1 and 366.")
    if minimum_spacing < 1 or minimum_spacing > 14:
        raise PrivateNotesError("--minimum-spacing must be between 1 and 14.")
    zone = load_zone(zone_name)
    end = start + timedelta(days=days - 1)
    events: list[dict[str, str]] = []
    draft_count = 0
    scheduled_total = 0
    by_date: Counter[str] = Counter()
    for note in notes:
        trigger = parse_iso(note.get("trigger_at"))
        if trigger is None:
            draft_count += 1
            continue
        scheduled_total += 1
        local = trigger.astimezone(zone)
        local_day = local.date()
        if start <= local_day <= end:
            key = local_day.isoformat()
            by_date[key] += 1
            events.append(
                {
                    "date": key,
                    "time": local.strftime("%-I:%M %p") if sys.platform != "win32" else local.strftime("%I:%M %p").lstrip("0"),
                    "id": item_id(note),
                    "text": note_body(note) or "Attachment-only Note",
                    "_order": local.isoformat(),
                }
            )
    events.sort(key=lambda item: (item["_order"], item["id"]))
    for event in events:
        event.pop("_order", None)
    first_monday = start - timedelta(days=start.weekday())
    week_totals: list[int] = []
    week = first_monday
    while week <= end:
        week_totals.append(
            sum(by_date[(week + timedelta(days=offset)).isoformat()] for offset in range(7))
        )
        week += timedelta(days=7)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "timezone": zone_name,
        "minimumSpacing": minimum_spacing,
        "events": events,
        "scheduledInWindow": len(events),
        "scheduledTotal": scheduled_total,
        "draftCount": draft_count,
        "activeDays": len(by_date),
        "busiestWeek": max(week_totals, default=0),
        "generatedAt": utc_now(),
    }

def render_runway_html(payload: dict[str, Any]) -> str:
    template = Path(__file__).with_name("note-runway-template.html")
    try:
        source = template.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PrivateNotesError(f"Runway template is missing: {template}") from exc
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    if "__RUNWAY_DATA__" not in source:
        raise PrivateNotesError(f"Runway template is invalid: {template}")
    return source.replace("__RUNWAY_DATA__", encoded)

def write_runway(
    output_dir: Path,
    notes: list[dict[str, Any]],
    *,
    start: date,
    days: int,
    zone_name: str,
    minimum_spacing: int,
    destination: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    payload = runway_payload(
        notes,
        start=start,
        days=days,
        zone_name=zone_name,
        minimum_spacing=minimum_spacing,
    )
    path = destination or (output_dir / "note-runway.html")
    atomic_write_text(path, render_runway_html(payload))
    return path.resolve(), payload

def parse_start(value: str | None, zone_name: str) -> date:
    if value:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise PrivateNotesError("--start must be YYYY-MM-DD.") from exc
    return datetime.now(load_zone(zone_name)).date()

def parse_schedule_at(
    value: str,
    zone_name: str,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PrivateNotesError(
            "--at must be an ISO date and time, such as '2026-10-30 09:30'."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=load_zone(zone_name))
    scheduled = parsed.astimezone(timezone.utc)
    if scheduled <= now().astimezone(timezone.utc):
        raise PrivateNotesError("--at must be in the future.")
    return scheduled

def api_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
