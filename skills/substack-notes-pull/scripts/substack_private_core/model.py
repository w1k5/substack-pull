"""Private Note identity, time, and readable text models."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class PrivateNotesError(RuntimeError):
    """An expected, user-facing Notes error."""


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
    document = note_body_document(item)
    rendered = render_prosemirror(document).strip() if document else ""
    return rendered or str(item.get("body") or "").strip()


def note_body_document(item: dict[str, Any]) -> dict[str, Any] | None:
    document = item.get("body_json") or item.get("bodyJson")
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError:
            return None
    return document if isinstance(document, dict) else None


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
