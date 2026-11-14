"""Connect desktop clients to the installed Clearview engine."""

import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED

TEST_PROMPT = "Use Clearview to show which of my recent Notes got the most replies per 1,000 impressions. Include the reply and impression counts."

CLAUDE_LAUNCHER = """
const { spawn } = require('node:child_process');
const child = spawn(process.argv[2], ['mcp'], { stdio: 'inherit', windowsHide: true });
child.on('error', () => {
  process.stderr.write('Could not start Clearview. Reopen Clearview and reinstall its Claude extension.\\n');
  process.exitCode = 1;
});
child.on('exit', (code) => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}
"""


def register_codex(config: Path, engine: Path) -> None:
    old = config.read_text(encoding="utf-8") if config.exists() else ""
    name = "clearview"
    servers = tomllib.loads(old).get("mcp_servers", {})
    entry = {"command": str(engine), "args": ["mcp"], "tool_timeout_sec": 300}
    if name in servers:
        if all(servers[name].get(key) == value for key, value in entry.items()):
            return
        raise ValueError("Codex already has a Clearview entry with different settings. Update it in Codex’s MCP settings.")
    updated = old.rstrip() + f"\n\n[mcp_servers.{name}]\n" + "".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in entry.items()
    )
    tomllib.loads(updated)
    config.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=config.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(updated)
        current = config.read_text(encoding="utf-8") if config.exists() else ""
        if current != old:
            raise ValueError("Codex settings changed during setup. Try again.")
        os.replace(temporary, config)
    finally:
        Path(temporary).unlink(missing_ok=True)


def make_claude_extension(destination: Path, engine: Path) -> None:
    manifest = {
        "manifest_version": "0.3",
        "name": "clearview",
        "display_name": "Clearview",
        "version": "1.0.0",
        "description": "Connect Claude Desktop to Clearview’s local Substack analytics and Note planner.",
        "author": {"name": "Clearview"},
        "compatibility": {"platforms": [sys.platform]},
        "server": {
            "type": "node",
            "entry_point": "launch.cjs",
            "mcp_config": {"command": "node", "args": ["${__dirname}/launch.cjs", str(engine)]},
        },
    }
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("launch.cjs", CLAUDE_LAUNCHER)


def setup_client(client: str, directory: Path) -> dict:
    if not getattr(sys, "frozen", False):
        raise ValueError("Install the packaged Clearview app to connect a desktop assistant.")
    engine = Path(sys.executable).absolute()
    if "AppTranslocation" in engine.parts or (sys.platform == "darwin" and engine.parts[1] == "Volumes"):
        raise ValueError("Move Clearview to Applications and reopen it before connecting.")
    if client == "codex":
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        register_codex(codex_home / "config.toml", engine)
        return {"message": "Clearview is registered. Restart Codex to load its tools."}
    destination = directory / "Clearview.mcpb"
    directory.mkdir(parents=True, exist_ok=True)
    make_claude_extension(destination, engine)
    return {"path": str(destination)}
