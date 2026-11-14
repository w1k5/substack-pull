"""The desktop sign-in shares the existing publication and Keychain contract."""

import json
from io import StringIO
import os
import ssl
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from substack_local.desktop.connection import configure, current_publication, discover, publication_url, verify
from substack_local.pullers.posts import PullError
from substack_local.paths import data_root


class DesktopConnectionTests(unittest.TestCase):
    @patch("substack_local.desktop.connection.ApiClient")
    def test_discovery_selects_one_eligible_publication(self, client):
        client.return_value.get_json.return_value = {"publicationUsers": [
            {"role": "admin", "publication": {"subdomain": "writer", "name": "Writing"}},
            {"role": "contributor", "publication": {"subdomain": "other"}},
            {"role": "editor", "is_byline_only": True, "publication": {"subdomain": "byline"}},
            {"role": "admin", "publication": {"subdomain": "outside.example"}},
        ]}
        self.assertEqual(discover("sample"), {
            "publications": [{"name": "Writing", "address": "writer.substack.com"}],
            "selected": "writer.substack.com",
        })
        client.assert_called_once_with("https://substack.com", "sample")
        client.return_value.get_json.assert_called_once_with("/api/v1/user/profile/self")

    @patch("substack_local.desktop.connection.ApiClient")
    def test_multiple_publications_prompt_unless_saved_choice_is_available(self, client):
        client.return_value.get_json.return_value = {"publicationUsers": [
            {"role": "admin", "publication": {"subdomain": "first"}},
            {"role": "editor", "publication": {"subdomain": "second"}},
        ]}
        self.assertIsNone(discover("sample")["selected"])
        self.assertIsNone(discover("sample", "old.substack.com")["selected"])
        self.assertEqual(discover("sample", "https://second.substack.com")["selected"], "second.substack.com")

    @patch("substack_local.desktop.connection.ApiClient")
    def test_discovery_returns_empty_choices_or_safe_error_for_manual_fallback(self, client):
        client.return_value.get_json.return_value = {"publicationUsers": []}
        self.assertEqual(discover("sample"), {"publications": [], "selected": None})
        client.return_value.get_json.side_effect = PullError("Upstream request details")
        with self.assertRaisesRegex(PullError, "could not find your publications automatically"):
            discover("sample")

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
            client.return_value.get_json.return_value = {"posts": [], "total": 0}
            result = verify("name.substack.com", "sample-session")
        self.assertEqual(result, {
            "publication": "https://name.substack.com", "account": "name.substack.com"
        })
        client.assert_called_once_with("https://name.substack.com", "sample-session")
        client.return_value.get_json.assert_called_once_with(
            "/api/v1/post_management/drafts?offset=0&limit=1&order_by=draft_updated_at&order_direction=desc"
        )

    def test_reports_request_failure_without_claiming_the_account_lacks_access(self):
        with patch("substack_local.desktop.connection.ApiClient") as client:
            error = PullError("Internal upstream details")
            error.__cause__ = HTTPError("https://name.substack.com", 400, "Bad Request", {}, None)
            client.return_value.get_json.side_effect = error
            with self.assertRaisesRegex(PullError, r"publication access check failed \(HTTP 400\)"):
                verify("name.substack.com", "sample-session")

    def test_rejects_json_without_a_drafts_list(self):
        with patch("substack_local.desktop.connection.ApiClient") as client:
            client.return_value.get_json.return_value = {"error": "Internal upstream details"}
            with self.assertRaisesRegex(PullError, "Substack returned an unexpected response"):
                verify("name.substack.com", "sample-session")

    def test_reports_certificate_failure_without_returning_upstream_details(self):
        with patch("substack_local.desktop.connection.ApiClient") as client:
            error = PullError("Internal upstream details")
            error.__cause__ = URLError(ssl.SSLCertVerificationError("certificate failure"))
            client.return_value.get_json.side_effect = error
            with self.assertRaisesRegex(PullError, "could not verify Substack’s HTTPS certificate"):
                verify("name.substack.com", "sample-session")

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
