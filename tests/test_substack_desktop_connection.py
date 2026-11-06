"""The desktop sign-in shares the existing publication and Keychain contract."""

import json
from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from substack_local.desktop.connection import configure, current_publication, publication_url, verify
from substack_local.pullers.posts import PullError
from substack_local.paths import data_root


class DesktopConnectionTests(unittest.TestCase):
    def test_packaged_data_location_is_separate_from_code(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"CLEARVIEW_DATA_DIR": folder}):
            self.assertEqual(data_root(), Path(folder).resolve())

    def test_windows_data_location_is_shared_with_optional_mcp(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}, clear=True), \
                patch("substack_local.paths.sys.platform", "win32"):
            self.assertEqual(data_root(), Path(folder) / "Clearview")

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

    def test_windows_connect_verifies_before_saving_session(self):
        from substack_local.desktop.connection import main
        with TemporaryDirectory() as folder, patch("sys.argv", [
            "connection", "connect", "--publication", "name.substack.com",
            "--config", str(Path(folder) / "settings.json"),
        ]), patch("sys.stdin", StringIO("sample-session")), patch("sys.stdout", new_callable=StringIO) as output, \
                patch("substack_local.desktop.connection.verify") as verify_session, \
                patch("substack_local.desktop.connection.KeychainStore") as store:
            verify_session.return_value = {
                "publication": "https://name.substack.com", "account": "name.substack.com"
            }
            self.assertEqual(main(), 0)
            verify_session.assert_called_once_with("name.substack.com", "sample-session")
            store.return_value.save.assert_called_once_with("name.substack.com", "sample-session")
            self.assertNotIn("sample-session", output.getvalue())
            self.assertNotIn("sample-session", (Path(folder) / "settings.json").read_text())


if __name__ == "__main__":
    unittest.main()
