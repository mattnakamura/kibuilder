"""YAML config loader/saver for kibuilder.

Schema (rough):

    project:
      pcb: path/to/board.kicad_pcb
      step_search_paths: ["/Applications/KiCad/.../3dmodels", "./footprints"]
      output: media/assembly

    components:
      JST_PH:
        step: 3dmodels/JST_B4B-PH-SM4-TB.step
        rot_x: 90
        rot_y: 0
        rot_z: 0
      BANANA_RED:
        step: 3dmodels/Banana_Cliff_red.step

    stages:
      - n: 2
        title: SMD parts
        sub: D1 · U6 · J5
        parts:
          - { key: D_SMA, qty: 1, label: "D1 · Schottky" }
          - { key: SOT235, qty: 1, label: "U6 · LMR62421" }
          - { key: JST_PH, qty: 1, label: "J5 · JST PH" }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ComponentSpec:
    step: str
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0


@dataclass
class StagePart:
    key: str
    qty: int = 1
    label: str = ""


@dataclass
class StageSpec:
    n: int
    title: str
    sub: str = ""
    parts: list[StagePart] = field(default_factory=list)


@dataclass
class ProjectSpec:
    pcb: str = ""
    output: str = "media/assembly"
    step_search_paths: list[str] = field(default_factory=list)


@dataclass
class Config:
    project: ProjectSpec
    components: dict[str, ComponentSpec]
    stages: list[StageSpec]
    source_path: Path | None = None


def load(path: str | Path) -> Config:
    path = Path(path)
    with path.open("r") as f:
        data = yaml.safe_load(f) or {}
    proj_d = data.get("project", {}) or {}
    project = ProjectSpec(
        pcb=proj_d.get("pcb", ""),
        output=proj_d.get("output", "media/assembly"),
        step_search_paths=list(proj_d.get("step_search_paths", []) or []),
    )
    components = {}
    for key, comp in (data.get("components", {}) or {}).items():
        comp = comp or {}
        components[key] = ComponentSpec(
            step=comp.get("step", ""),
            rot_x=float(comp.get("rot_x", 0)),
            rot_y=float(comp.get("rot_y", 0)),
            rot_z=float(comp.get("rot_z", 0)),
        )
    stages = []
    for s in data.get("stages", []) or []:
        s = s or {}
        parts = [
            StagePart(
                key=p.get("key", ""),
                qty=int(p.get("qty", 1)),
                label=str(p.get("label", "")),
            )
            for p in (s.get("parts", []) or [])
        ]
        stages.append(
            StageSpec(
                n=int(s.get("n", 0)),
                title=str(s.get("title", "")),
                sub=str(s.get("sub", "")),
                parts=parts,
            )
        )
    cfg = Config(project=project, components=components, stages=stages,
                 source_path=path)
    return cfg


def save(cfg: Config, path: str | Path | None = None) -> Path:
    """Write the config back to YAML. Uses cfg.source_path if path is None."""
    target = Path(path or cfg.source_path or "kibuilder.yaml")
    out: dict[str, Any] = {
        "project": {
            "pcb": cfg.project.pcb,
            "output": cfg.project.output,
            "step_search_paths": list(cfg.project.step_search_paths),
        },
        "components": {
            k: {
                "step": v.step,
                "rot_x": v.rot_x,
                "rot_y": v.rot_y,
                "rot_z": v.rot_z,
            }
            for k, v in cfg.components.items()
        },
        "stages": [
            {
                "n": s.n,
                "title": s.title,
                "sub": s.sub,
                "parts": [
                    {"key": p.key, "qty": p.qty, "label": p.label}
                    for p in s.parts
                ],
            }
            for s in cfg.stages
        ],
    }
    with target.open("w") as f:
        yaml.safe_dump(out, f, sort_keys=False, default_flow_style=False)
    return target


def resolve_step(cfg: Config, comp: ComponentSpec) -> Path:
    """Find a STEP file using the config's search paths."""
    bases: list[Path] = []
    if cfg.source_path:
        bases.append(cfg.source_path.parent)
    for sp in cfg.project.step_search_paths:
        p = Path(sp).expanduser()
        if not p.is_absolute() and cfg.source_path:
            p = cfg.source_path.parent / p
        bases.append(p)
    candidates = [Path(comp.step)]
    if not Path(comp.step).is_absolute():
        for b in bases:
            candidates.append(b / comp.step)
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"STEP not found: {comp.step}")
