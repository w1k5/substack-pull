"""Command-line interface for the shared post puller."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from typing import Any, Iterable

from .api import ApiClient, KeychainStore, host_for, normalize_publication
from .common import DEFAULT_CONFIG, DEFAULT_OUTPUT, PullError
from .storage import (collect_local_posts, config_path_from, load_config, local_status,
                      resolve_output_dir, save_config)
from .sync import SyncEngine


def command_auth(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    existing = read_json(config_path, {})
    publication_value = args.publication or existing.get("publication")
    if not publication_value:
        publication_value = input("Publication URL: ").strip()
    publication = normalize_publication(str(publication_value))
    directory = (
        args.directory
        or existing.get("directory")
        or existing.get("output")
        or DEFAULT_OUTPUT
    )
    save_config(config_path, {"publication": publication, "directory": directory})

    account = host_for(publication)
    keychain = KeychainStore()
    keychain.store_interactive(account)

    token = keychain.get(account)
    api = ApiClient(publication, token, request_delay=args.request_delay)
    api.get_json("/api/v1/drafts?limit=1")
    print(f"Authentication verified for {publication}.")
    print(f"Configuration saved to {config_path} (no secret stored there).")
    return 0

def command_sync(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    publication = config["publication"]
    output_dir = resolve_output_dir(config_path, config, args.directory)

    if args.page_limit < 1:
        raise PullError("--page-limit must be at least 1.")
    if args.public:
        api = ApiClient(
            publication,
            request_delay=args.request_delay,
            timeout=args.timeout,
        )
    else:
        token = KeychainStore().get(host_for(publication))
        api = ApiClient(
            publication,
            token,
            request_delay=args.request_delay,
            timeout=args.timeout,
        )
    engine = SyncEngine(
        api,
        output_dir,
        page_limit=args.page_limit,
        public_only=args.public,
    )
    summary = engine.sync(refresh_published=args.refresh_published)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"]:
        return 1
    return 0

def command_status(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    result = local_status(output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def command_list(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    output_dir = resolve_output_dir(config_path, config, args.directory)
    if args.limit < 1:
        raise PullError("--limit must be at least 1.")
    category = None if args.category == "all" else args.category
    posts = collect_local_posts(
        output_dir,
        category=category,
        include_missing=args.include_missing,
        query=args.query or "",
    )
    posts = posts[: args.limit]
    result = {
        "publication": config["publication"],
        "directory": str(output_dir),
        "query": args.query,
        "count": len(posts),
        "items": posts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def command_configure(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    config = load_config(config_path, args.publication)
    if args.directory:
        config["directory"] = args.directory
    save_config(config_path, config)
    print(f"Publication: {config['publication']}")
    print(f"Directory: {config['directory']}")
    print(f"Configuration saved to {config_path} (no secret stored there).")
    return 0

def command_doctor(args: argparse.Namespace) -> int:
    config_path = config_path_from(args)
    report: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "security_command": shutil.which("security") is not None,
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
    }
    healthy = sys.platform == "darwin" and report["security_command"]
    if config_path.is_file():
        try:
            config = load_config(config_path, args.publication)
            account = host_for(config["publication"])
            report["publication"] = config["publication"]
            output_dir = resolve_output_dir(config_path, config)
            report["directory"] = str(output_dir)
            report["sync_state_exists"] = (output_dir / ".sync" / "state.json").is_file()
            report["keychain_session_present"] = KeychainStore().exists(account)
            if not report["keychain_session_present"]:
                healthy = False
        except PullError as exc:
            report["config_error"] = str(exc)
            healthy = False
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if healthy else 1

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="substack-pull",
        description="Read-only incremental backup of a Substack publication.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help=f"configuration path (default: {DEFAULT_CONFIG})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="store and verify a browser session")
    auth.add_argument("--publication", help="publication URL or hostname")
    auth.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help=f"content directory (default: {DEFAULT_OUTPUT})",
    )
    auth.add_argument("--request-delay", type=float, default=0.25)
    auth.set_defaults(handler=command_auth)

    def add_pull_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--publication", help="override configured publication")
        command.add_argument(
            "-d",
            "--directory",
            "--output",
            dest="directory",
            help="override configured content directory for this pull",
        )
        command.add_argument(
            "--public",
            action="store_true",
            help="pull only anonymously visible published posts; do not use a session",
        )
        command.add_argument("--refresh-published", action="store_true")
        command.add_argument("--page-limit", type=int, default=50)
        command.add_argument("--request-delay", type=float, default=0.25)
        command.add_argument("--timeout", type=float, default=30.0)
        command.set_defaults(handler=command_sync)

    pull = subparsers.add_parser(
        "pull", help="pull content and report exactly which posts changed"
    )
    add_pull_arguments(pull)

    sync = subparsers.add_parser("sync", help="alias for pull")
    add_pull_arguments(sync)

    status = subparsers.add_parser("status", help="show local sync state")
    status.add_argument("--publication", help="override configured publication")
    status.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help="override configured content directory",
    )
    status.set_defaults(handler=command_status)

    list_posts = subparsers.add_parser(
        "list", help="find recent posts in the local backup"
    )
    list_posts.add_argument("--publication", help="override configured publication")
    list_posts.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help="override configured content directory",
    )
    list_posts.add_argument("--query", help="case-insensitive title or ID search")
    list_posts.add_argument(
        "--category",
        choices=("all", "drafts", "scheduled", "published"),
        default="all",
    )
    list_posts.add_argument("--limit", type=int, default=20)
    list_posts.add_argument("--include-missing", action="store_true")
    list_posts.set_defaults(handler=command_list)

    configure = subparsers.add_parser(
        "configure", help="change publication or default content directory"
    )
    configure.add_argument("--publication", help="publication URL or hostname")
    configure.add_argument(
        "-d",
        "--directory",
        "--output",
        dest="directory",
        help="new default content directory",
    )
    configure.set_defaults(handler=command_configure)

    doctor = subparsers.add_parser("doctor", help="check local prerequisites")
    doctor.add_argument("--publication", help="override configured publication")
    doctor.set_defaults(handler=command_doctor)

    return parser

def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if not raw_args:
        raw_args = ["pull"]
    args = parser.parse_args(raw_args)
    try:
        return int(args.handler(args))
    except PullError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130
