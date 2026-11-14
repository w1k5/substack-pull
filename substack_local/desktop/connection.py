"""Verify a desktop sign-in and configure the shared local data engine.

The session arrives only on standard input. It is never passed as a process
argument, written to a config file, or included in a response.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import ssl
from urllib.error import HTTPError, URLError

from ..pullers.posts import ApiClient, KeychainStore, PullError
from ..pullers.posts.api import host_for, normalize_publication, verify_editor_access
from ..pullers.posts.common import DEFAULT_OUTPUT
from ..pullers.posts.storage import read_json, save_config
from ..paths import data_root
from .ai_connections import TEST_PROMPT, setup_client
from .updates import check_for_update


def publication_url(value: str) -> str:
    publication = normalize_publication(value)
    host = host_for(publication)
    if host == "substack.com" or not host.endswith(".substack.com"):
        raise PullError("Enter your publication address, such as name.substack.com.")
    return publication


def require_session(token: str) -> None:
    if not token or "\n" in token or "\r" in token:
        raise PullError("Substack did not provide a usable sign-in session.")


def discover(token: str, preferred: str | None = None) -> dict:
    require_session(token)
    try:
        profile = ApiClient("https://substack.com", token).get_json("/api/v1/user/profile/self")
    except PullError as exc:
        raise PullError("Clearview could not find your publications automatically.") from exc
    memberships = profile.get("publicationUsers") if isinstance(profile, dict) else None
    if not isinstance(memberships, list):
        raise PullError("Substack did not return a publication list.")
    choices = {}
    for membership in memberships:
        if not isinstance(membership, dict) or membership.get("is_byline_only"):
            continue
        if membership.get("role") not in ("admin", "owner", "editor"):
            continue
        publication = membership.get("publication")
        if not isinstance(publication, dict):
            continue
        subdomain = publication.get("subdomain")
        if not isinstance(subdomain, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", subdomain):
            continue
        address = f"{subdomain}.substack.com"
        name = publication.get("name")
        choices[address] = {"address": address, "name": name if isinstance(name, str) and name.strip() else address}
    selected = host_for(publication_url(preferred)) if preferred else None
    if selected not in choices:
        selected = next(iter(choices)) if len(choices) == 1 else None
    return {"publications": list(choices.values()), "selected": selected}


def verify(publication: str, token: str) -> dict[str, str]:
    publication = publication_url(publication)
    require_session(token)
    try:
        verify_editor_access(ApiClient(publication, token))
    except PullError as exc:
        cause = exc.__cause__
        if isinstance(cause, URLError) and isinstance(cause.reason, ssl.SSLCertVerificationError):
            raise PullError("Clearview could not verify Substack’s HTTPS certificate.") from exc
        if isinstance(cause, HTTPError):
            if cause.code in {401, 403}:
                raise PullError("Substack denied access to the publication. Sign in with an editor account for this publication.") from exc
            if cause.code == 429:
                raise PullError("Substack is limiting requests. Try connecting again later.") from exc
            raise PullError(f"Substack’s publication access check failed (HTTP {cause.code}).") from exc
        if isinstance(cause, URLError):
            raise PullError("Clearview could not reach Substack. Check your internet connection and try again.") from exc
        raise PullError("Substack returned an unexpected response while Clearview checked publication access.") from exc
    return {"publication": publication, "account": host_for(publication)}


def configure(config_path: Path, publication: str) -> dict[str, str]:
    publication = publication_url(publication)
    existing = read_json(config_path, {})
    if not isinstance(existing, dict):
        raise PullError("The existing publication settings are invalid.")
    directory = existing.get("directory") or existing.get("output") or DEFAULT_OUTPUT
    save_config(config_path, {"publication": publication, "directory": directory})
    return {"publication": publication, "account": host_for(publication)}


def current_publication(config_path: Path) -> str | None:
    existing = read_json(config_path, {})
    if not isinstance(existing, dict):
        return None
    value = existing.get("publication")
    if not isinstance(value, str):
        return None
    try:
        return publication_url(value)
    except PullError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("current", "discover", "discover-saved", "switch", "verify", "configure", "connect",
                                           "setup-codex", "setup-claude", "test-prompt",
                                           "check-update", "check-update-automatic"))
    parser.add_argument("--publication")
    parser.add_argument("--installed-version")
    parser.add_argument("--config", type=Path, default=data_root() / ".substack-pull.json")
    args = parser.parse_args()
    try:
        if args.action in {"check-update", "check-update-automatic"}:
            result = check_for_update(args.installed_version or "", data_root(),
                                      automatic=args.action.endswith("-automatic"))
        elif args.action == "test-prompt":
            result = {"prompt": TEST_PROMPT}
        elif args.action in {"setup-codex", "setup-claude"}:
            result = setup_client(args.action.removeprefix("setup-"), data_root())
        elif args.action == "current":
            publication = current_publication(args.config)
            result = {
                "publication": publication,
                "connected": bool(publication and KeychainStore().exists(host_for(publication))),
            }
        elif args.action == "discover":
            result = discover(sys.stdin.read().rstrip("\r\n"), current_publication(args.config))
        elif args.action in {"discover-saved", "switch"}:
            current = current_publication(args.config)
            if not current:
                raise PullError("Sign in to Substack before changing publications.")
            store = KeychainStore()
            token = store.get(host_for(current))
            if args.action == "discover-saved":
                result = discover(token, current)
            else:
                if not args.publication:
                    raise PullError("Choose a publication.")
                result = verify(args.publication, token)
                if result["account"] != host_for(current):
                    store.save(result["account"], token)
                configure(args.config, result["publication"])
        elif args.action in {"verify", "connect"}:
            if not args.publication:
                raise PullError("Enter your publication address.")
            token = sys.stdin.read().rstrip("\r\n")
            result = verify(args.publication, token)
            if args.action == "connect":
                KeychainStore().save(result["account"], token)
                configure(args.config, result["publication"])
        else:
            if not args.publication:
                raise PullError("Enter your publication address.")
            result = configure(args.config, args.publication)
        print(json.dumps(result))
        return 0
    except (PullError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
