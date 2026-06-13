# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for kibuilder.app.

Builds a double-clickable macOS .app bundle that embeds:
- The Python interpreter (3.12)
- PyQt6 + Qt frameworks
- cadquery-ocp (OpenCASCADE bindings — large, ~250 MB)
- PyObjC framework wrapper (for Cocoa_Window orderOut_)
- The kibuilder package itself

Build with:
    pip install pyinstaller
    pyinstaller kibuilder.spec
    # output: dist/kibuilder.app

Notes:
- Onedir bundle (not onefile) so cold-start time is bearable.
- Hidden imports cover OCP submodules that PyInstaller's analyzer misses
  because they're imported lazily inside kibuilder.render.
- kicad-cli is NOT bundled — the app detects it at runtime and prompts the
  user to install KiCad if missing.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

block_cipher = None

# OCP (OpenCASCADE) is split into many submodules; PyInstaller's static
# analyzer can't follow them through string-based imports, so we collect
# every submodule explicitly.
ocp_submodules = collect_submodules("OCP")
ocp_dylibs = collect_dynamic_libs("OCP")

hidden = [
    # PyQt6 — Qt6 sub-modules we touch
    "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
    # PyObjC bits for macOS NSWindow manipulation
    "Cocoa", "objc",
    # PIL plugins (PyInstaller misses lazy plugin loaders)
    "PIL.JpegImagePlugin", "PIL.PngImagePlugin",
    # YAML loader backend
    "yaml.cyaml",
] + ocp_submodules

datas = []

a = Analysis(
    ["scripts/launcher.py"],
    pathex=["src"],
    binaries=ocp_dylibs,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Big packages we definitely don't need pulled in
        "matplotlib", "scipy", "pandas", "IPython", "jedi",
        "test", "unittest", "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kibuilder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # no terminal window
    disable_windowed_traceback=False,
    target_arch=None,     # let it pick host arch (arm64 on Apple Silicon)
    # Identity comes from the CODESIGN_IDENTITY env var in CI; local builds
    # stay ad-hoc signed (None).
    codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
    entitlements_file="resources/entitlements.plist",
    icon="resources/kibuilder.ico" if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="kibuilder",
)

# BUNDLE is macOS-only; on Windows/Linux the onedir COLLECT output in
# dist/kibuilder/ is the final artifact.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="kibuilder.app",
        icon="resources/kibuilder.icns",
        bundle_identifier="io.github.mattnakamura.kibuilder",
        version="0.1.0",
        info_plist={
            "CFBundleName": "kibuilder",
            "CFBundleDisplayName": "kibuilder",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # Required so Cocoa_Window can attach an OpenGL surface without
            # the macOS sandbox blocking it.
            "NSPrincipalClass": "NSApplication",
            # Don't show in Dock until the splash actually appears? Leave as
            # default app (LSUIElement=False) so users can Cmd-Tab to it.
        },
    )
