"""Command-line interface for the shared public Note puller."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable

from .api import ApiClient, normalize_handle, resolve_profile
from .common import APP_NAME, DEFAULT_CONFIG, DEFAULT_OUTPUT, PullError
from .files import (collect_local_notes, config_path_from, load_config, local_status,
                    read_json, resolve_output_dir, save_config)
from .sync import SyncEngine


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
    for key in ("notes_directory", "timezone"):
        if existing.get(key):
            config[key] = existing[key]
    if not config.get("notes_directory") and existing.get("private_directory"):
        config["notes_directory"] = existing["private_directory"]
    save_config(path, config)
    print(f"Profile: {config['profile']}")
    print(f"Directory: {config['directory']}")
    print(f"Configuration saved to {path} (no authentication is used).")
    return 0

def command_status(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.profile)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    print(json.dumps(local_status(output_dir), ensure_ascii=False, indent=2))
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

def public_main(argv: Iterable[str] | None = None) -> int:
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

def main(argv: Iterable[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    if raw and raw[0] == "public":
        return public_main(raw[1:])
    if not raw:
        raw = ["pull"]
    from ..private_notes import main as notes_main
    return int(notes_main(raw))
