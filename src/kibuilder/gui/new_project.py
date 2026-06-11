"""Bootstrap a new kibuilder config from a .kicad_pcb."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from kibuilder import config as kbcfg
from kibuilder.pcb import parse, suggest_component_key, _strip_vars


def sync_components_from_pcb(cfg: kbcfg.Config) -> list[str]:
    """Re-walk the PCB and add any components missing from `cfg`.

    Returns the list of newly added component keys. Existing entries
    (including their rot_x/y/z) are left untouched.
    """
    if cfg.source_path is None:
        raise ValueError("config has no source_path")
    pcb_path = (cfg.source_path.parent / cfg.project.pcb).resolve()
    if not pcb_path.exists():
        # try absolute interpretation of project.pcb
        pcb_path = Path(cfg.project.pcb)
        if not pcb_path.exists():
            raise FileNotFoundError(f"PCB not found: {cfg.project.pcb}")

    summary = parse(pcb_path)
    added: list[str] = []
    for fp in summary.footprints:
        for model in fp.models:
            key = suggest_component_key(model)
            if key in cfg.components:
                continue
            cfg.components[key] = kbcfg.ComponentSpec(step=_strip_vars(model))
            added.append(key)
    return added


def new_project_from_pcb(pcb_path: Path, parent: QWidget | None = None) -> Path | None:
    """Parse the .kicad_pcb, build a default config, ask the user where to save it.

    Returns the saved YAML path, or None if cancelled.
    """
    summary = parse(pcb_path)

    # Build component entries: one per unique STEP model basename.
    # NB: a single footprint can carry several (model …) blocks — KiCad uses
    # this to embed e.g. a DIP chip into its socket footprint, or stacking
    # sockets into a Feather footprint. We must register every model, not
    # just the first one, or the cumulative-board renderer can't hide them.
    components: dict[str, kbcfg.ComponentSpec] = {}
    for fp in summary.footprints:
        for model in fp.models:
            stripped = _strip_vars(model)
            key = suggest_component_key(model)
            if key not in components:
                components[key] = kbcfg.ComponentSpec(step=stripped)

    # One "Assembly" stage with everything in it; user can split it up later.
    parts = [
        kbcfg.StagePart(key=key, qty=1, label=key)
        for key in components
    ]
    stages = [
        kbcfg.StageSpec(n=1, title="Bare PCB", sub="Inspect.", parts=[]),
        kbcfg.StageSpec(n=2, title="Assembly",
                        sub="All parts (re-organise into stages)",
                        parts=parts),
    ]

    project = kbcfg.ProjectSpec(
        pcb=str(pcb_path),
        output="media/assembly",
        step_search_paths=[
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels",
            str(pcb_path.parent / "footprints"),
        ],
    )
    cfg = kbcfg.Config(project=project, components=components, stages=stages)

    default_name = pcb_path.with_suffix(".kibuilder.yaml").name
    out, _ = QFileDialog.getSaveFileName(
        parent, "Save kibuilder config",
        str(pcb_path.parent / default_name),
        "kibuilder YAML (*.yaml)",
    )
    if not out:
        return None
    cfg.source_path = Path(out)
    saved = kbcfg.save(cfg, out)
    QMessageBox.information(
        parent, "Project created",
        f"Created {saved.name} with {len(components)} components.",
    )
    return saved
