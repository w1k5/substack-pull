"""Contract checks for the process-free MCP backup adapters."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from substack_local.mcp import pulls as workflows
from substack_local.workflows.modules import private_notes


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
        module.collect_local_notes.side_effect = lambda *_args, **kwargs: [
            {"id": "1", "preview": "private body"} if kwargs["include_preview"] else {"id": "1"}
        ]
        self.assertNotIn("preview", workflows.find_note_copies()["items"][0])
        self.assertEqual(workflows.find_note_copies(include_preview=True)["items"][0]["preview"], "private body")

    def test_private_note_listing_shared_by_cli_and_mcp(self):
        notes = private_notes()
        rows = [
            {"id": 1, "body": "first", "edited_at": "2026-11-02"},
            {"id": 2, "body": "second", "edited_at": "2026-11-03"},
        ]
        with patch("substack_local.pullers.private_notes.files.load_private_notes", return_value=rows):
            items = notes.collect_local_notes(Path("/tmp"), "UTC", include_preview=False)
            self.assertEqual([item["id"] for item in items], ["2", "1"])
            self.assertNotIn("preview", items[0])
            self.assertEqual(
                notes.collect_local_notes(Path("/tmp"), "UTC", query="first")[0]["preview"],
                "first",
            )

    @patch("substack_local.mcp.pulls.private_notes")
    def test_private_note_search_pages_without_losing_total(self, module):
        module = module.return_value
        module.collect_local_notes.return_value = [
            {"id": "3"}, {"id": "2"}, {"id": "1"},
        ]

        page = workflows.find_note_copies(limit=1, offset=1)

        self.assertEqual([item["id"] for item in page["items"]], ["2"])
        self.assertEqual((page["count"], page["total"], page["next_offset"]), (1, 3, 2))
        self.assertNotIn("preview", page["items"][0])

    @patch("substack_local.mcp.pulls.public_notes")
    def test_public_note_history_is_anonymous_and_profile_scoped(self, module):
        module = module.return_value
        module.normalize_handle.return_value = "prettyhostile"
        module.load_config.return_value = {"profile": "@prettyhostile"}
        module.SyncEngine.return_value.sync.return_value = {"complete": True}
        workflows.pull_published_notes("@PrettyHostile")
        module.ApiClient.assert_called_once_with()
        self.assertEqual(module.resolve_output_dir.call_args.args[2], str(
            workflows.ROOT / "substack/published-notes/prettyhostile"
        ))

    @patch("substack_local.mcp.pulls.post_puller")
    def test_post_search_pages_and_can_include_preserved_missing_copies(self, module):
        module = module.return_value
        module.load_config.return_value = {"publication": "https://example.substack.com"}
        module.collect_local_posts.return_value = [
            {"id": "3", "title": "three"},
            {"id": "2", "title": "two"},
            {"id": "1", "title": "one"},
        ]

        page = workflows.find_post_copies(limit=1, offset=1, include_missing=True)

        self.assertEqual([item["id"] for item in page["items"]], ["2"])
        self.assertEqual((page["total"], page["next_offset"]), (3, 2))
        self.assertTrue(module.collect_local_posts.call_args.kwargs["include_missing"])

    def test_published_notes_status_search_and_single_read(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            workflows, "_public_note_dir", return_value=Path(temp)
        ):
            directory = Path(temp)
            (directory / ".sync").mkdir()
            (directory / "notes").mkdir()
            (directory / ".sync/state.json").write_text(json.dumps({
                "profile": "@prettyhostile", "last_sync_at": "2026-11-05T12:00:00Z",
                "notes": {
                    "10": {"file": "notes/10.json", "remote_status": "present"},
                    "20": {"file": "notes/20.json", "remote_status": "missing"},
                },
            }), encoding="utf-8")
            for note_id in ("10", "20"):
                (directory / f"notes/{note_id}.json").write_text(json.dumps({
                    "note": {"body": f"Full body {note_id}", "date": f"2026-11-{note_id}"},
                    "permalink": f"https://substack.com/@prettyhostile/note/c-{note_id}",
                }), encoding="utf-8")
                (directory / f"notes/{note_id}.md").write_text(f"Markdown {note_id}", encoding="utf-8")

            status = workflows.published_notes_status("https://substack.com/@prettyhostile")
            first = workflows.find_published_notes("@prettyhostile", limit=1)
            all_notes = workflows.find_published_notes("@prettyhostile", include_missing=True)
            second_page = workflows.find_published_notes(
                "@prettyhostile", include_missing=True, limit=1, offset=1,
            )
            read = workflows.read_published_note("@prettyhostile", "c-10")

            self.assertEqual((status["present"], status["missing_local_preserved"]), (1, 1))
            self.assertEqual((first["total"], first["next_offset"]), (1, None))
            self.assertNotIn("body", first["items"][0])
            self.assertNotIn("preview", first["items"][0])
            self.assertNotIn("file", first["items"][0])
            self.assertEqual(all_notes["total"], 2)
            self.assertEqual((second_page["count"], second_page["total"], second_page["next_offset"]),
                             (1, 2, None))
            self.assertEqual(second_page["items"][0]["id"], "10")
            self.assertIn("preview", workflows.find_published_notes(
                "@prettyhostile", include_preview=True,
            )["items"][0])
            self.assertEqual(read["markdown"], "Markdown 10")
            self.assertEqual(read["remote_status"], "present")
            with self.assertRaises(LookupError):
                workflows.read_published_note("@prettyhostile", "20")
            self.assertEqual(
                workflows.read_published_note("@prettyhostile", "20", include_missing=True)["markdown"],
                "Markdown 20",
            )

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
