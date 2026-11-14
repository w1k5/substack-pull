import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tomllib
from unittest import TestCase
from zipfile import ZipFile

from substack_local.desktop.ai_connections import make_claude_extension, register_codex


class DesktopAIConnectionTests(TestCase):
    def test_codex_preserves_other_settings_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text('[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8")
            engine = Path(directory) / 'Clearview with spaces' / 'engine'
            register_codex(config, engine)
            first = config.read_text(encoding="utf-8")
            servers = tomllib.loads(first)["mcp_servers"]
            self.assertEqual(servers["other"], {"command": "other"})
            self.assertEqual(servers["clearview"]["command"], str(engine))
            self.assertEqual(servers["clearview"]["args"], ["mcp"])
            register_codex(config, engine)
            self.assertEqual(config.read_text(encoding="utf-8"), first)
            with self.assertRaises(ValueError):
                register_codex(config, engine.with_name("another-engine"))
            self.assertEqual(config.read_text(encoding="utf-8"), first)

    def test_claude_extension_contains_launcher_and_uses_installed_engine(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            engine = root / "Clearview with spaces" / "engine"
            bundle = root / "Clearview.mcpb"
            make_claude_extension(bundle, engine)
            with ZipFile(bundle) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                launch = manifest["server"]["mcp_config"]
                self.assertEqual(launch["args"], ["${__dirname}/launch.cjs", str(engine)])
                self.assertEqual(set(archive.namelist()), {"manifest.json", "launch.cjs"})
                self.assertIn(b"['mcp']", archive.read("launch.cjs"))
