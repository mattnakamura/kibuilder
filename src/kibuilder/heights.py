"""Measure component heights from STEP files and group them into stages.

Heights are derived from the Z-extent of each STEP's geometric bounding box
via OpenCASCADE. Components with similar heights are clustered into one
assembly stage. The output preserves bare-PCB as stage 1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.STEPControl import STEPControl_Reader
from OCP.gp import gp_Trsf, gp_Ax1, gp_Pnt, gp_Dir
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
import math

from kibuilder import config as kbcfg

log = logging.getLogger("kibuilder.heights")


def _rotation_trsf(rx: float, ry: float, rz: float):
    if not (rx or ry or rz):
        return None
    combined = gp_Trsf()
    for deg, d in ((rz, gp_Dir(0, 0, 1)),
                   (ry, gp_Dir(0, 1, 0)),
                   (rx, gp_Dir(1, 0, 0))):
        if deg:
            t = gp_Trsf()
            t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), d), math.radians(deg))
            combined.Multiply(t)
    return combined


def measure_step_extents(step_path: Path,
                         rot_x: float = 0, rot_y: float = 0, rot_z: float = 0,
                         ) -> tuple[float, float, float] | None:
    """Return (x_extent, y_extent, z_extent) of a STEP's bounding box, in mm.

    Applies the same Rx/Ry/Rz rotation the renderer would, so the extents
    reflect the part's intended on-PCB orientation.
    """
    step_path = Path(step_path)
    reader = STEPControl_Reader()
    if not reader.ReadFile(str(step_path)):
        return None
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        return None
    trsf = _rotation_trsf(rot_x, rot_y, rot_z)
    if trsf is not None:
        shape = BRepBuilderAPI_Transform(shape, trsf, True).Shape()

    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    if bbox.IsVoid():
        return None
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    return float(xmax - xmin), float(ymax - ymin), float(zmax - zmin)


def measure_step_height(step_path: Path,
                        rot_x: float = 0, rot_y: float = 0, rot_z: float = 0,
                        ) -> float | None:
    """Return the Z-extent (mm) of a STEP file's bounding box."""
    extents = measure_step_extents(step_path, rot_x, rot_y, rot_z)
    return extents[2] if extents else None


def is_daughterboard(extents: tuple[float, float, float],
                     min_footprint_mm: float = 15.0,
                     max_z_ratio: float = 0.5) -> bool:
    """Heuristic: a part is a daughterboard if its geometry is plate-like.

    Both XY dimensions must exceed `min_footprint_mm`, and Z must be small
    compared to the smaller footprint dimension. This catches breakout
    boards (Feather, MCP23017 breakout, etc.) and rejects narrow strips
    (pin headers) and small ICs (DIPs, SOTs).
    """
    xe, ye, ze = extents
    min_xy = min(xe, ye)
    if min_xy < min_footprint_mm:
        return False
    return ze < min_xy * max_z_ratio


@dataclass
class _Measured:
    key: str
    height: float


def measure_all(cfg: kbcfg.Config) -> dict[str, tuple[float, float, float]]:
    """Measure XYZ extents for every component in the config.

    Missing STEPs are skipped (with a log warning).
    """
    extents: dict[str, tuple[float, float, float]] = {}
    for key, comp in cfg.components.items():
        try:
            step = kbcfg.resolve_step(cfg, comp)
        except FileNotFoundError:
            log.warning("STEP missing for %s: %s", key, comp.step)
            continue
        try:
            e = measure_step_extents(step, comp.rot_x, comp.rot_y, comp.rot_z)
        except Exception:
            log.exception("extent measurement failed for %s", key)
            continue
        if e is None:
            continue
        extents[key] = e
        log.debug("extents %-22s = %5.1f × %5.1f × %5.2f mm",
                  key, e[0], e[1], e[2])
    return extents


def auto_stages_by_height(cfg: kbcfg.Config,
                          threshold_mm: float = 3.0,
                          keep_bare_pcb: bool = True) -> list[kbcfg.StageSpec]:
    """Build stages from components grouped by ascending height.

    Daughterboards (plate-like parts: large XY, modest Z) are pulled out
    into a final stage regardless of measured height, since they actually
    sit on top of their pin headers in the finished assembly.
    """
    extents = measure_all(cfg)

    boards: list[str] = []
    parts: list[_Measured] = []
    for key, e in extents.items():
        if is_daughterboard(e):
            boards.append(key)
            log.debug("classified %s as daughterboard "
                      "(%.1f × %.1f × %.2f mm)", key, *e)
        else:
            parts.append(_Measured(key, e[2]))

    parts.sort(key=lambda m: m.height)
    missing = [k for k in cfg.components if k not in extents]

    clusters: list[list[_Measured]] = []
    for m in parts:
        if not clusters or m.height - clusters[-1][-1].height > threshold_mm:
            clusters.append([m])
        else:
            clusters[-1].append(m)

    stages: list[kbcfg.StageSpec] = []
    n = 1
    if keep_bare_pcb:
        stages.append(kbcfg.StageSpec(
            n=n, title="Bare PCB",
            sub="Inspect: no shorts, silkscreen legible.",
            parts=[]))
        n += 1

    for cluster in clusters:
        keys = [m.key for m in cluster]
        avg_h = sum(m.height for m in cluster) / len(cluster)
        title = _label_for_cluster(avg_h)
        stages.append(kbcfg.StageSpec(
            n=n, title=title,
            sub=f"~{avg_h:.1f} mm tall:  " + " · ".join(keys),
            parts=[kbcfg.StagePart(key=k, qty=1, label=k) for k in keys],
        ))
        n += 1

    if boards:
        stages.append(kbcfg.StageSpec(
            n=n, title="Daughterboards",
            sub="Seat boards onto their headers last:  " + " · ".join(boards),
            parts=[kbcfg.StagePart(key=k, qty=1, label=k) for k in boards],
        ))
        n += 1

    if missing:
        stages.append(kbcfg.StageSpec(
            n=n, title="Other parts",
            sub="Components with no measurable STEP geometry.",
            parts=[kbcfg.StagePart(key=k, qty=1, label=k) for k in missing],
        ))

    return stages


def _label_for_cluster(avg_h: float) -> str:
    """Friendly stage title based on the height bucket."""
    if avg_h < 2.0:
        return "SMD parts"
    if avg_h < 4.5:
        return "Low-profile through-hole"
    if avg_h < 9.0:
        return "Sockets & pin headers"
    if avg_h < 14.0:
        return "Inductors & small caps"
    if avg_h < 20.0:
        return "Large capacitors / connectors"
    return "Tallest parts"
