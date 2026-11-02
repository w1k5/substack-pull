#!/usr/bin/env python3
"""Register the repository's Substack MCP server with the Codex desktop app."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home() / ".codex" / "config.toml"
NAME = "substack-analytics-local"
ENTRY = {
    "command": "/bin/sh",
    "args": [str(ROOT / "substack-analytics-mcp")],
    "startup_timeout_sec": 30.0,
    "tool_timeout_sec": 300.0,
    "default_tools_approval_mode": "writes",
}


def main() -> None:
    old = CONFIG.read_text() if CONFIG.exists() else ""
    parsed = tomllib.loads(old)
    existing = parsed.get("mcp_servers", {}).get(NAME)
    if existing == ENTRY:
        print("Substack analytics MCP is already registered.")
        return
    if existing is None:
        block = f"\n\n[mcp_servers.{NAME}]\n" + "".join(
            f"{key} = {json.dumps(value)}\n" for key, value in ENTRY.items()
        )
        updated = old + block
    else:
        previous = dict(ENTRY, tool_timeout_sec=120.0)
        if existing != previous:
            raise SystemExit(f"An existing {NAME} entry differs; no changes made.")
        header = f"[mcp_servers.{NAME}]"
        start = old.index(header)
        end = old.find("\n[", start + len(header))
        end = len(old) if end < 0 else end
        section = old[start:end]
        old_line = 'tool_timeout_sec = 120.0'
        if section.count(old_line) != 1:
            raise SystemExit("Could not safely update the existing timeout.")
        updated = old[:start] + section.replace(old_line, 'tool_timeout_sec = 300.0') + old[end:]
    assert tomllib.loads(updated)["mcp_servers"][NAME] == ENTRY
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = CONFIG.with_name(f"config.toml.before-substack-analytics-{stamp}")
        shutil.copy2(CONFIG, backup)
        backup.chmod(0o600)
    fd, name = tempfile.mkstemp(prefix=".config-substack-analytics-", dir=CONFIG.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(updated)
        os.replace(name, CONFIG)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print("Registered Substack MCP. Reconnect MCP servers in Codex to use its tools.")


if __name__ == "__main__":
    main()
