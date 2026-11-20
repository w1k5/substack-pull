"""Note reply URL resolution and paginated thread retrieval."""

import unittest

from substack_local.pullers.note_conversations import note_id_from, read_note_conversation


class FakeApi:
    def __init__(self):
        self.paths = []

    def get_json(self, path):
        self.paths.append(path)
        root = {"id": 10, "body": "Root", "publication_id": 42}
        parent = {"id": 11, "body": "Parent", "ancestor_path": "10"}
        selected = {"id": 12, "body": "Selected", "ancestor_path": "10.11"}
        if path == "/api/v1/reader/comment/12":
            return {"item": {"comment": selected, "parentComments": [root, parent]}}
        if path == "/api/v1/reader/comment/10/replies?publication_id=42&comment_id=10":
            return {"commentBranches": [{"comment": parent, "descendantComments": [
                {"comment": selected}]}], "nextCursor": "next"}
        if path == "/api/v1/reader/comment/10/replies?publication_id=42&comment_id=10&cursor=next":
            return {"commentBranches": [{"comment": {"id": 13, "body": "Sibling", "ancestor_path": "10"},
                                        "descendantComments": []}], "nextCursor": None}
        raise AssertionError(path)


class NoteConversationTests(unittest.TestCase):
    def test_reference_validation(self):
        self.assertEqual(note_id_from("https://substack.com/@eli/note/c-12"), "12")
        self.assertEqual(note_id_from("https://substack.com/profile/123-eli/note/c-12"), "12")
        for value in ("https://evil.example/@eli/note/c-12", "http://substack.com/@eli/note/c-12",
                      "https://substack.com/@eli/note/p-12"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                note_id_from(value)

    def test_selected_reply_resolves_entire_conversation(self):
        api = FakeApi()
        result = read_note_conversation("https://substack.com/@eli/note/c-12", api=api)
        self.assertEqual((result["root_id"], result["selected_id"], result["pages"]), ("10", "12", 2))
        self.assertEqual([row["id"] for row in result["replies"]], ["10", "11", "12", "13"])
        self.assertEqual(result["replies"][2]["parent_id"], "11")

    def test_missing_nested_children_are_fetched_from_parent(self):
        class MissingBranchApi(FakeApi):
            def get_json(self, path):
                if path == "/api/v1/reader/comment/10/replies?publication_id=42&comment_id=10":
                    return {"commentBranches": [{"comment": {
                        "id": 11, "body": "Parent", "ancestor_path": "10", "children_count": 2},
                        "descendantComments": [{"comment": {
                            "id": 12, "body": "Selected", "ancestor_path": "10.11"}}]}],
                        "nextCursor": None}
                if path == "/api/v1/reader/comment/11/replies?publication_id=42&comment_id=11":
                    return {"commentBranches": [{"comment": {
                        "id": 12, "body": "Selected", "ancestor_path": "10.11"},
                        "descendantComments": []}, {"comment": {
                        "id": 14, "body": "Missing", "ancestor_path": "10.11"},
                        "descendantComments": []}], "nextCursor": None}
                return super().get_json(path)

        result = read_note_conversation("c-12", api=MissingBranchApi())
        self.assertEqual({row["id"] for row in result["replies"]}, {"10", "11", "12", "14"})
        self.assertTrue(result["conversation_complete"])
        self.assertEqual(result["queried_parent_ids"], ["10", "11"])


if __name__ == "__main__":
    unittest.main()
