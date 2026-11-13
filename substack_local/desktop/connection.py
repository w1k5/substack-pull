"""Verify a desktop sign-in and configure the shared local data engine.

The session arrives only on standard input. It is never passed as a process
argument, written to a config file, or included in a response.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import ssl
from urllib.error import HTTPError, URLError

from ..pullers.posts import ApiClient, KeychainStore, PullError
from ..pullers.posts.api import host_for, normalize_publication, verify_editor_access
from ..pullers.posts.common import DEFAULT_OUTPUT
from ..pullers.posts.storage import read_json, save_config
from ..paths import data_root


def publication_url(value: str) -> str:
    publication = normalize_publication(value)
    host = host_for(publication)
    if host == "substack.com" or not host.endswith(".substack.com"):
        raise PullError("Enter your publication address, such as name.substack.com.")
    return publication


def verify(publication: str, token: str) -> dict[str, str]:
    publication = publication_url(publication)
    if not token or "\n" in token or "\r" in token:
        raise PullError("Substack did not provide a usable sign-in session.")
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
    parser.add_argument("action", choices=("current", "verify", "configure", "connect"))
    parser.add_argument("--publication")
    parser.add_argument("--config", type=Path, default=data_root() / ".substack-pull.json")
    args = parser.parse_args()
    try:
        if args.action == "current":
            publication = current_publication(args.config)
            result = {
                "publication": publication,
                "connected": bool(publication and KeychainStore().exists(host_for(publication))),
            }
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
