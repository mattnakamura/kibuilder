#!/usr/bin/env bash
# Package dist/kibuilder.app into a versioned, arch-tagged DMG.
#
# Usage:
#   scripts/make_dmg.sh                 # version from pyproject, arch from host
#   scripts/make_dmg.sh 0.1.0 arm64     # explicit overrides
#
# Output: dist/kibuilder-<version>-<arch>.dmg

set -euo pipefail

cd "$(dirname "$0")/.."

APP=dist/kibuilder.app
[[ -d "$APP" ]] || { echo "!!! $APP not found — run scripts/build_app.sh first" >&2; exit 1; }

VERSION="${1:-$(python -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')}"
ARCH="${2:-$(uname -m)}"
[[ "$ARCH" == "x86_64" || "$ARCH" == "arm64" ]] || { echo "!!! unknown arch: $ARCH" >&2; exit 1; }

DMG="dist/kibuilder-${VERSION}-${ARCH}.dmg"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

echo ">>> Staging $APP"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # drag-to-install affordance

echo ">>> Creating $DMG"
rm -f "$DMG"
hdiutil create -volname "kibuilder ${VERSION}" \
    -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

shasum -a 256 "$DMG"
