"""Command-line interface for the shared private Note puller."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

from .api import PrivateApiClient
from .config import (KeychainStore, load_config, local_status, output_dir_from,
                     reusable_session, save_private_config, shared_session_account,
                     zone_name_from)
from .constants import (APP_NAME, DEFAULT_CONFIG, DEFAULT_OUTPUT, KEYCHAIN_SERVICE)
from .files import (atomic_write_text, collect_local_notes, load_private_notes,
                    read_json, utc_now)
from .model import (PrivateNotesError, load_zone, note_category, notes_overview)
from .payloads import normalize_draft_text
from .planning import parse_start, write_runway
from .sync import PrivateNotesSync
from . import create_note_draft, schedule_note


def read_draft_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return normalize_draft_text(args.text)
    path = Path(args.file).expanduser().resolve()
    try:
        return normalize_draft_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PrivateNotesError(f"Could not read Note text from {path}: {exc}") from exc

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

def command_create_draft(args: argparse.Namespace) -> int:
    result = create_note_draft(
        read_draft_text(args), apply=args.apply, config_path=Path(args.config),
        directory=args.directory, timezone_name=args.timezone, timeout=args.timeout,
        days=args.days, minimum_spacing=args.minimum_spacing,
    )
    if not args.apply:
        result["next_step"] = "After the exact body is approved, run the same command with --apply."
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def command_schedule(args: argparse.Namespace) -> int:
    result = schedule_note(
        args.note_id, args.at, apply=args.apply, config_path=Path(args.config),
        directory=args.directory, timezone_name=args.timezone, timeout=args.timeout,
        days=args.days, minimum_spacing=args.minimum_spacing,
    )
    if not args.apply:
        result["next_step"] = "Run the same command with --apply to send the schedule change."
    print(json.dumps(result, ensure_ascii=False, indent=2))
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
    if args.limit < 1:
        raise PrivateNotesError("--limit must be at least 1.")
    items = collect_local_notes(output_dir, zone_name, status=args.status, query=args.query or "")
    print(json.dumps({"count": len(items), "items": items[: args.limit]}, ensure_ascii=False, indent=2))
    return 0

def command_status(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = output_dir_from(config_path, config, args.directory)
    print(json.dumps(local_status(config_path, config, output_dir), ensure_ascii=False, indent=2))
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
        description=(
            "Pull, create, and schedule Note drafts and build a 90-day runway."
        ),
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

    create_draft = commands.add_parser(
        "create-draft", help="preview or create one unpublished, unscheduled text Note"
    )
    draft_source = create_draft.add_mutually_exclusive_group(required=True)
    draft_source.add_argument("--text", help="exact plain-text Note body")
    draft_source.add_argument("--file", help="UTF-8 file containing the exact Note body")
    create_draft.add_argument(
        "--apply",
        action="store_true",
        help="create the draft on Substack; omission produces a preview only",
    )
    create_draft.add_argument("--timeout", type=float, default=30.0)
    add_local_args(create_draft)
    add_runway_args(create_draft)
    create_draft.set_defaults(handler=command_create_draft)

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
