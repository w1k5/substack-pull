from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "substack_pull.py"
SPEC = importlib.util.spec_from_file_location("substack_pull", SCRIPT)
assert SPEC and SPEC.loader
substack_pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(substack_pull)


class FakeApi:
    base_url = "https://example.substack.com"

    def __init__(self, category: str):
        self.category = category

    def get_json(self, path: str):
        if path.startswith("/api/v1/post_management/"):
            category = path.split("/api/v1/post_management/", 1)[1].split("?", 1)[0]
            posts = [self._list_item()] if category == self.category else []
            return {"posts": posts, "total": len(posts)}
        if path == "/api/v1/drafts/42/scheduled_release":
            return {"trigger_at": "2027-01-05T16:14:00.000Z"}
        if path in {"/api/v1/drafts/42", "/api/v1/posts/by-id/42"}:
            return {
                "id": 42,
                "draft_title": f"Post in {self.category}",
                "body_html": f"<p>{self.category} body</p>",
            }
        raise AssertionError(f"Unexpected API path: {path}")

    def _list_item(self):
        return {
            "id": 42,
            "draft_title": f"Post in {self.category}",
            "draft_updated_at": f"2026-10-12T00:00:0{list(substack_pull.CATEGORY_ENDPOINTS).index(self.category)}Z",
        }


class CategoryTransitionTests(unittest.TestCase):
    def sync(self, output_dir: Path, category: str, timestamp: str):
        engine = substack_pull.SyncEngine(
            FakeApi(category),
            output_dir,
            now=lambda: timestamp,
        )
        return engine.sync()

    def assert_only_current_category(self, output_dir: Path, category: str):
        state = json.loads((output_dir / ".sync" / "state.json").read_text())
        for candidate in substack_pull.CATEGORY_ENDPOINTS:
            artifacts = [
                output_dir / candidate / f"42{suffix}"
                for suffix in substack_pull.POST_ARTIFACT_SUFFIXES
            ]
            if candidate == category:
                self.assertIn("42", state["categories"][candidate])
                self.assertTrue(all(path.is_file() for path in artifacts))
            else:
                self.assertNotIn("42", state["categories"].get(candidate, {}))
                self.assertFalse(any(path.exists() for path in artifacts))

    def test_every_authenticated_category_transition_reconciles_directories(self):
        categories = tuple(substack_pull.CATEGORY_ENDPOINTS)
        for old_category in categories:
            for new_category in categories:
                if old_category == new_category:
                    continue
                with self.subTest(old=old_category, new=new_category):
                    with tempfile.TemporaryDirectory() as temporary:
                        output_dir = Path(temporary)
                        self.sync(output_dir, old_category, "2026-10-12T00:00:00Z")
                        self.assertTrue(
                            all(
                                (
                                    output_dir
                                    / old_category
                                    / f"42{suffix}"
                                ).is_file()
                                for suffix in substack_pull.POST_ARTIFACT_SUFFIXES
                            )
                        )
                        summary = self.sync(
                            output_dir,
                            new_category,
                            "2026-10-13T00:00:00Z",
                        )
                        self.assert_only_current_category(output_dir, new_category)
                        self.assertNotIn("category_transitions", summary)
                        self.assertEqual(
                            0,
                            summary["categories"][old_category][
                                "missing_local_preserved"
                            ],
                        )

    def test_true_disappearance_moves_to_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.sync(output_dir, "drafts", "2026-10-12T00:00:00Z")
            api = FakeApi("drafts")
            api.category = "none"
            summary = substack_pull.SyncEngine(
                api,
                output_dir,
                now=lambda: "2026-10-13T00:00:00Z",
            ).sync()

            self.assertFalse((output_dir / "drafts" / "42.json").exists())
            self.assertTrue(
                all(
                    (output_dir / "archive" / "drafts" / f"42{suffix}").is_file()
                    for suffix in substack_pull.POST_ARTIFACT_SUFFIXES
                )
            )
            self.assertEqual(
                0,
                summary["categories"]["drafts"]["missing_local_preserved"],
            )
            self.assertEqual(1, summary["categories"]["drafts"]["archived"])
            state = json.loads((output_dir / ".sync" / "state.json").read_text())
            self.assertNotIn("42", state["categories"]["drafts"])
            self.assertEqual(
                "archive/drafts/42.json",
                state["archive"]["drafts"]["42"]["file"],
            )

    def test_failed_destination_fetch_keeps_former_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.sync(output_dir, "drafts", "2026-10-12T00:00:00Z")
            api = FakeApi("scheduled")
            successful_get = api.get_json

            def fail_full_fetch(path: str):
                if path == "/api/v1/drafts/42":
                    raise substack_pull.PullError("simulated fetch failure")
                return successful_get(path)

            api.get_json = fail_full_fetch
            summary = substack_pull.SyncEngine(
                api,
                output_dir,
                now=lambda: "2026-10-13T00:00:00Z",
            ).sync()

            self.assertTrue(
                all(
                    (output_dir / "drafts" / f"42{suffix}").is_file()
                    for suffix in substack_pull.POST_ARTIFACT_SUFFIXES
                )
            )
            self.assertFalse((output_dir / "scheduled" / "42.json").exists())
            self.assertNotIn("category_transitions", summary)
            self.assertEqual(1, summary["categories"]["scheduled"]["failures"])

    def test_public_pull_does_not_reconcile_private_categories(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            self.sync(output_dir, "drafts", "2026-10-12T00:00:00Z")
            engine = substack_pull.SyncEngine(
                FakeApi("published"),
                output_dir,
                public_only=True,
                now=lambda: "2026-10-13T00:00:00Z",
            )
            original_public_paginator = substack_pull.paginate_public_posts
            substack_pull.paginate_public_posts = lambda api, limit: [api._list_item()]
            try:
                summary = engine.sync()
            finally:
                substack_pull.paginate_public_posts = original_public_paginator

            self.assertTrue((output_dir / "drafts" / "42.json").is_file())
            self.assertTrue((output_dir / "published" / "42.json").is_file())
            self.assertNotIn("category_transitions", summary)


if __name__ == "__main__":
    unittest.main()
