#!/usr/bin/env python3
"""Read-only sync and planning view for Substack draft and scheduled Notes."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


APP_NAME = "substack-notes-pull"
BASE_URL = "https://substack.com"
KEYCHAIN_SERVICE = "com.local.substack-pull"
LEGACY_KEYCHAIN_SERVICE = "com.local.substack-notes-pull"
LEGACY_KEYCHAIN_ACCOUNT = "substack.com"
SUBSTACK_PULL_CONFIG = ".substack-pull.json"
DEFAULT_CONFIG = ".substack-notes-pull.json"
DEFAULT_OUTPUT = "substack-notes"
STATE_VERSION = 1
NOTE_CATEGORIES = ("note-drafts", "note-scheduled")


class PrivateNotesError(RuntimeError):
    """An expected, user-facing Notes error."""


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


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def local_zone_name() -> str:
    configured = os.environ.get("TZ")
    if configured:
        try:
            ZoneInfo(configured)
            return configured
        except ZoneInfoNotFoundError:
            pass
    localtime = Path("/etc/localtime")
    try:
        resolved = localtime.resolve()
        marker = "/zoneinfo/"
        if marker in str(resolved):
            candidate = str(resolved).split(marker, 1)[1]
            ZoneInfo(candidate)
            return candidate
    except (OSError, ZoneInfoNotFoundError):
        pass
    name = datetime.now().astimezone().tzname()
    return str(name or "UTC")


def load_zone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        if name == "UTC":
            return timezone.utc
        raise PrivateNotesError(f"Unknown IANA time zone: {name}") from exc


def local_timestamp(value: Any, zone: timezone | ZoneInfo) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return str(value or "unknown")
    local = parsed.astimezone(zone)
    hour = local.strftime("%I").lstrip("0") or "0"
    zone_label = getattr(zone, "key", None) or local.tzname() or local.strftime("%z")
    return (
        f"{local.strftime('%b')} {local.day}, {local.year} at "
        f"{hour}:{local.strftime('%M %p')} {zone_label}"
    )


def item_id(item: dict[str, Any]) -> str:
    value = item.get("id") or item.get("post_id")
    if value is None:
        raise PrivateNotesError("A Note item did not include an id.")
    return str(value)


def note_category(item: dict[str, Any]) -> str:
    return "note-scheduled" if item.get("trigger_at") else "note-drafts"


def _marked_text(node: dict[str, Any]) -> str:
    text = str(node.get("text", ""))
    for mark in node.get("marks", []):
        if not isinstance(mark, dict):
            continue
        kind = mark.get("type")
        if kind == "link" and mark.get("attrs", {}).get("href"):
            text = f"[{text}]({mark['attrs']['href']})"
        elif kind in {"strong", "bold"}:
            text = f"**{text}**"
        elif kind in {"em", "italic"}:
            text = f"*{text}*"
        elif kind == "code":
            text = f"`{text}`"
    return text


def render_prosemirror(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return _marked_text(node)
    if kind == "hardBreak":
        return "\n"
    if kind in {"horizontal_rule", "horizontalRule"}:
        return "\n\n---\n\n"
    if kind in {"image", "image2"}:
        attrs = node.get("attrs", {})
        source = attrs.get("src") or attrs.get("imageUrl")
        return f"![{attrs.get('alt') or ''}]({source})" if source else ""
    children = "".join(render_prosemirror(child) for child in node.get("content", []))
    if kind == "paragraph":
        return children.rstrip() + "\n\n"
    if kind == "heading":
        level = int(node.get("attrs", {}).get("level") or 2)
        return f"{'#' * max(1, min(6, level))} {children.strip()}\n\n"
    if kind == "blockquote":
        body = children.strip()
        return "\n".join(f"> {line}" for line in body.splitlines()) + "\n\n"
    if kind in {"bulletList", "orderedList"}:
        rendered: list[str] = []
        start = int(node.get("attrs", {}).get("start") or 1)
        for index, child in enumerate(node.get("content", [])):
            body = render_prosemirror(child).strip()
            prefix = f"{start + index}. " if kind == "orderedList" else "- "
            lines = body.splitlines() or [""]
            rendered.append(prefix + lines[0])
            rendered.extend("  " + line for line in lines[1:])
        return "\n".join(rendered) + "\n\n"
    if kind == "listItem":
        return children.strip()
    if kind == "codeBlock":
        language = node.get("attrs", {}).get("language") or ""
        return f"```{language}\n{children.rstrip()}\n```\n\n"
    return children


def note_body(item: dict[str, Any]) -> str:
    document = item.get("body_json")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            document = None
    rendered = render_prosemirror(document).strip() if isinstance(document, dict) else ""
    return rendered or str(item.get("body") or "").strip()


def _attachment_markdown(attachment: dict[str, Any]) -> str:
    kind = str(attachment.get("type") or "attachment")
    if kind == "image":
        url = attachment.get("imageUrl") or attachment.get("url")
        return f"![Attached image]({url})" if url else "- Attached image"
    if kind == "post" and isinstance(attachment.get("post"), dict):
        post = attachment["post"]
        title = str(post.get("title") or post.get("subtitle") or "Attached post")
        url = post.get("canonical_url")
        return f"[{title}]({url})" if url else f"- {title}"
    for key in ("url", "videoUrl", "audioUrl"):
        if attachment.get(key):
            return f"[{kind.title()} attachment]({attachment[key]})"
    return f"- {kind.title()} attachment (details preserved in JSON)"


def note_markdown(item: dict[str, Any], zone: timezone | ZoneInfo) -> str:
    scheduled_at = item.get("trigger_at")
    lines = [
        f"# Note {item_id(item)}",
        "",
        f"- Status: {'scheduled' if scheduled_at else 'draft'}",
        f"- Created: {local_timestamp(item.get('date'), zone)}",
    ]
    if item.get("edited_at"):
        lines.append(f"- Edited: {local_timestamp(item['edited_at'], zone)}")
    if scheduled_at:
        lines.append(f"- Scheduled: {local_timestamp(scheduled_at, zone)}")
    lines.extend(["", note_body(item)])
    attachments = [value for value in item.get("attachments", []) if isinstance(value, dict)]
    if attachments:
        lines.extend(["", "## Attachments", ""])
        lines.extend(_attachment_markdown(value) for value in attachments)
    return "\n".join(lines).rstrip() + "\n"


def notes_overview(
    drafts: list[dict[str, Any]],
    scheduled: list[dict[str, Any]],
    synced_at: str,
    zone: timezone | ZoneInfo,
) -> str:
    ordered_scheduled = sorted(
        scheduled, key=lambda item: (str(item.get("trigger_at") or ""), item_id(item))
    )
    ordered_drafts = sorted(
        drafts,
        key=lambda item: (str(item.get("edited_at") or item.get("date") or ""), item_id(item)),
        reverse=True,
    )
    lines = [
        "# Substack Draft and Scheduled Notes",
        "",
        f"_Last synced: {synced_at}_",
        "",
        f"- Scheduled: {len(ordered_scheduled)}",
        f"- Drafts: {len(ordered_drafts)}",
    ]
    for heading, items in (("Scheduled Notes", ordered_scheduled), ("Draft Notes", ordered_drafts)):
        lines.extend(["", f"## {heading} ({len(items)})"])
        if not items:
            lines.extend(["", "_None._"])
            continue
        for item in items:
            is_scheduled = heading == "Scheduled Notes"
            timestamp = item.get("trigger_at") if is_scheduled else item.get("edited_at") or item.get("date")
            lines.extend(
                [
                    "",
                    f"### {local_timestamp(timestamp, zone)} · Note {item_id(item)}",
                    "",
                    f"**Status:** {'Scheduled' if is_scheduled else 'Draft'}",
                    "",
                    note_body(item),
                ]
            )
            attachments = [value for value in item.get("attachments", []) if isinstance(value, dict)]
            if attachments:
                lines.extend(["", "Attachments:", ""])
                lines.extend(_attachment_markdown(value) for value in attachments)
            lines.extend(["", "---"])
    return "\n".join(lines).rstrip() + "\n"


class KeychainStore:
    def __init__(self, service: str = KEYCHAIN_SERVICE):
        self.service = service

    def _require_macos(self) -> None:
        if sys.platform != "darwin" or shutil.which("security") is None:
            raise PrivateNotesError("macOS Keychain is required, but 'security' is unavailable.")

    def store_interactive(self, account: str) -> None:
        self._require_macos()
        print(
            "Paste the Substack session cookie VALUE at the Keychain prompt "
            "(Safari connect.sid or Chromium substack.sid). Input is hidden."
        )
        result = subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-a",
                account,
                "-s",
                self.service,
                "-l",
                "Substack Notes Pull",
                "-w",
            ],
            check=False,
        )
        if result.returncode != 0:
            raise PrivateNotesError("Keychain did not store the Substack session value.")

    def lookup(self, account: str) -> str | None:
        self._require_macos()
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", self.service, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        token = result.stdout.rstrip("\r\n")
        return token or None

    def get(self, account: str) -> str:
        token = self.lookup(account)
        if token is None:
            raise PrivateNotesError(f"No Substack session is stored for {account}.")
        return token

    def exists(self, account: str) -> bool:
        return self.lookup(account) is not None


class PrivateApiClient:
    def __init__(
        self,
        session_token: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        request_delay: float = 0.25,
        attempts: int = 6,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PrivateNotesError(f"Invalid Notes base URL: {base_url}")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise PrivateNotesError("Notes requests must use HTTPS.")
        if parsed.hostname not in {"127.0.0.1", "localhost", "substack.com"}:
            raise PrivateNotesError("Notes authentication is sent only to substack.com.")
        self.base_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        self.session_token = session_token
        self.timeout = timeout
        self.request_delay = max(0.0, request_delay)
        self.attempts = max(1, attempts)
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper
        self._last_request_at = 0.0

    def get_json(self, path: str) -> Any:
        if not path.startswith("/"):
            raise PrivateNotesError(f"API path must start with '/': {path}")
        remaining = self.request_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleeper(remaining)
        headers = {
            "Accept": "application/json",
            "Cookie": f"substack.sid={self.session_token}; connect.sid={self.session_token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) substack-notes-pull/1",
        }
        url = self.base_url + path
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                self._last_request_at = time.monotonic()
                try:
                    return json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise PrivateNotesError(f"Substack returned non-JSON data for {path}.") from exc
            except urllib.error.HTTPError as exc:
                self._last_request_at = time.monotonic()
                if exc.code in {401, 403}:
                    raise PrivateNotesError(
                        "The Notes session was rejected or expired. Run "
                        "'./substack-pull auth' again."
                    ) from exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_error = exc
                    if attempt + 1 < self.attempts:
                        delay = min(60.0, 2.0 * (2**attempt))
                        self.sleeper(delay)
                        continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise PrivateNotesError(
                    f"Substack request failed ({exc.code}) for {path}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                self._last_request_at = time.monotonic()
                last_error = exc
                if attempt + 1 < self.attempts:
                    self.sleeper(min(30.0, 1.0 * (2**attempt)))
                    continue
        raise PrivateNotesError(f"Substack request failed for {path}: {last_error}")

    def patch_json(self, path: str, payload: dict[str, Any]) -> Any:
        if not path.startswith("/"):
            raise PrivateNotesError(f"API path must start with '/': {path}")
        remaining = self.request_delay - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleeper(remaining)
        raw_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            self.base_url + path,
            data=raw_payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": (
                    f"substack.sid={self.session_token}; "
                    f"connect.sid={self.session_token}"
                ),
                "Origin": self.base_url,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                    "substack-notes-pull/1"
                ),
            },
            method="PATCH",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
            self._last_request_at = time.monotonic()
        except urllib.error.HTTPError as exc:
            self._last_request_at = time.monotonic()
            if exc.code in {401, 403}:
                raise PrivateNotesError(
                    "The Notes session was rejected or expired. Run "
                    "'./substack-pull auth' again."
                ) from exc
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise PrivateNotesError(
                f"Substack rejected the schedule change ({exc.code}): {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            self._last_request_at = time.monotonic()
            raise PrivateNotesError(
                "The schedule request may have reached Substack, but its result could "
                "not be confirmed. Pull again before retrying."
            ) from exc
        try:
            return json.loads(raw) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivateNotesError(
                "Substack accepted the schedule request but returned non-JSON data. "
                "Pull again to verify the result."
            ) from exc


def query_path(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return path + ("?" + urllib.parse.urlencode(clean) if clean else "")


def paginate_private_notes(api: PrivateApiClient, *, limit: int = 20) -> list[dict[str, Any]]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    collected: list[dict[str, Any]] = []
    while True:
        payload = api.get_json(
            query_path("/api/v1/feed/drafts", {"limit": limit, "cursor": cursor})
        )
        if not isinstance(payload, dict):
            raise PrivateNotesError("Unexpected response shape from /api/v1/feed/drafts.")
        drafts = payload.get("drafts", [])
        if not isinstance(drafts, list) or any(not isinstance(item, dict) for item in drafts):
            raise PrivateNotesError("Unexpected drafts list from /api/v1/feed/drafts.")
        collected.extend(drafts)
        next_cursor = payload.get("nextCursor")
        if payload.get("hasMore") is False or not drafts:
            break
        if next_cursor is None:
            if len(drafts) < limit:
                break
            raise PrivateNotesError("Substack reported more Notes without a cursor.")
        cursor = str(next_cursor)
        if cursor in seen_cursors:
            raise PrivateNotesError("Substack repeated a Notes pagination cursor.")
        seen_cursors.add(cursor)
    return collected


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
    template = Path(__file__).resolve().parent.parent / "assets" / "note-runway-template.html"
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


def load_config(path: Path) -> dict[str, Any]:
    config = read_json(path, {})
    if not isinstance(config, dict):
        raise PrivateNotesError(f"Configuration in {path} must be a JSON object.")
    return config


def publication_account(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise PrivateNotesError("A Substack publication URL is required for authentication.")
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host != "substack.com" and not host.endswith(".substack.com"):
        raise PrivateNotesError("Authentication can only be reused for a substack.com host.")
    return host


def shared_session_account(
    config_path: Path,
    config: dict[str, Any],
    publication_override: str | None = None,
) -> str | None:
    direct = publication_override or config.get("session_account") or config.get("publication")
    if direct:
        return publication_account(direct)
    pull_config = read_json(config_path.parent / SUBSTACK_PULL_CONFIG, {})
    if isinstance(pull_config, dict) and pull_config.get("publication"):
        return publication_account(pull_config["publication"])
    return None


def session_candidates(
    config_path: Path, config: dict[str, Any]
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    account = shared_session_account(config_path, config)
    if account:
        candidates.append((KEYCHAIN_SERVICE, account))
    candidates.append((LEGACY_KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_ACCOUNT))
    return candidates


def reusable_session(config_path: Path, config: dict[str, Any]) -> str:
    for service, account in session_candidates(config_path, config):
        token = KeychainStore(service).lookup(account)
        if token:
            return token
    raise PrivateNotesError(
        "No reusable Substack session was found. Run './substack-pull auth' "
        "in your terminal, then try again."
    )


def reusable_session_present(config_path: Path, config: dict[str, Any]) -> bool:
    return any(
        KeychainStore(service).exists(account)
        for service, account in session_candidates(config_path, config)
    )


def save_private_config(path: Path, config: dict[str, Any]) -> None:
    atomic_write_json(path, config)


def output_dir_from(config_path: Path, config: dict[str, Any], override: str | None) -> Path:
    value = (
        override
        or config.get("notes_directory")
        or config.get("private_directory")
        or DEFAULT_OUTPUT
    )
    result = Path(str(value)).expanduser()
    if not result.is_absolute():
        result = config_path.parent / result
    return result.resolve()


def zone_name_from(config: dict[str, Any], override: str | None) -> str:
    value = str(override or config.get("timezone") or local_zone_name())
    load_zone(value)
    return value


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


def schedule_payload(note: dict[str, Any], trigger_at: datetime) -> dict[str, Any]:
    body_json = note.get("body_json") or note.get("bodyJson")
    if not isinstance(body_json, dict):
        raise PrivateNotesError(
            f"Note {item_id(note)} has no editable body document; no change was made."
        )
    payload: dict[str, Any] = {
        "bodyJson": body_json,
        "replyMinimumRole": (
            note.get("reply_minimum_role")
            or note.get("replyMinimumRole")
            or "everyone"
        ),
        "trigger_at": api_timestamp(trigger_at),
    }
    attachment_ids = note.get("attachment_ids") or note.get("attachmentIds")
    if not isinstance(attachment_ids, list):
        attachment_ids = [
            attachment.get("id")
            for attachment in note.get("attachments", [])
            if isinstance(attachment, dict) and attachment.get("id")
        ]
    if attachment_ids:
        payload["attachmentIds"] = [str(value) for value in attachment_ids]
    if "ai_detection_disabled" in note or "aiDetectionDisabled" in note:
        payload["aiDetectionDisabled"] = bool(
            note.get("ai_detection_disabled", note.get("aiDetectionDisabled"))
        )
    return payload


def command_auth(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    if args.directory:
        config["notes_directory"] = args.directory
    if args.timezone:
        load_zone(args.timezone)
        config["timezone"] = args.timezone
    config.setdefault(
        "notes_directory", config.get("private_directory") or DEFAULT_OUTPUT
    )
    config.pop("private_directory", None)
    config.setdefault("timezone", local_zone_name())
    account = shared_session_account(config_path, config, args.publication)
    if account is None:
        raise PrivateNotesError(
            "No Substack publication is configured. Run './substack-pull auth' "
            "or pass --publication https://name.substack.com."
        )
    config["session_account"] = account
    save_private_config(config_path, config)
    store = KeychainStore(KEYCHAIN_SERVICE)
    store.store_interactive(account)
    PrivateApiClient(store.get(account), request_delay=0).get_json(
        "/api/v1/feed/drafts?limit=1"
    )
    print(f"Shared Substack authentication verified for {account}.")
    print(f"Configuration saved to {config_path} (no secret stored there).")
    return 0


def command_configure(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    if args.directory:
        config["notes_directory"] = args.directory
    if args.timezone:
        load_zone(args.timezone)
        config["timezone"] = args.timezone
    config.setdefault(
        "notes_directory", config.get("private_directory") or DEFAULT_OUTPUT
    )
    config.pop("private_directory", None)
    config.setdefault("timezone", local_zone_name())
    save_private_config(config_path, config)
    print(f"Notes directory: {config['notes_directory']}")
    print(f"Time zone: {config['timezone']}")
    print(f"Configuration saved to {config_path}.")
    return 0


def command_pull(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, args.directory)
    zone_name = zone_name_from(config, args.timezone)
    if args.request_delay < 0:
        raise PrivateNotesError("--request-delay cannot be negative.")
    token = reusable_session(config_path, config)
    api = PrivateApiClient(
        token,
        timeout=args.timeout,
        request_delay=args.request_delay,
        attempts=args.attempts,
    )
    summary = PrivateNotesSync(api, output_dir, zone_name=zone_name).sync(
        days=args.days,
        minimum_spacing=args.minimum_spacing,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_schedule(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, args.directory)
    zone_name = zone_name_from(config, args.timezone)
    scheduled_at = parse_schedule_at(args.at, zone_name)
    token = reusable_session(config_path, config)
    api = PrivateApiClient(token, timeout=args.timeout, request_delay=0.25, attempts=3)
    notes = paginate_private_notes(api)
    note = next((value for value in notes if item_id(value) == str(args.note_id)), None)
    if note is None:
        raise PrivateNotesError(
            f"Note {args.note_id} was not found among the account's drafts and "
            "scheduled Notes."
        )
    current_trigger = note.get("trigger_at")
    preview = {
        "note_id": item_id(note),
        "current_status": "scheduled" if current_trigger else "draft",
        "current_scheduled_at": current_trigger,
        "new_scheduled_at": api_timestamp(scheduled_at),
        "timezone": zone_name,
        "applied": False,
    }
    if not args.apply:
        preview["next_step"] = (
            "Run the same command with --apply to send the schedule change."
        )
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    path = f"/api/v1/feed/comment/{urllib.parse.quote(item_id(note), safe='')}"
    api.patch_json(path, schedule_payload(note, scheduled_at))
    summary = PrivateNotesSync(api, output_dir, zone_name=zone_name).sync(
        days=args.days,
        minimum_spacing=args.minimum_spacing,
    )
    refreshed = next(
        (
            value
            for value in load_private_notes(output_dir)
            if item_id(value) == item_id(note)
        ),
        None,
    )
    actual_trigger = refreshed.get("trigger_at") if refreshed else None
    expected_trigger = api_timestamp(scheduled_at)
    if actual_trigger != expected_trigger:
        raise PrivateNotesError(
            "Substack accepted the request, but the refreshed Note did not show the "
            "requested time. Pull again before retrying."
        )
    preview.update(
        {
            "applied": True,
            "verified_scheduled_at": actual_trigger,
            "runway_file": summary["runway_file"],
        }
    )
    preview.pop("next_step", None)
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    return 0


def command_visualize(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, args.directory)
    zone_name = zone_name_from(config, args.timezone)
    notes = load_private_notes(output_dir)
    if not notes:
        raise PrivateNotesError(
            f"No Note JSON files found in {output_dir}. Run pull first."
        )
    state = read_json(output_dir / ".private-sync" / "state.json", {})
    synced_at = (
        state.get("last_sync_at")
        if isinstance(state, dict) and state.get("last_sync_at")
        else utc_now()
    )
    overview_path = output_dir / "notes.md"
    atomic_write_text(
        overview_path,
        notes_overview(
            [note for note in notes if note_category(note) == "note-drafts"],
            [note for note in notes if note_category(note) == "note-scheduled"],
            str(synced_at),
            load_zone(zone_name),
        ),
    )
    destination = Path(args.output).expanduser().resolve() if args.output else None
    path, payload = write_runway(
        output_dir,
        notes,
        start=parse_start(args.start, zone_name),
        days=args.days,
        zone_name=zone_name,
        minimum_spacing=args.minimum_spacing,
        destination=destination,
    )
    print(
        json.dumps(
            {
                "overview_file": str(overview_path.resolve()),
                "runway_file": str(path),
                "start": payload["start"],
                "end": payload["end"],
                "timezone": payload["timezone"],
                "scheduled_in_window": payload["scheduledInWindow"],
                "drafts_off_calendar": payload["draftCount"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_list(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, args.directory)
    zone_name = zone_name_from(config, args.timezone)
    zone = load_zone(zone_name)
    if args.limit < 1:
        raise PrivateNotesError("--limit must be at least 1.")
    notes = load_private_notes(output_dir)
    items: list[dict[str, Any]] = []
    for note in notes:
        category = note_category(note)
        status = "scheduled" if category == "note-scheduled" else "draft"
        if args.status != "all" and args.status != status:
            continue
        body = note_body(note)
        if args.query and args.query.casefold() not in f"{item_id(note)} {body}".casefold():
            continue
        items.append(
            {
                "id": item_id(note),
                "status": status,
                "scheduled_at": note.get("trigger_at"),
                "scheduled_local": local_timestamp(note.get("trigger_at"), zone) if note.get("trigger_at") else None,
                "edited_at": note.get("edited_at"),
                "preview": re.sub(r"\s+", " ", body).strip()[:240],
            }
        )
    scheduled_items = sorted(
        (item for item in items if item["status"] == "scheduled"),
        key=lambda item: (str(item.get("scheduled_at") or ""), item["id"]),
    )
    draft_items = sorted(
        (item for item in items if item["status"] == "draft"),
        key=lambda item: (str(item.get("edited_at") or ""), item["id"]),
        reverse=True,
    )
    items = [*scheduled_items, *draft_items]
    print(json.dumps({"count": len(items), "items": items[: args.limit]}, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, args.directory)
    notes = load_private_notes(output_dir)
    counts = Counter(note_category(note) for note in notes)
    state = read_json(output_dir / ".private-sync" / "state.json", {})
    print(
        json.dumps(
            {
                "directory": str(output_dir),
                "last_sync_at": state.get("last_sync_at") if isinstance(state, dict) else None,
                "drafts": counts["note-drafts"],
                "scheduled": counts["note-scheduled"],
                "runway_exists": (output_dir / "note-runway.html").is_file(),
                "keychain_session_present": reusable_session_present(config_path, config),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def add_local_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-d", "--directory", help="Notes directory")
    parser.add_argument("--timezone", help="IANA time zone, such as America/New_York")


def add_runway_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--days", type=int, default=90, help="rolling horizon in days")
    parser.add_argument(
        "--minimum-spacing",
        type=int,
        default=3,
        help="days required from the nearest scheduled Note for a suggested opening",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Pull draft and scheduled Notes and build a 90-day schedule runway.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser("auth", help="store and verify a session in macOS Keychain")
    add_local_args(auth)
    auth.add_argument("--publication", help="Substack publication URL for the shared session")
    auth.set_defaults(handler=command_auth)

    configure = commands.add_parser("configure", help="set the Notes directory and time zone")
    add_local_args(configure)
    configure.set_defaults(handler=command_configure)

    pull = commands.add_parser("pull", help="pull drafts and scheduled Notes")
    add_local_args(pull)
    add_runway_args(pull)
    pull.add_argument("--request-delay", type=float, default=0.25)
    pull.add_argument("--timeout", type=float, default=30.0)
    pull.add_argument("--attempts", type=int, default=6)
    pull.set_defaults(handler=command_pull)

    schedule = commands.add_parser(
        "schedule", help="schedule a draft or change a scheduled Note's date"
    )
    schedule.add_argument("note_id", help="Note ID from the list command")
    schedule.add_argument(
        "--at",
        required=True,
        help="ISO date and time; a time without an offset uses the configured time zone",
    )
    schedule.add_argument(
        "--apply",
        action="store_true",
        help="send the change to Substack; omission produces a preview only",
    )
    schedule.add_argument("--timeout", type=float, default=30.0)
    add_local_args(schedule)
    add_runway_args(schedule)
    schedule.set_defaults(handler=command_schedule)

    visualize = commands.add_parser("visualize", help="regenerate the local schedule runway")
    add_local_args(visualize)
    add_runway_args(visualize)
    visualize.add_argument("--start", help="first day in YYYY-MM-DD form; defaults to today")
    visualize.add_argument("--output", help="destination HTML file")
    visualize.set_defaults(handler=command_visualize)

    listing = commands.add_parser("list", help="list locally pulled Notes")
    add_local_args(listing)
    listing.add_argument("--status", choices=("all", "draft", "scheduled"), default="all")
    listing.add_argument("--query")
    listing.add_argument("--limit", type=int, default=1000)
    listing.set_defaults(handler=command_list)

    status = commands.add_parser("status", help="show Notes sync status")
    add_local_args(status)
    status.set_defaults(handler=command_status)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.handler(args))
    except PrivateNotesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
