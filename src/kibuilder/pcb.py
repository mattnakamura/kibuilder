"""Parse a .kicad_pcb file and extract footprints + 3D-model references.

KiCAD's .kicad_pcb is an S-expression text format. We don't do a full
parse — just walk top-level (1-tab indented) `(footprint ...)` blocks and
pick the bits we need (reference designator, lib id, position, model paths).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Footprint:
    ref: str = ""
    lib_id: str = ""           # e.g. "Connector_JST:JST_PH_B4B-PH-SM4-TB..."
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)  # mm, mm, deg
    models: list[str] = field(default_factory=list)  # raw STEP paths from (model "...")


@dataclass
class PCBSummary:
    path: Path
    footprints: list[Footprint] = field(default_factory=list)

    def by_model(self) -> dict[str, list[Footprint]]:
        """Group footprints by every model path basename they reference.

        Footprints with multiple (model …) blocks contribute to each model's
        bucket — e.g. a DIP socket footprint that embeds the chip's STEP
        registers under both names.
        """
        out: dict[str, list[Footprint]] = {}
        for fp in self.footprints:
            if not fp.models:
                out.setdefault("(no 3D model)", []).append(fp)
                continue
            for m in fp.models:
                key = Path(_strip_vars(m)).name
                out.setdefault(key, []).append(fp)
        return out


_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def _strip_vars(p: str) -> str:
    """Strip leading env-var references like ${KIPRJMOD}/ to keep the tail path."""
    s = _VAR_RE.sub("", p)
    return s.lstrip("/").lstrip("\\")


def resolve_model(raw: str, project_root: Path,
                  extra_search: list[Path] | None = None) -> Path | None:
    """Resolve a (model "...") string to an absolute STEP path.

    Handles ${KIPRJMOD}, ${KICAD*_3DMODEL_DIR}, and bare relative paths.
    """
    p = raw
    p = p.replace("${KIPRJMOD}", str(project_root))
    p = re.sub(r"\$\{KICAD\d*_3DMODEL_DIR\}",
               "/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels",
               p)
    p = os.path.expandvars(p)
    cand = Path(p)
    if cand.is_absolute() and cand.exists():
        return cand
    # Try project root + extras
    bases = [project_root]
    if extra_search:
        bases.extend(extra_search)
    for b in bases:
        c = b / p.lstrip("/")
        if c.exists():
            return c
    return None


def parse(pcb_path: str | Path) -> PCBSummary:
    """Walk the .kicad_pcb, return a PCBSummary."""
    pcb_path = Path(pcb_path)
    text = pcb_path.read_text(errors="replace").splitlines()

    out = PCBSummary(path=pcb_path)
    i = 0
    n = len(text)
    while i < n:
        line = text[i]
        m = re.match(r'^\t\(footprint\s+"([^"]+)"', line)
        if not m:
            i += 1
            continue
        fp = Footprint(lib_id=m.group(1))
        depth = line.count("(") - line.count(")")
        i += 1
        seen_at = False
        while depth > 0 and i < n:
            l = text[i]
            depth += l.count("(") - l.count(")")
            # footprint position (the FIRST (at X Y [ROT]) at 2-tab indent
            if not seen_at:
                am = re.match(r"^\t\t\(at\s+([-\d.]+)\s+([-\d.]+)(?:\s+([-\d.]+))?\)", l)
                if am:
                    x = float(am.group(1)); y = float(am.group(2))
                    r = float(am.group(3)) if am.group(3) else 0.0
                    fp.position = (x, y, r)
                    seen_at = True
            # reference
            if not fp.ref:
                rm = re.search(r'\(property "Reference" "([^"]+)"', l)
                if rm:
                    fp.ref = rm.group(1)
            # model paths
            mm = re.search(r'\(model\s+"([^"]+)"', l)
            if mm:
                fp.models.append(mm.group(1))
            i += 1
        out.footprints.append(fp)
    return out


def suggest_component_key(model_path: str) -> str:
    """Make a tidy snake-ish key from a STEP path basename."""
    name = Path(_strip_vars(model_path)).stem
    # strip common suffixes
    name = re.sub(r"_P[\d.]+mm.*$", "", name)
    name = re.sub(r"_Handsoldering$", "", name)
    name = name.replace(" ", "_")
    return name
