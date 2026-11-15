"""Post conversation endpoint, pagination, and local MCP workflow contracts."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from substack_local.pullers.post_conversations import (
    load_conversation, post_id_from, pull_conversation,
)
from substack_local.pullers.public_notes import PullError
from substack_local.workflows import backups


def comment(item_id, path="", children=0):
    return {"id": item_id, "post_id": 198308000, "user_id": 7,
            "name": "Reader", "body": f"Body {item_id}", "date": "2026-10-27T12:00:00Z",
            "ancestor_path": path, "children_count": children}


class FakeApi:
    def __init__(self):
        self.paths = []

    def get_json(self, path):
        self.paths.append(path)
        if path == "/api/v1/posts/by-id/198308000?as-feed-item=1":
            return {"post": {"id": 198308000, "publication_id": 6892145,
                             "title": "Example", "canonical_url": "https://example.substack.com/p/example"},
                    "publication": {"id": 6892145, "name": "Example"}}
        if path == "/api/v1/reader/post/198308000/replies?publication_id=6892145":
            return {"commentBranches": [
                {"comment": comment(10, children=2), "descendantComments": [
                    {"type": "comment", "comment": comment(11, "10")}]}
            ], "moreBranches": 1, "nextCursor": "next", "automodHiddenBranches": []}
        if path == "/api/v1/reader/post/198308000/replies?publication_id=6892145&cursor=next":
            return {"commentBranches": [
                {"comment": comment(20), "descendantComments": []},
                {"comment": comment(10, children=2), "descendantComments": [
                    {"type": "comment", "comment": comment(11, "10")}]},
            ], "moreBranches": 0, "nextCursor": None, "automodHiddenBranches": []}
        raise AssertionError(f"Unexpected path: {path}")


class ConversationTests(unittest.TestCase):
    def test_reference_validation(self):
        self.assertEqual(post_id_from("198308000"), "198308000")
        self.assertEqual(post_id_from(
            "https://substack.com/@prettyhostile/note/p-198308000?utm_source=test"
        ), "198308000")
        for value in ("https://evil.example/note/p-198308000", "http://substack.com/note/p-198308000",
                      "https://substack.com/@prettyhostile/note/c-10", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                post_id_from(value)

    def test_pull_follows_cursor_saves_raw_pages_and_reports_gaps(self):
        api = FakeApi()
        with tempfile.TemporaryDirectory() as temp:
            result = pull_conversation("https://substack.com/@prettyhostile/note/p-198308000",
                                       Path(temp), api=api)
            saved = load_conversation("198308000", Path(temp))
        self.assertEqual((result["pages"], result["replies"]), (2, 3))
        self.assertEqual([row["id"] for row in saved["comments"]], ["10", "11", "20"])
        self.assertEqual(saved["comments"][1]["parent_id"], "10")
        self.assertEqual(saved["short_branches"], [
            {"id": "10", "reported_children": 2, "returned_children": 1}])
        self.assertEqual(result["reported_unreturned_children"], 1)
        self.assertEqual(len(saved["pages"]), 2)
        self.assertEqual(api.paths[-1],
                         "/api/v1/reader/post/198308000/replies?publication_id=6892145&cursor=next")

    def test_repeated_cursor_does_not_publish_partial_backup(self):
        class RepeatingApi(FakeApi):
            def get_json(self, path):
                if path.endswith("cursor=next"):
                    return {"commentBranches": [], "nextCursor": "next"}
                return super().get_json(path)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(PullError):
                pull_conversation("198308000", Path(temp), api=RepeatingApi())
            self.assertFalse((Path(temp) / "198308000.json").exists())

    def test_repeated_page_does_not_publish_partial_backup(self):
        class RepeatingPageApi(FakeApi):
            def get_json(self, path):
                if path.endswith("cursor=next"):
                    return {"commentBranches": [
                        {"comment": comment(10), "descendantComments": [
                            {"type": "comment", "comment": comment(11, "10")}]}],
                            "nextCursor": "another"}
                return super().get_json(path)

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PullError, "repeated a replies page"):
                pull_conversation("198308000", Path(temp), api=RepeatingPageApi())
            self.assertFalse((Path(temp) / "198308000.json").exists())

    def test_local_workflows_page_search_and_read_thread(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            backups, "_post_conversation_dir", return_value=Path(temp)
        ), patch.object(backups, "private_notes") as private:
            private.return_value.load_config.return_value = {}
            private.return_value.reusable_session.return_value = "test-session"
            private.return_value.PrivateApiClient.return_value = FakeApi()
            backups.pull_post_conversation("198308000")
            status = backups.post_conversation_status("198308000")
            found = backups.find_post_replies("198308000", query="Body", limit=2)
            preview = backups.find_post_replies("198308000", include_preview=True)
            reply = backups.read_post_reply("198308000", "c-11")
            thread = backups.read_post_thread("198308000", "11")
            self.assertEqual(status["replies"], 3)
            self.assertEqual((found["total"], found["next_offset"]), (3, 2))
            self.assertNotIn("body", found["items"][0])
            self.assertIn("preview", preview["items"][0])
            self.assertEqual(reply["reply"]["parent_id"], "10")
            self.assertEqual([row["id"] for row in thread["items"]], ["10", "11"])
            private.return_value.PrivateApiClient.assert_called_once_with(
                "test-session", request_delay=0.25)


if __name__ == "__main__":
    unittest.main()
