"""Cumulative board renderer using `kicad-cli pcb render`.

For each assembly stage N, produce a board image with only components from
stages 1..N populated. Other components have their model references rewritten
to a non-existent path in a temp PCB copy so kicad-cli silently skips them.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from kibuilder import config as kbcfg

log = logging.getLogger("kibuilder.board")


def purge_temp_files(project_dir: Path) -> list[Path]:
    """Remove tmp*.kicad_* artifacts left over from interrupted renders.

    NamedTemporaryFile leaves `tmpXXXXXX.kicad_pcb` if our finally-block
    didn't run (process killed, crash, etc.). KiCad/kicad-cli also drops
    `.kicad_prl` (local project layout) sidecars next to whatever PCB it
    touched. Both share the `tmp*` prefix when generated from our temps.

    Returns the list of paths actually deleted.
    """
    project_dir = Path(project_dir)
    deleted: list[Path] = []
    for path in project_dir.glob("tmp*.kicad_*"):
        try:
            path.unlink()
            deleted.append(path)
        except OSError as e:
            log.warning("failed to delete %s: %s", path, e)
    return deleted


def _hide_steps(pcb_src: Path, pcb_dst: Path, hide_basenames: list[str]):
    """Rewrite model-path references whose basename appears in `hide_basenames`."""
    text = pcb_src.read_text()
    for base in hide_basenames:
        esc = re.escape(base)
        for ext in ("step", "stp", "STEP", "STP", "wrl", "WRL"):
            text = re.sub(
                rf'"([^"]*?){esc}\.{ext}"',
                f'"__KIBUILDER_HIDDEN__/{base}.{ext}"',
                text,
            )
    pcb_dst.write_text(text)


def render_board(pcb_path: Path,
                 out_path: Path,
                 hide_basenames: list[str] | None = None,
                 *,
                 width: int = 1800,
                 height: int = 1350,
                 rotate: str = "-32,0,-25",
                 pivot: str | None = None,
                 zoom: float = 1.0,
                 quality: str = "high",
                 background: str = "opaque") -> bool:
    """Render one board image via kicad-cli. Returns True on success."""
    if shutil.which("kicad-cli") is None:
        raise RuntimeError(
            "kicad-cli not found on PATH — install KiCad with CLI tools."
        )
    pcb_path = Path(pcb_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Temp PCB lives next to the source so any relative project paths still
    # resolve (sym/footprint-lib-tables, .kicad_pro, etc.).
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".kicad_pcb", dir=str(pcb_path.parent),
    ) as tf:
        tmp = Path(tf.name)
    try:
        if hide_basenames:
            _hide_steps(pcb_path, tmp, hide_basenames)
        else:
            shutil.copyfile(pcb_path, tmp)
        cmd = [
            "kicad-cli", "pcb", "render",
            "--side", "top",
            "--perspective",
            "--rotate", rotate,
            "--zoom", str(zoom),
            "--quality", quality,
            "--background", background,
            "--width", str(width),
            "--height", str(height),
            "-o", str(out_path),
            str(tmp),
        ]
        if pivot:
            cmd += ["--pivot", pivot]
        log.debug("kicad-cli: %s", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            log.warning("kicad-cli rc=%d\n%s\n%s",
                        r.returncode, r.stdout, r.stderr)
            return False
        return out_path.exists()
    finally:
        tmp.unlink(missing_ok=True)


def _cumulative_keys_through(cfg: kbcfg.Config, stage_n: int) -> set[str]:
    """Component keys placed on the board up to and including stage_n."""
    cumulative: set[str] = set()
    for s in sorted(cfg.stages, key=lambda x: x.n):
        cumulative |= {p.key for p in s.parts}
        if s.n == stage_n:
            break
    return cumulative


def render_stage_board(cfg: kbcfg.Config,
                       stage_n: int,
                       out_dir: Path,
                       **render_kwargs) -> Path | None:
    """Render the cumulative board for a single stage. Returns output path or None."""
    if cfg.source_path is None:
        raise ValueError("cfg.source_path is required")
    pcb = (cfg.source_path.parent / cfg.project.pcb).resolve()
    if not pcb.exists():
        raise FileNotFoundError(f"PCB not found: {pcb}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cumulative = _cumulative_keys_through(cfg, stage_n)
    hide_keys = set(cfg.components) - cumulative
    hide_basenames = [
        Path(cfg.components[k].step).stem
        for k in hide_keys if k in cfg.components and cfg.components[k].step
    ]
    out = out_dir / f"{stage_n:02d}.jpg"
    log.info("re-rendering stage %d: %d shown, %d hidden",
             stage_n, len(cumulative), len(hide_basenames))
    return out if render_board(pcb, out, hide_basenames, **render_kwargs) else None


def render_cumulative(cfg: kbcfg.Config,
                      out_dir: Path,
                      *,
                      progress=None,
                      **render_kwargs) -> list[Path]:
    """Render one board image per stage, cumulative parts populated.

    `progress(i, total, stage)` is called once per stage if provided.
    Returns the list of successfully written output paths in stage order.
    """
    if cfg.source_path is None:
        raise ValueError("cfg.source_path is required (YAML must be loaded from disk)")
    pcb = (cfg.source_path.parent / cfg.project.pcb).resolve()
    if not pcb.exists():
        raise FileNotFoundError(f"PCB not found: {pcb}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stages = sorted(cfg.stages, key=lambda s: s.n)

    cumulative: set[str] = set()
    written: list[Path] = []
    total = len(stages)

    for i, stage in enumerate(stages, 1):
        cumulative |= {p.key for p in stage.parts}
        hide_keys = set(cfg.components) - cumulative
        hide_basenames = [
            Path(cfg.components[k].step).stem
            for k in hide_keys if k in cfg.components and cfg.components[k].step
        ]
        out = out_dir / f"{stage.n:02d}.jpg"
        log.info("board %s: %d parts shown, %d hidden",
                 out.name, len(cumulative), len(hide_basenames))
        if progress is not None:
            progress(i, total, stage)
        ok = render_board(pcb, out, hide_basenames, **render_kwargs)
        if ok:
            written.append(out)
        else:
            log.warning("board render failed for stage %d", stage.n)
    return written
