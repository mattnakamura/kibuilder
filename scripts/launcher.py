"""PyInstaller entry point for the kibuilder.app bundle.

When users double-click the bundled .app, macOS launches this script with
no arguments. We default to the GUI rather than printing CLI help.

This file is *only* the bundle entry point; the regular `kibuilder` console
script in pyproject.toml still points at `kibuilder.cli:main`.
"""

import sys


def main():
    # Force the GUI subcommand if launched with no args (double-click).
    if len(sys.argv) == 1:
        sys.argv.append("gui")
    from kibuilder.cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
