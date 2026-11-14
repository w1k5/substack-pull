from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from substack_local.desktop.updates import DOWNLOAD_BASE, available_update, check_for_update


def release(version, suffix="macos-arm64.dmg", *, draft=False, expected_url=True):
    asset = f"Clearview-{version}-{suffix}"
    return {
        "tag_name": f"v{version}", "draft": draft, "prerelease": "-beta." in version,
        "assets": [{
            "name": asset, "state": "uploaded",
            "browser_download_url": f"{DOWNLOAD_BASE}/v{version}/{asset}" if expected_url else "https://example.org",
        }],
    }


class DesktopUpdatesTests(TestCase):
    def test_beta_checks_choose_highest_published_compatible_version(self):
        releases = [release("0.1.0-beta.9"), release("0.1.0-beta.10"),
                    release("0.1.0-beta.11", "windows-x64.zip"),
                    release("0.1.0-beta.12", draft=True),
                    release("0.1.0-beta.13", expected_url=False)]
        update = available_update(releases, "0.1.0-beta.6", "macos-arm64.dmg")
        self.assertEqual(update["version"], "0.1.0-beta.10")
        self.assertIsNone(available_update(releases, "0.1.0-beta.10", "macos-arm64.dmg"))

    def test_stable_channel_skips_beta_and_stable_supersedes_same_beta(self):
        self.assertIsNone(available_update([release("0.2.0-beta.1")], "0.1.0", "macos-arm64.dmg"))
        update = available_update([release("0.1.0", "windows-x64.zip")], "0.1.0-beta.10", "windows-x64.zip")
        self.assertEqual(update["version"], "0.1.0")

    @patch("substack_local.desktop.updates.urlopen")
    def test_automatic_checks_are_throttled_and_manual_checks_are_not(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        with TemporaryDirectory() as directory, patch("sys.platform", "darwin"), patch("sys.frozen", True, create=True):
            root = Path(directory)
            self.assertEqual(check_for_update("0.1.0-beta.6", root, automatic=True), {"update": None})
            check_for_update("0.1.0-beta.6", root, automatic=True)
            urlopen.assert_called_once()
            check_for_update("0.1.0-beta.6", root)
        self.assertEqual(urlopen.call_count, 2)
