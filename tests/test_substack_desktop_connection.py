"""The desktop sign-in shares the existing publication and Keychain contract."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from substack_local.desktop.connection import configure, current_publication, publication_url, verify
from substack_local.pullers.posts import PullError


class DesktopConnectionTests(unittest.TestCase):
    def test_rejects_non_publication_hosts_before_using_a_session(self):
        for value in ("substack.com", "example.com", "not-substack.com", "http://name.substack.com"):
            with self.subTest(value=value), self.assertRaises(PullError):
                publication_url(value)

    def test_verifies_editor_access_with_the_shared_client(self):
        with patch("substack_local.desktop.connection.ApiClient") as client:
            result = verify("name.substack.com", "sample-session")
        self.assertEqual(result, {
            "publication": "https://name.substack.com", "account": "name.substack.com"
        })
        client.assert_called_once_with("https://name.substack.com", "sample-session")
        client.return_value.get_json.assert_called_once_with("/api/v1/drafts?limit=1")

    def test_configuration_preserves_existing_backup_directory_and_never_saves_token(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"publication": "https://old.substack.com", "directory": "posts"}))
            result = configure(path, "new.substack.com")
            saved = json.loads(path.read_text())
            self.assertEqual(result["account"], "new.substack.com")
            self.assertEqual(saved, {
                "publication": "https://new.substack.com", "directory": "posts"
            })
            self.assertEqual(current_publication(path), "https://new.substack.com")


if __name__ == "__main__":
    unittest.main()
