"""kibuilder CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_orient(args):
    from kibuilder.gui.orient import run
    run(args.target, args.part)


def cmd_render_parts(args):
    from kibuilder import config as kbcfg
    from kibuilder.render.part import RenderOptions, render_step

    cfg = kbcfg.load(args.config)
    out_root = Path(cfg.source_path).parent / cfg.project.output / "_components"
    out_root.mkdir(parents=True, exist_ok=True)

    only = set(args.only) if args.only else None
    for key, comp in cfg.components.items():
        if only and key not in only:
            continue
        out = out_root / f"{key}.png"
        if out.exists() and not args.force:
            print(f"  cache hit {key}")
            continue
        try:
            step = kbcfg.resolve_step(cfg, comp)
        except FileNotFoundError as e:
            print(f"  MISSING {key}: {e}")
            continue
        print(f"  rendering {key}  ({step.name})")
        ok = render_step(step, out, RenderOptions(
            rot_x_deg=comp.rot_x,
            rot_y_deg=comp.rot_y,
            rot_z_deg=comp.rot_z,
        ))
        print(f"    {'OK' if ok else 'FAIL'} → {out.name}")


def cmd_gui(args):
    from kibuilder.gui.splash import run
    run()


def _setup_logging(args):
    from kibuilder.log import setup
    setup(verbose=getattr(args, "verbose", False))


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="kibuilder",
        description="Generate visual step-by-step assembly guides from a KiCAD PCB.",
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print debug-level logs to stderr")
    sp = parser.add_subparsers(dest="cmd")

    p = sp.add_parser("gui", help="Launch the kibuilder splash / project window.")
    p.set_defaults(fn=cmd_gui)

    p = sp.add_parser("orient", help="Interactively tune component orientation.")
    p.add_argument("target", help="kibuilder.yaml or a .step file")
    p.add_argument("--part", help="component key to focus on initially")
    p.set_defaults(fn=cmd_orient)

    p = sp.add_parser("render-parts", help="Render each component STEP via V3d.")
    p.add_argument("config", help="kibuilder.yaml")
    p.add_argument("--only", nargs="*", help="component keys to render (default: all)")
    p.add_argument("--force", action="store_true", help="re-render even if cached")
    p.set_defaults(fn=cmd_render_parts)

    args = parser.parse_args(argv)
    _setup_logging(args)
    if not args.cmd:
        # Default: launch the GUI.
        cmd_gui(args)
        return
    args.fn(args)


if __name__ == "__main__":
    main()
