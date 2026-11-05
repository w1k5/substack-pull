"""Contract checks for the process-free MCP backup adapters."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from substack_local.mcp import pulls as workflows


class WorkflowTests(unittest.TestCase):
    @patch("substack_local.mcp.pulls.post_puller")
    def test_public_post_pull_uses_anonymous_mode_and_ignored_directory(self, module):
        module = module.return_value
        module.load_config.return_value = {"publication": "https://example.substack.com"}
        module.SyncEngine.return_value.sync.return_value = {"mode": "public", "errors": []}
        result = workflows.pull_public_posts("https://example.substack.com")
        self.assertEqual(result["mode"], "public")
        module.ApiClient.assert_called_once_with("https://example.substack.com", None)
        self.assertEqual(module.SyncEngine.call_args.kwargs["public_only"], True)
        self.assertEqual(module.resolve_output_dir.call_args.args[2], str(
            workflows.ROOT / "substack/public-posts/example.substack.com"
        ))

    @patch("substack_local.mcp.pulls.private_notes")
    def test_private_note_previews_are_opt_in(self, module):
        module = module.return_value
        module.load_private_notes.return_value = [{"id": 1}]
        module.note_category.return_value = "note-drafts"
        module.note_body.return_value = "private body"
        module.item_id.return_value = "1"
        self.assertNotIn("preview", workflows.find_note_copies()["items"][0])
        self.assertEqual(workflows.find_note_copies(include_preview=True)["items"][0]["preview"], "private body")

    @patch("substack_local.mcp.pulls.public_notes")
    def test_public_note_history_is_anonymous_and_profile_scoped(self, module):
        module = module.return_value
        module.load_config.return_value = {"profile": "@prettyhostile"}
        module.SyncEngine.return_value.sync.return_value = {"complete": True}
        workflows.pull_published_notes("@PrettyHostile")
        module.ApiClient.assert_called_once_with()
        self.assertEqual(module.resolve_output_dir.call_args.args[2], str(
            workflows.ROOT / "substack/published-notes/prettyhostile"
        ))

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
