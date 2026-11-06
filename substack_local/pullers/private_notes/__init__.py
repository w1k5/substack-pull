"""Shared private Note puller with stable CLI, dashboard, and MCP imports."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import urllib.parse

from .constants import (APP_NAME, DEFAULT_CONFIG, DEFAULT_OUTPUT, KEYCHAIN_SERVICE,
                        LEGACY_KEYCHAIN_ACCOUNT, LEGACY_KEYCHAIN_SERVICE,
                        MAX_NOTE_LENGTH, NOTE_CATEGORIES, STATE_VERSION,
                        SUBSTACK_PULL_CONFIG)
from .api import BASE_URL, PrivateApiClient, paginate_private_notes, query_path
from .model import (PrivateNotesError, _attachment_markdown, _marked_text, item_id,
                    load_zone, local_timestamp, local_zone_name, note_body,
                    note_body_document, note_category, note_markdown, notes_overview,
                    parse_iso, render_prosemirror)
from .files import (atomic_write_json, atomic_write_text, canonical_json,
                    collect_local_notes, fingerprint, load_private_notes, read_json,
                    unwrap_note, utc_now)
from .planning import (api_timestamp, parse_schedule_at, parse_start,
                       render_runway_html, runway_payload, write_runway)
from .config import (KeychainStore, load_config, local_status, output_dir_from,
                     publication_account, reusable_session, reusable_session_present,
                     save_private_config, session_candidates, shared_session_account,
                     zone_name_from)
from .payloads import (created_note_from_response, draft_body_json, draft_payload,
                       matching_drafts, normalize_draft_text, schedule_payload)
from .sync import PrivateNotesSync


def create_note_draft(
    text: str, *, apply: bool = False, config_path: Path = Path(DEFAULT_CONFIG),
    directory: str | None = None, timezone_name: str | None = None,
    timeout: float = 30.0, days: int = 90, minimum_spacing: int = 3,
) -> dict[str, Any]:
    """Preview or create a text draft, then verify the remote and local result."""
    text = normalize_draft_text(text)
    payload = draft_payload(text)
    preview: dict[str, Any] = {
        "body": text,
        "characters": len(text),
        "paragraphs": len(payload["bodyJson"]["content"]),
        "reply_minimum_role": payload["replyMinimumRole"],
        "trigger_at": None,
        "applied": False,
    }
    if not apply:
        preview["next_step"] = "Approve this exact body before creating the draft."
        return preview

    config_path = Path(config_path).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, directory)
    zone_name = zone_name_from(config, timezone_name)
    token = reusable_session(config_path, config)
    api = PrivateApiClient(token, timeout=timeout, request_delay=0.25, attempts=3)
    before = paginate_private_notes(api)
    duplicates = matching_drafts(before, payload["bodyJson"])
    if duplicates:
        preview.update(
            {
                "duplicate": True,
                "existing_notes": [
                    {
                        "id": item_id(note),
                        "status": "scheduled" if note.get("trigger_at") else "draft",
                        "trigger_at": note.get("trigger_at"),
                    }
                    for note in duplicates
                ],
                "next_step": "No Note was created because this exact body already exists.",
            }
        )
        return preview

    existing_ids = {item_id(note) for note in before}
    response = api.post_json("/api/v1/comment/draft", payload)
    response_note = created_note_from_response(response)
    response_id = item_id(response_note) if response_note else None
    try:
        summary = PrivateNotesSync(api, output_dir, zone_name=zone_name).sync(
            days=days,
            minimum_spacing=minimum_spacing,
        )
    except PrivateNotesError as exc:
        raise PrivateNotesError(
            "Substack returned a draft-creation response, but the local refresh failed. "
            "Pull and check the exact body before retrying."
        ) from exc

    refreshed_notes = load_private_notes(output_dir)
    if response_id:
        refreshed = next(
            (note for note in refreshed_notes if item_id(note) == response_id), None
        )
    else:
        candidates = [
            note
            for note in matching_drafts(refreshed_notes, payload["bodyJson"])
            if item_id(note) not in existing_ids
        ]
        refreshed = candidates[0] if len(candidates) == 1 else None
    if refreshed is None:
        raise PrivateNotesError(
            "Substack returned a draft-creation response, but the new draft could not "
            "be identified after refresh. Pull and check the exact body before retrying."
        )
    if refreshed.get("trigger_at"):
        raise PrivateNotesError(
            "The created Note unexpectedly has a scheduled time. Pull and inspect it "
            "before making another change."
        )
    if not matching_drafts([refreshed], payload["bodyJson"]):
        raise PrivateNotesError(
            "The refreshed draft body did not match the approved text. Pull and inspect "
            "it before making another change."
        )

    created_id = item_id(refreshed)
    preview.update(
        {
            "applied": True,
            "note_id": created_id,
            "verified_status": "draft",
            "local_json": str(
                (output_dir / "note-drafts" / f"{created_id}.json").resolve()
            ),
            "local_markdown": str(
                (output_dir / "note-drafts" / f"{created_id}.md").resolve()
            ),
            "runway_file": summary["runway_file"],
        }
    )
    return preview


def create_note_drafts(
    texts: list[str], *, apply: bool = False,
    config_path: Path = Path(DEFAULT_CONFIG), directory: str | None = None,
    timezone_name: str | None = None, timeout: float = 30.0,
    days: int = 90, minimum_spacing: int = 3,
) -> dict[str, Any]:
    """Create a bounded batch with one preflight read and one final verification sync."""
    if not 1 <= len(texts) <= 20:
        raise PrivateNotesError("Provide 1 to 20 Note bodies per batch.")
    previews = [create_note_draft(text) for text in texts]
    bodies = [item["body"] for item in previews]
    if len(set(bodies)) != len(bodies):
        raise PrivateNotesError("A batch cannot contain identical Note bodies.")
    for item in previews:
        item.pop("next_step", None)
    result: dict[str, Any] = {"items": previews, "applied": False, "incomplete": False}
    if not apply:
        result["next_step"] = "Approve these exact bodies before creating the drafts."
        return result

    config_path = Path(config_path).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, directory)
    zone_name = zone_name_from(config, timezone_name)
    token = reusable_session(config_path, config)
    api = PrivateApiClient(token, timeout=timeout, request_delay=1.0, attempts=3)
    before = paginate_private_notes(api)
    existing_ids = {item_id(note) for note in before}
    pending: list[tuple[int, str | None, dict[str, Any]]] = []
    failed_index: int | None = None

    for index, item in enumerate(previews):
        body_json = draft_payload(item["body"])["bodyJson"]
        duplicates = matching_drafts(before, body_json)
        if duplicates:
            item["duplicate"] = True
            item["existing_notes"] = [
                {"id": item_id(note), "status": "scheduled" if note.get("trigger_at") else "draft"}
                for note in duplicates
            ]
            continue
        try:
            response = api.post_json("/api/v1/comment/draft", draft_payload(item["body"]))
        except PrivateNotesError as exc:
            item["error"] = str(exc)
            item["uncertain"] = True
            result["incomplete"] = True
            failed_index = index
            break
        response_note = created_note_from_response(response)
        response_id = item_id(response_note) if response_note else None
        if response_id:
            item["response_id"] = response_id
        pending.append((index, response_id, body_json))

    if failed_index is not None:
        for item in previews[failed_index + 1:]:
            item["not_attempted"] = True

    if pending or failed_index is not None:
        try:
            summary = PrivateNotesSync(api, output_dir, zone_name=zone_name).sync(
                days=days, minimum_spacing=minimum_spacing,
            )
        except PrivateNotesError as exc:
            result["incomplete"] = True
            result["error"] = (
                "The final Notes refresh failed. Pull and inspect the batch before retrying: "
                f"{exc}"
            )
            result["posted_unverified"] = len(pending)
            return result
        refreshed_notes = load_private_notes(output_dir)
        claimed_ids: set[str] = set()
        to_verify = pending + (
            [(failed_index, None, draft_payload(previews[failed_index]["body"])["bodyJson"])]
            if failed_index is not None else []
        )
        for index, response_id, body_json in to_verify:
            item = previews[index]
            if response_id:
                note = next((note for note in refreshed_notes if item_id(note) == response_id), None)
            else:
                candidates = [
                    note for note in matching_drafts(refreshed_notes, body_json)
                    if item_id(note) not in existing_ids | claimed_ids
                ]
                note = candidates[0] if len(candidates) == 1 else None
            if (note is None or item_id(note) in existing_ids or note.get("trigger_at")
                    or not matching_drafts([note], body_json)):
                item["verification_error"] = "The draft could not be verified after refresh."
                result["incomplete"] = True
                continue
            note_id = item_id(note)
            claimed_ids.add(note_id)
            item.update({
                "applied": True,
                "note_id": note_id,
                "verified_status": "draft",
                "local_json": str((output_dir / "note-drafts" / f"{note_id}.json").resolve()),
                "local_markdown": str((output_dir / "note-drafts" / f"{note_id}.md").resolve()),
            })
            item.pop("uncertain", None)
            item.pop("error", None)
        result["runway_file"] = summary["runway_file"]

    result["created"] = sum(item["applied"] for item in previews)
    result["duplicates"] = sum(bool(item.get("duplicate")) for item in previews)
    result["applied"] = bool(result["created"]) and not result["incomplete"]
    return result


def schedule_note(
    note_id: str, at: str, *, apply: bool = False,
    config_path: Path = Path(DEFAULT_CONFIG), directory: str | None = None,
    timezone_name: str | None = None, timeout: float = 30.0,
    days: int = 90, minimum_spacing: int = 3,
) -> dict[str, Any]:
    """Preview or change a Note's schedule, preserving its body and attachments."""
    config_path = Path(config_path).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, directory)
    zone_name = zone_name_from(config, timezone_name)
    scheduled_at = parse_schedule_at(at, zone_name)
    token = reusable_session(config_path, config)
    api = PrivateApiClient(token, timeout=timeout, request_delay=0.25, attempts=3)
    notes = paginate_private_notes(api)
    note = next((value for value in notes if item_id(value) == str(note_id)), None)
    if note is None:
        raise PrivateNotesError(
            f"Note {note_id} was not found among the account's drafts and "
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
    if not apply:
        preview["next_step"] = "Approve this Note and time before changing its schedule."
        return preview

    path = f"/api/v1/feed/comment/{urllib.parse.quote(item_id(note), safe='')}"
    api.patch_json(path, schedule_payload(note, scheduled_at))
    summary = PrivateNotesSync(api, output_dir, zone_name=zone_name).sync(
        days=days,
        minimum_spacing=minimum_spacing,
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
    return preview


from .cli import (add_local_args, add_runway_args, build_parser, command_auth,
                  command_configure, command_create_draft, command_list,
                  command_pull, command_schedule, command_status,
                  command_visualize, main, read_draft_text)
