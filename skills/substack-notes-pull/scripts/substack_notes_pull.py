#!/usr/bin/env python3
"""Read-only, incremental backup of a Substack profile's public Notes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Callable, Iterable
import urllib.error
import urllib.parse
import urllib.request


APP_NAME = "substack-notes-pull"
DEFAULT_CONFIG = ".substack-notes-pull.json"
DEFAULT_OUTPUT = "substack-notes"
DEFAULT_BASE_URL = "https://substack.com"
STATE_VERSION = 1


class PullError(RuntimeError):
    """An expected, user-facing pull error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


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


def normalize_base_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PullError(f"Invalid API base URL: {value}")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise PullError("Substack requests must use HTTPS.")
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def normalize_handle(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise PullError("A Substack profile handle or URL is required.")

    candidate = raw
    if "://" in raw or raw.endswith(".substack.com"):
        url = raw if "://" in raw else "https://" + raw
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if host == "substack.com" or host == "www.substack.com":
            parts = [part for part in parsed.path.split("/") if part]
            if not parts or not parts[0].startswith("@"):
                raise PullError(
                    "Use a Substack profile URL such as https://substack.com/@handle."
                )
            candidate = parts[0][1:]
        elif host.endswith(".substack.com"):
            candidate = host[: -len(".substack.com")]
        else:
            raise PullError("Profile URLs must be on substack.com.")
    else:
        candidate = raw.removeprefix("@").split("/", 1)[0]

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", candidate):
        raise PullError(f"Invalid Substack handle: {candidate}")
    return candidate.lower()


def profile_url(handle: str) -> str:
    return f"https://substack.com/@{handle}"


def query_path(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    return path + ("?" + urllib.parse.urlencode(clean) if clean else "")


class ApiClient:
    """Small anonymous GET client with conservative throttling and retries."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        request_delay: float = 1.25,
        attempts: int = 8,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.base_url = normalize_base_url(base_url)
        self.timeout = timeout
        self.request_delay = max(0.0, request_delay)
        self.attempts = max(1, attempts)
        self.opener = opener or urllib.request.urlopen
        self.sleeper = sleeper
        self.monotonic = monotonic
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        remaining = self.request_delay - (self.monotonic() - self._last_request_at)
        if remaining > 0:
            self.sleeper(remaining)

    @staticmethod
    def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
        header = exc.headers.get("Retry-After") if exc.headers else None
        if header:
            try:
                return min(120.0, max(0.0, float(header)))
            except ValueError:
                try:
                    target = parsedate_to_datetime(header)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    return min(
                        120.0,
                        max(0.0, (target - datetime.now(timezone.utc)).total_seconds()),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        if exc.code == 429:
            return min(60.0, 5.0 * (2**attempt))
        return min(30.0, 1.0 * (2**attempt))

    def _get(self, path: str, accept: str) -> bytes:
        if not path.startswith("/"):
            raise PullError(f"API path must start with '/': {path}")
        url = self.base_url + path
        headers = {
            "Accept": accept,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) substack-notes-pull/1",
        }
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            self._throttle()
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                self._last_request_at = self.monotonic()
                return raw
            except urllib.error.HTTPError as exc:
                self._last_request_at = self.monotonic()
                if exc.code in {401, 403}:
                    raise PullError(
                        "Substack denied anonymous access. The profile or Note may be "
                        "private, restricted, or unavailable."
                    ) from exc
                if exc.code == 404:
                    raise PullError(f"Substack did not find {path}.") from exc
                if exc.code == 429 or 500 <= exc.code < 600:
                    last_error = exc
                    if attempt + 1 < self.attempts:
                        delay = self._retry_after(exc, attempt)
                        print(
                            f"Substack returned {exc.code}; retrying in {delay:g}s...",
                            file=sys.stderr,
                        )
                        self.sleeper(delay)
                        continue
                detail = exc.read(500).decode("utf-8", errors="replace")
                raise PullError(
                    f"Substack request failed ({exc.code}) for {path}: {detail}"
                ) from exc
            except urllib.error.URLError as exc:
                self._last_request_at = self.monotonic()
                last_error = exc
                if attempt + 1 < self.attempts:
                    self.sleeper(min(30.0, 1.0 * (2**attempt)))
                    continue
        raise PullError(f"Substack request failed for {path}: {last_error}")

    def get_json(self, path: str) -> Any:
        raw = self._get(path, "application/json")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PullError(f"Substack returned non-JSON data for {path}.") from exc

    def get_text(self, path: str) -> str:
        raw = self._get(path, "text/html,application/xhtml+xml")
        return raw.decode("utf-8", errors="replace")


def parse_preloads(html: str) -> dict[str, Any]:
    match = re.search(
        r"window\._preloads\s*=\s*JSON\.parse\((\"(?:\\.|[^\"\\])*\")\)",
        html,
        re.DOTALL,
    )
    if not match:
        raise PullError("Substack's profile page did not contain profile metadata.")
    try:
        encoded = json.loads(match.group(1))
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise PullError("Substack returned unreadable profile metadata.") from exc
    if not isinstance(value, dict):
        raise PullError("Substack returned an unexpected profile metadata shape.")
    return value


def resolve_profile(api: ApiClient, reference: str) -> dict[str, Any]:
    handle = normalize_handle(reference)
    html = api.get_text(f"/@{urllib.parse.quote(handle, safe='')}")
    preload = parse_preloads(html)
    raw = preload.get("profile")
    if not isinstance(raw, dict) or raw.get("id") is None:
        raise PullError(f"Substack did not expose a public profile for @{handle}.")
    resolved_handle = normalize_handle(str(raw.get("handle") or handle))
    return {
        "id": str(raw["id"]),
        "handle": resolved_handle,
        "name": str(raw.get("name") or resolved_handle),
        "bio": raw.get("bio"),
        "url": profile_url(resolved_handle),
    }


def _marked_text(node: dict[str, Any]) -> str:
    text = str(node.get("text", ""))
    for mark in node.get("marks", []):
        if not isinstance(mark, dict):
            continue
        kind = mark.get("type")
        if kind == "link":
            href = mark.get("attrs", {}).get("href")
            if href:
                text = f"[{text}]({href})"
        elif kind in {"strong", "bold"}:
            text = f"**{text}**"
        elif kind in {"em", "italic"}:
            text = f"*{text}*"
        elif kind == "code":
            text = f"`{text}`"
    return text


def render_prosemirror(node: Any) -> str:
    """Render the common Note ProseMirror nodes as readable Markdown."""
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


def note_body(note: dict[str, Any]) -> str:
    document = note.get("body_json")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            document = None
    rendered = render_prosemirror(document).strip() if isinstance(document, dict) else ""
    if rendered:
        return rendered
    return str(note.get("body") or "").strip()


def _attachment_markdown(attachment: dict[str, Any]) -> str:
    kind = str(attachment.get("type") or "attachment")
    if kind == "image":
        url = attachment.get("imageUrl") or attachment.get("url")
        return f"![Attached image]({url})" if url else "- Attached image"
    if kind == "post":
        post = attachment.get("post")
        if isinstance(post, dict):
            title = str(post.get("title") or post.get("subtitle") or "Attached post")
            url = post.get("canonical_url")
            return f"[{title}]({url})" if url else f"- {title}"
    if kind == "comment":
        comment = attachment.get("comment")
        if isinstance(comment, dict):
            author = comment.get("handle")
            user = comment.get("user")
            if not author and isinstance(user, dict):
                author = user.get("handle")
            body = note_body(comment).replace("\n", " ").strip()
            note_id = comment.get("id")
            if author and note_id:
                url = f"https://substack.com/@{author}/note/c-{note_id}"
                return f"> [{('@' + str(author))}]({url}): {body}".rstrip()
            return f"> {body}".rstrip()
    for key in ("url", "videoUrl", "audioUrl"):
        if attachment.get(key):
            return f"[{kind.title()} attachment]({attachment[key]})"
    return f"- {kind.title()} attachment (details preserved in JSON)"


def note_permalink(profile: dict[str, Any], note: dict[str, Any]) -> str:
    return f"https://substack.com/@{profile['handle']}/note/c-{note['id']}"


def note_markdown(profile: dict[str, Any], note: dict[str, Any]) -> str:
    permalink = note_permalink(profile, note)
    lines = [
        f"# Note {note['id']}",
        "",
        f"- Profile: [@{profile['handle']}]({profile['url']})",
        f"- Published: {note.get('date') or 'unknown'}",
    ]
    if note.get("edited_at"):
        lines.append(f"- Edited: {note['edited_at']}")
    lines.extend(
        [
            f"- Permalink: {permalink}",
            f"- Reactions: {int(note.get('reaction_count') or 0)}",
            f"- Restacks: {int(note.get('restacks') or 0)}",
            f"- Replies: {int(note.get('children_count') or 0)}",
            "",
            note_body(note),
        ]
    )
    attachments = [
        item for item in note.get("attachments", []) if isinstance(item, dict)
    ]
    if attachments:
        lines.extend(["", "## Attachments", ""])
        lines.extend(_attachment_markdown(item) for item in attachments)
    return "\n".join(lines).rstrip() + "\n"


def authored_note(item: Any, profile_id: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("type") != "comment":
        return None
    context = item.get("context")
    if not isinstance(context, dict) or context.get("type") != "note":
        return None
    note = item.get("comment")
    if not isinstance(note, dict) or note.get("id") is None:
        return None
    if str(note.get("user_id")) != str(profile_id):
        return None
    if str(note.get("ancestor_path") or "").strip("/"):
        return None
    return note


def note_content_fingerprint(note: dict[str, Any]) -> str:
    return digest(
        {
            key: note.get(key)
            for key in (
                "id",
                "user_id",
                "body",
                "body_json",
                "attachments",
                "date",
                "edited_at",
                "language",
            )
        }
    )


def note_snapshot_fingerprint(item: dict[str, Any]) -> str:
    return digest(
        {
            key: item.get(key)
            for key in ("comment", "context", "post", "publication")
        }
    )


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
    atomic_write_json(
        path,
        {
            "profile": "@" + normalize_handle(str(config["profile"])),
            "directory": str(config.get("directory") or DEFAULT_OUTPUT),
        },
    )


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
        results.append(
            {
                "id": str(note_id),
                "date": note.get("date"),
                "edited_at": note.get("edited_at"),
                "body": body,
                "preview": re.sub(r"\s+", " ", body).strip()[:240],
                "reactions": int(note.get("reaction_count") or 0),
                "restacks": int(note.get("restacks") or 0),
                "replies": int(note.get("children_count") or 0),
                "remote_status": status,
                "permalink": envelope.get("permalink"),
                "file": str(path.resolve()),
                "readable_file": str(path.with_suffix(".md").resolve()),
            }
        )
    metric = {
        "recent": lambda item: (str(item.get("date") or ""), item["id"]),
        "reactions": lambda item: (item["reactions"], str(item.get("date") or "")),
        "restacks": lambda item: (item["restacks"], str(item.get("date") or "")),
        "replies": lambda item: (item["replies"], str(item.get("date") or "")),
    }[sort_by]
    results.sort(key=metric, reverse=True)
    return results


def command_pull(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.profile)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    if args.overlap < 1:
        raise PullError("--overlap must be at least 1.")
    if args.request_delay < 0:
        raise PullError("--request-delay cannot be negative.")
    api = ApiClient(
        timeout=args.timeout,
        request_delay=args.request_delay,
        attempts=args.attempts,
    )
    profile = resolve_profile(api, config["profile"])
    summary = SyncEngine(
        api,
        output_dir,
        profile,
        overlap=args.overlap,
    ).sync(refresh=args.refresh)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_configure(args: argparse.Namespace) -> int:
    path = config_path_from(args)
    existing = read_json(path, {})
    if not isinstance(existing, dict):
        raise PullError(f"Configuration in {path} must be a JSON object.")
    profile = args.profile or existing.get("profile")
    if not profile:
        raise PullError("--profile is required the first time you configure the puller.")
    config = {
        "profile": "@" + normalize_handle(str(profile)),
        "directory": args.directory or existing.get("directory") or DEFAULT_OUTPUT,
    }
    save_config(path, config)
    print(f"Profile: {config['profile']}")
    print(f"Directory: {config['directory']}")
    print(f"Configuration saved to {path} (no authentication is used).")
    return 0


def command_status(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.profile)
    output_dir = resolve_output_dir(config_path, config, args.directory)
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
    print(
        json.dumps(
            {
                "profile": state.get("profile"),
                "directory": str(output_dir),
                "last_sync_at": state.get("last_sync_at"),
                "crawl_in_progress": isinstance(state.get("crawl"), dict),
                "tracked": len(entries),
                "present": present,
                "missing_local_preserved": missing,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_list(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.profile)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    if args.limit < 1:
        raise PullError("--limit must be at least 1.")
    notes = collect_local_notes(
        output_dir,
        query=args.query,
        include_missing=args.include_missing,
        sort_by=args.sort,
    )[: args.limit]
    print(
        json.dumps(
            {
                "profile": config["profile"],
                "directory": str(output_dir),
                "query": args.query,
                "sort": args.sort,
                "count": len(notes),
                "items": notes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
        "authentication_required": False,
    }
    healthy = True
    try:
        config = load_config(config_path, args.profile)
        output_dir = resolve_output_dir(config_path, config, args.directory)
        report.update(
            {
                "profile": config["profile"],
                "directory": str(output_dir),
                "sync_state_exists": (output_dir / ".sync" / "state.json").is_file(),
            }
        )
    except PullError as exc:
        report["config_error"] = str(exc)
        healthy = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="Read-only incremental backup of a Substack profile's public Notes.",
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG, help=f"config path (default: {DEFAULT_CONFIG})"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add_local_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--profile", help="@handle or Substack profile URL")
        command.add_argument(
            "-d", "--directory", help="override the configured Notes directory"
        )

    def add_pull_arguments(command: argparse.ArgumentParser) -> None:
        add_local_arguments(command)
        command.add_argument(
            "--refresh",
            action="store_true",
            help="scan the complete feed and reconcile older edits/removals",
        )
        command.add_argument(
            "--overlap",
            type=int,
            default=24,
            help="unchanged authored Notes required before an incremental pull stops",
        )
        command.add_argument("--request-delay", type=float, default=1.25)
        command.add_argument("--timeout", type=float, default=30.0)
        command.add_argument("--attempts", type=int, default=8)
        command.set_defaults(handler=command_pull)

    pull = commands.add_parser("pull", help="pull new and changed public Notes")
    add_pull_arguments(pull)
    sync = commands.add_parser("sync", help="alias for pull")
    add_pull_arguments(sync)

    configure = commands.add_parser("configure", help="save a profile and directory")
    configure.add_argument("--profile", help="@handle or Substack profile URL")
    configure.add_argument(
        "-d", "--directory", help=f"Notes directory (default: {DEFAULT_OUTPUT})"
    )
    configure.set_defaults(handler=command_configure)

    status = commands.add_parser("status", help="show local Notes sync state")
    add_local_arguments(status)
    status.set_defaults(handler=command_status)

    listing = commands.add_parser("list", help="search or rank locally pulled Notes")
    add_local_arguments(listing)
    listing.add_argument("--query", help="case-insensitive text or Note ID search")
    listing.add_argument(
        "--sort",
        choices=("recent", "reactions", "restacks", "replies"),
        default="recent",
    )
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--include-missing", action="store_true")
    listing.set_defaults(handler=command_list)

    doctor = commands.add_parser("doctor", help="check local configuration")
    add_local_arguments(doctor)
    doctor.set_defaults(handler=command_doctor)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    raw = list(argv) if argv is not None else sys.argv[1:]
    if not raw:
        raw = ["pull"]
    args = parser.parse_args(raw)
    try:
        return int(args.handler(args))
    except PullError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
