"""Contract checks for the MCP adapters around the two pullers."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from substack_local.mcp import pulls as workflows


class WorkflowTests(unittest.TestCase):
    @patch("substack_local.mcp.pulls.subprocess.run")
    def test_public_post_pull_uses_anonymous_mode_and_ignored_directory(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"mode":"public"}'
        run.return_value.stderr = ""
        result = workflows.pull_public_posts("https://example.substack.com")
        command = run.call_args.args[0]
        self.assertEqual(result["mode"], "public")
        self.assertIn("--public", command)
        self.assertIn(str(workflows.ROOT / "substack/public-posts/example.substack.com"), command)
        self.assertNotIn("auth", command)

    @patch("substack_local.mcp.pulls.subprocess.run")
    def test_private_note_previews_are_opt_in(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"count":1,"items":[{"id":"c-1","preview":"private body"}]}'
        run.return_value.stderr = ""
        self.assertNotIn("preview", workflows.find_note_copies()["items"][0])
        self.assertEqual(workflows.find_note_copies(include_preview=True)["items"][0]["preview"], "private body")

    @patch("substack_local.mcp.pulls.subprocess.run")
    def test_public_note_history_is_anonymous_and_profile_scoped(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"complete":true}'
        run.return_value.stderr = ""
        workflows.pull_published_notes("@PrettyHostile")
        command = run.call_args.args[0]
        self.assertLess(command.index("public"), command.index("--config"))
        self.assertIn(str(workflows.ROOT / "substack/published-notes/prettyhostile"), command)

    def test_markdown_reader_stays_inside_backup(self):
        with tempfile.TemporaryDirectory() as root:
            inside = Path(root) / "inside.md"
            outside = Path(root).parent / "outside.md"
            inside.write_text("local copy", encoding="utf-8")
            self.assertEqual(workflows._read_markdown(str(inside), root, 5)["markdown"], "local")
            with self.assertRaises(ValueError):
                workflows._read_markdown(str(outside), root, 5)


if __name__ == "__main__":
    unittest.main()
