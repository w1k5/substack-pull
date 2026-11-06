"""Private Note settings and Keychain session lookup."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import urllib.parse

from .constants import (DEFAULT_OUTPUT, KEYCHAIN_SERVICE, LEGACY_KEYCHAIN_ACCOUNT,
                        LEGACY_KEYCHAIN_SERVICE, SUBSTACK_PULL_CONFIG)
from .files import atomic_write_json, load_private_notes, read_json
from .model import PrivateNotesError, load_zone, local_zone_name, note_category


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

def local_status(config_path: Path, config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Describe private Note files and session availability without a network request."""
    notes = load_private_notes(output_dir)
    counts = Counter(note_category(note) for note in notes)
    state = read_json(output_dir / ".private-sync" / "state.json", {})
    return {
        "directory": str(output_dir),
        "last_sync_at": state.get("last_sync_at") if isinstance(state, dict) else None,
        "drafts": counts["note-drafts"],
        "scheduled": counts["note-scheduled"],
        "runway_exists": (output_dir / "note-runway.html").is_file(),
        "keychain_session_present": reusable_session_present(config_path, config),
    }
