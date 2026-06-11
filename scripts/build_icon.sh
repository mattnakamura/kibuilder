#!/usr/bin/env bash
# Generate resources/kibuilder.icns from the procedural Pillow source.
# Uses only macOS built-in tools (sips + iconutil) after the Pillow draw.

set -euo pipefail

cd "$(dirname "$0")/.."

PNG=resources/icon_1024.png
ICNS=resources/kibuilder.icns
ICONSET=resources/kibuilder.iconset

echo ">>> Drawing 1024x1024 source"
python scripts/make_icon.py

echo ">>> Generating macOS iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for sz in 16 32 128 256 512; do
    sips -z "$sz" "$sz" "$PNG" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
    twox=$((sz * 2))
    sips -z "$twox" "$twox" "$PNG" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
done

echo ">>> Compiling .icns"
iconutil -c icns "$ICONSET" -o "$ICNS"
ls -lh "$ICNS"
echo ">>> Done."
