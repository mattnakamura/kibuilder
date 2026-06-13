"""Locate the kicad-cli executable across platforms.

`shutil.which` alone fails in two common situations:
- macOS .app bundles launched from Finder don't inherit the shell PATH,
  so /usr/local/bin etc. are invisible.
- Windows installs KiCad under Program Files without touching PATH.

This module probes PATH first, then the conventional install locations.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

log = logging.getLogger("kibuilder.kicad")

_MACOS_CANDIDATES = [
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/opt/homebrew/bin/kicad-cli",
]

_LINUX_CANDIDATES = [
    "/usr/bin/kicad-cli",
    "/usr/local/bin/kicad-cli",
    "/snap/bin/kicad.kicad-cli",
    "/var/lib/flatpak/exports/bin/org.kicad.KiCad",
]


def _windows_candidates() -> list[str]:
    """KiCad installs to <ProgramFiles>\\KiCad\\<major.minor>\\bin\\kicad-cli.exe."""
    out: list[str] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if not base:
            continue
        kicad_root = Path(base) / "KiCad"
        if not kicad_root.is_dir():
            continue
        # version dirs sorted newest-first so 9.0 beats 8.0
        for vdir in sorted(kicad_root.iterdir(), reverse=True):
            exe = vdir / "bin" / "kicad-cli.exe"
            if exe.exists():
                out.append(str(exe))
    return out


def find_kicad_cli() -> str | None:
    """Return an absolute path to kicad-cli, or None if not found."""
    hit = shutil.which("kicad-cli")
    if hit:
        return hit
    if sys.platform == "darwin":
        candidates = _MACOS_CANDIDATES
    elif sys.platform == "win32":
        candidates = _windows_candidates()
    else:
        candidates = _LINUX_CANDIDATES
    for c in candidates:
        if Path(c).exists():
            log.debug("kicad-cli found at %s", c)
            return c
    return None
