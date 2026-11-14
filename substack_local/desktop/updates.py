"""Discover a newer compatible installer on Clearview's GitHub Releases page."""

import json
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, urlopen

REPOSITORY = "w1k5/substack-pull"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
DOWNLOAD_BASE = f"https://github.com/{REPOSITORY}/releases/download"
VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-beta\.([1-9]\d*))?", re.ASCII)


def version_key(version):
    match = VERSION.fullmatch(version)
    if match is None:
        raise ValueError("Could not identify this Clearview build.")
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), beta is None, int(beta or 0)


def available_update(releases, current, platform_suffix):
    installed = version_key(current)
    best = None
    for release in releases:
        if release.get("draft") or (installed[3] and release.get("prerelease")):
            continue
        tag = release.get("tag_name", "")
        if not tag.startswith("v") or not VERSION.fullmatch(tag):
            continue
        key = version_key(tag)
        if key <= installed or (best and key <= best[0]) or (installed[3] and not key[3]):
            continue
        version = tag[1:]
        asset_name = f"Clearview-{version}-{platform_suffix}"
        url = f"{DOWNLOAD_BASE}/{tag}/{asset_name}"
        if any(asset.get("name") == asset_name and asset.get("state") == "uploaded"
               and asset.get("browser_download_url") == url for asset in release.get("assets", [])):
            best = key, {"version": version, "url": url}
    return best[1] if best else None


def check_for_update(current: str, data_directory: Path, *, automatic: bool = False) -> dict:
    suffix = {"darwin": "macos-arm64.dmg", "win32": "windows-x64.zip"}.get(sys.platform)
    if suffix is None or not getattr(sys, "frozen", False):
        raise ValueError("Update checks are available in the packaged Clearview app.")
    version_key(current)
    stamp = data_directory / f".last-update-check-{current}"
    if automatic and stamp.exists() and 0 <= time.time() - stamp.stat().st_mtime < 24 * 60 * 60:
        return {"update": None}
    request = Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Clearview desktop updater",
    })
    with urlopen(request, timeout=8) as response:
        releases = json.loads(response.read(2_000_000))
    if not isinstance(releases, list):
        raise ValueError("GitHub did not return a release list.")
    update = available_update(releases, current, suffix)
    data_directory.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    return {"update": update}
