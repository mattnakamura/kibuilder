"""Project-wide logging setup."""

from __future__ import annotations

import logging
import sys


def setup(verbose: bool = False):
    """Configure root logging. Call once at app entry."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # PIL/matplotlib/OCC chatter is never useful for our debugging
    for name in ("PIL", "matplotlib", "OCC"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
