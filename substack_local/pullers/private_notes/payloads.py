"""Note draft and schedule payload construction."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .constants import MAX_NOTE_LENGTH
from .model import (PrivateNotesError, item_id, note_body, note_body_document,
                    render_prosemirror)
from .planning import api_timestamp


def normalize_draft_text(value: str) -> str:
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        raise PrivateNotesError("A Note draft cannot be empty.")
    if len(text) > MAX_NOTE_LENGTH:
        raise PrivateNotesError(
            f"A Note draft cannot exceed {MAX_NOTE_LENGTH:,} characters."
        )
    lines = [line for line in text.split("\n") if line]
    if not lines or not any(line.strip() for line in lines):
        raise PrivateNotesError("A Note draft must contain visible text.")
    return "\n".join(lines)

def draft_body_json(text: str) -> dict[str, Any]:
    normalized = normalize_draft_text(text)
    return {
        "type": "doc",
        "attrs": {"schemaVersion": "v1", "title": None},
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}],
            }
            for line in normalized.split("\n")
        ],
    }

def draft_payload(text: str) -> dict[str, Any]:
    return {
        "bodyJson": draft_body_json(text),
        "replyMinimumRole": "everyone",
        "trigger_at": None,
    }

def matching_drafts(
    notes: Iterable[dict[str, Any]], body_json: dict[str, Any]
) -> list[dict[str, Any]]:
    expected_text = normalize_draft_text(render_prosemirror(body_json).strip())
    matches: list[dict[str, Any]] = []
    for note in notes:
        if note_body_document(note) == body_json:
            matches.append(note)
            continue
        try:
            if normalize_draft_text(note_body(note)) == expected_text:
                matches.append(note)
        except PrivateNotesError:
            continue
    return matches

def created_note_from_response(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("id") is not None:
        return payload
    for key in ("draft", "comment"):
        value = payload.get(key)
        if isinstance(value, dict) and value.get("id") is not None:
            return value
    item = payload.get("item")
    if isinstance(item, dict):
        if item.get("id") is not None:
            return item
        comment = item.get("comment")
        if isinstance(comment, dict) and comment.get("id") is not None:
            return comment
    return None

def schedule_payload(note: dict[str, Any], trigger_at: datetime) -> dict[str, Any]:
    attachment_ids = note.get("attachment_ids") or note.get("attachmentIds")
    if not isinstance(attachment_ids, list):
        attachment_ids = [
            attachment.get("id")
            for attachment in note.get("attachments", [])
            if isinstance(attachment, dict) and attachment.get("id")
        ]
    body_json = note.get("body_json") or note.get("bodyJson")
    if not isinstance(body_json, dict):
        if str(note.get("body") or "").strip() or not attachment_ids:
            raise PrivateNotesError(
                f"Note {item_id(note)} has no editable body document; no change was made."
            )
        body_json = {"type": "doc", "content": [{"type": "paragraph"}]}
    payload: dict[str, Any] = {
        "bodyJson": body_json,
        "replyMinimumRole": (
            note.get("reply_minimum_role")
            or note.get("replyMinimumRole")
            or "everyone"
        ),
        "trigger_at": api_timestamp(trigger_at),
    }
    if attachment_ids:
        payload["attachmentIds"] = [str(value) for value in attachment_ids]
    if "ai_detection_disabled" in note or "aiDetectionDisabled" in note:
        payload["aiDetectionDisabled"] = bool(
            note.get("ai_detection_disabled", note.get("aiDetectionDisabled"))
        )
    return payload
