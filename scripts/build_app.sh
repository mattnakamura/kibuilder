#!/usr/bin/env bash
# Build kibuilder.app via PyInstaller.
#
# Usage:
#   scripts/build_app.sh              # build the .app
#   scripts/build_app.sh --clean      # nuke caches first
#   scripts/build_app.sh --install    # also copy result into /Applications
#
# Run from the repo root inside the env that has kibuilder + pyinstaller
# installed (e.g. `pyenv activate openpauw`).

set -euo pipefail

cd "$(dirname "$0")/.."

CLEAN=0
INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
        --install) INSTALL=1 ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
    esac
done

# Ensure pyinstaller is available in the current env.
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo ">>> Installing PyInstaller into the current env"
    pip install "pyinstaller>=6.0"
fi

# Make sure the app icon is built before PyInstaller bundles it.
if [[ ! -f resources/kibuilder.icns ]]; then
    echo ">>> Building app icon (resources/kibuilder.icns)"
    scripts/build_icon.sh
fi

if [[ $CLEAN -eq 1 ]]; then
    echo ">>> Cleaning build/, dist/, and PyInstaller caches"
    rm -rf build dist
fi

echo ">>> Running PyInstaller (this can take 2-3 min on a cold cache)"
python -m PyInstaller --noconfirm kibuilder.spec

if [[ ! -d "dist/kibuilder.app" ]]; then
    echo "!!! Build did not produce dist/kibuilder.app" >&2
    exit 1
fi

SIZE=$(du -sh dist/kibuilder.app | awk '{print $1}')
echo ""
echo "=========================================="
echo "  Built dist/kibuilder.app  (${SIZE})"
echo "=========================================="
echo ""
echo "To run:        open dist/kibuilder.app"
echo "To install:    cp -R dist/kibuilder.app /Applications/"
echo ""
echo "First launch will hit Gatekeeper (app is unsigned). Right-click"
echo "the app -> Open -> confirm. Subsequent launches will be normal."
echo ""

if [[ $INSTALL -eq 1 ]]; then
    echo ">>> Copying to /Applications/"
    rm -rf /Applications/kibuilder.app
    cp -R dist/kibuilder.app /Applications/
    echo ">>> Installed. Run with: open /Applications/kibuilder.app"
fi
