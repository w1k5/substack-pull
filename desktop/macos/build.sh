#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
test "$(uname -m)" = arm64
python desktop/release_metadata.py
version=$(python -c 'import json; print(json.load(open("desktop/release.json"))["version"])')
build="$PWD/desktop/macos/.build/beta"
app="$build/Clearview.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
python desktop/release_metadata.py --mac-plist "$app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier io.github.w1k5.clearview' "$app/Contents/Info.plist"
cp desktop/assets/Clearview.icns "$app/Contents/Resources/"
xcrun swiftc -target arm64-apple-macos13.0 -parse-as-library -O \
  desktop/macos/ClearviewApp.swift -o "$app/Contents/MacOS/Clearview"

python -m PyInstaller --noconfirm --clean --onedir --name clearview-engine \
  --distpath "$build/engine-dist" --workpath "$build/py-work" --specpath "$build" \
  --paths "$PWD" --target-architecture arm64 --collect-data tzdata \
  --hidden-import tzlocal --hidden-import substack_local.mcp.server --copy-metadata mcp \
  --add-data "$PWD/substack_local/dashboard/static:substack_local/dashboard/static" \
  --add-data "$PWD/substack_local/pullers/private_notes/note-runway-template.html:substack_local/pullers/private_notes" \
  substack_local/desktop/entry.py
ditto "$build/engine-dist/clearview-engine" "$app/Contents/Resources/engine"
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"
lipo "$app/Contents/MacOS/Clearview" -verify_arch arm64
lipo "$app/Contents/Resources/engine/clearview-engine" -verify_arch arm64

stem="$build/Clearview-$version-macos-arm64"
ditto -c -k --sequesterRsrc --keepParent "$app" "$stem.zip"
mkdir -p "$build/dmg"
ditto "$app" "$build/dmg/Clearview.app"
ln -sfn /Applications "$build/dmg/Applications"
hdiutil create -ov -volname Clearview -srcfolder "$build/dmg" -format UDZO "$stem.dmg"
mount="$build/mounted"
mkdir -p "$mount"
for attempt in 1 2 3 4 5; do
  if hdiutil attach -readonly -nobrowse -mountpoint "$mount" "$stem.dmg"; then
    break
  fi
  if [[ "$attempt" = 5 ]]; then exit 1; fi
  sleep 3
done
trap 'hdiutil detach "$mount"' EXIT
codesign --verify --deep --strict "$mount/Clearview.app"
test "$(readlink "$mount/Applications")" = /Applications
hdiutil detach "$mount"
trap - EXIT
mkdir -p "$build/check"
ditto -x -k "$stem.zip" "$build/check"
codesign --verify --deep --strict "$build/check/Clearview.app"
python desktop/smoke_package.py "$build/check/Clearview.app/Contents/Resources/engine/clearview-engine"
(cd "$build" && shasum -a 256 "Clearview-$version-macos-arm64.zip" "Clearview-$version-macos-arm64.dmg" > SHA256SUMS-macos.txt)
