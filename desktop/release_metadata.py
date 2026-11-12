"""Validate shared release metadata and stamp a macOS bundle plist."""

import argparse
import json
import plistlib
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--mac-plist", type=Path)
    args = parser.parse_args()
    desktop = Path(__file__).resolve().parent
    release = json.loads((desktop / "release.json").read_text(encoding="utf-8"))
    version, build = release["version"], release["build"]
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-beta\.[1-9][0-9]*)?", version)
    if not match or type(build) is not int or not 1 <= build <= 9999:
        parser.error("Expected MAJOR.MINOR.PATCH[-beta.N] and a build number from 1 to 9999.")
    if any(int(part) > 65534 for part in match.groups()):
        parser.error("Version components must fit Windows file version fields.")
    if args.tag is not None and args.tag != f"v{version}":
        parser.error(f"Tag {args.tag!r} does not match release version {version}.")
    if args.mac_plist:
        metadata = plistlib.loads((desktop / "macos" / "Info.plist").read_bytes())
        metadata["CFBundleShortVersionString"] = ".".join(match.groups())
        metadata["CFBundleVersion"] = str(build)
        metadata["ClearviewReleaseVersion"] = version
        args.mac_plist.write_bytes(plistlib.dumps(metadata))


if __name__ == "__main__":
    main()
