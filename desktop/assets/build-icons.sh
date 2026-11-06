#!/bin/sh
set -eu

ASSETS=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SIZES="$ASSETS/.icon-sizes"
mkdir -p "$SIZES"
swift "$ASSETS/make-icon.swift" "$ASSETS/Clearview.png"
for size in 16 32 64 128 256 512 1024; do
  sips -z "$size" "$size" "$ASSETS/Clearview.png" --out "$SIZES/icon-$size.png" >/dev/null
done
python3 "$ASSETS/make-icon-bundles.py" "$ASSETS/Clearview.icns" "$ASSETS/Clearview.ico" \
  "$SIZES/icon-16.png" "$SIZES/icon-32.png" "$SIZES/icon-64.png" \
  "$SIZES/icon-128.png" "$SIZES/icon-256.png" "$SIZES/icon-512.png" \
  "$SIZES/icon-1024.png"
rm -rf "$SIZES"
