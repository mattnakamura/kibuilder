"""Render STEP files via OpenCASCADE V3d.

Uses XCAFPrs_AISObject so the assembly hierarchy and per-face XCAF colors
are honoured (matches KiCAD's STEP renderer). Output is a transparent-bg
PNG produced by chroma-keying a magenta background, with optional
supersampling for crisper edges.

The expensive bits (NSApplication, OpenGL driver, V3d viewer, off-screen
Cocoa window) are created once and reused across renders via the
``Renderer`` class. The module-level ``render_step`` helper keeps the
old one-shot signature for callers that don't care.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtWidgets import QApplication

from OCP.AIS import AIS_InteractiveContext
from OCP.Aspect import Aspect_DisplayConnection
from OCP.Image import Image_AlienPixMap
from OCP.OpenGl import OpenGl_GraphicDriver
from OCP.Quantity import Quantity_Color, Quantity_TypeOfColor
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDF import TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.V3d import V3d_TypeOfOrientation, V3d_Viewer
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.XCAFPrs import XCAFPrs_AISObject
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf

# Platform-specific V3d window backend.
# macOS uses Cocoa_Window (NSWindow); Linux uses Xw_Window (Xlib);
# Windows would use WNT_Window. OCP only ships the backend matching the
# host OS, so we import lazily.
if sys.platform == "darwin":
    from OCP.Cocoa import Cocoa_Window as _NativeWindow
elif sys.platform.startswith("linux"):
    from OCP.Xw import Xw_Window as _NativeWindow
else:
    from OCP.WNT import WNT_Window as _NativeWindow  # type: ignore[no-redef]

# Bootstrap a Qt app on import so NSApplication exists for Cocoa_Window
# (macOS) and a Qt event loop exists at module-level for callers.
_QAPP = QApplication.instance() or QApplication(sys.argv)


@dataclass
class RenderOptions:
    """Options for a single render call."""

    width: int = 1400
    height: int = 1050
    margin: float = 0.18
    supersample: int = 2
    transparent: bool = True
    bg: tuple[float, float, float] = (1.0, 0.0, 1.0)  # magenta key colour
    rot_x_deg: float = 0.0
    rot_y_deg: float = 0.0
    rot_z_deg: float = 0.0
    deviation_coefficient: float = 0.0005
    deviation_angle: float = 0.10
    msaa_samples: int = 16


def _qcolor(rgb: tuple[float, float, float]) -> Quantity_Color:
    return Quantity_Color(rgb[0], rgb[1], rgb[2],
                          Quantity_TypeOfColor.Quantity_TOC_RGB)


def _rotation_trsf(rx: float, ry: float, rz: float) -> gp_Trsf | None:
    if not (rx or ry or rz):
        return None
    combined = gp_Trsf()
    for axis_deg, axis_dir in [
        (rz, gp_Dir(0, 0, 1)),
        (ry, gp_Dir(0, 1, 0)),
        (rx, gp_Dir(1, 0, 0)),
    ]:
        if axis_deg:
            t = gp_Trsf()
            t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), axis_dir),
                          math.radians(axis_deg))
            combined.Multiply(t)
    return combined


class Renderer:
    """A reusable V3d viewer that can render many STEPs in a session.

    Constructing this opens one (off-screen, far-away) Cocoa window which
    is reused for every render. Drop a single instance into long-running
    callers (the orient GUI, batch renderers) so we don't keep popping
    a fresh OS window per render.
    """

    def __init__(self, bg: tuple[float, float, float] = (1.0, 0.0, 1.0),
                 msaa_samples: int = 16,
                 # Tiny window: ToPixMap renders at its own buffer size, not
                 # the window's, so the OS window can be vanishingly small.
                 window_size: tuple[int, int] = (32, 32)):
        self._bg = bg
        self._display = Aspect_DisplayConnection()
        self._driver = OpenGl_GraphicDriver(self._display)

        self._viewer = V3d_Viewer(self._driver)
        self._viewer.SetDefaultLights()
        self._viewer.SetLightOn()
        self._viewer.SetDefaultBackgroundColor(_qcolor(bg))

        self._context = AIS_InteractiveContext(self._viewer)
        self._context.SetDisplayMode(1, False)  # shaded

        self._view = self._viewer.CreateView()
        self._view.SetBackgroundColor(_qcolor(bg))

        rp = self._view.ChangeRenderingParams()
        rp.NbMsaaSamples = msaa_samples
        rp.IsAntialiasingEnabled = True

        # Snapshot existing NSWindows so we can identify ours after creation
        # and hide ONLY the one we own (not Qt windows like the project/orient).
        # macOS only — Linux/Xw doesn't share a global window list with Qt.
        _windows_before: set = set()
        if sys.platform == "darwin":
            try:
                from Cocoa import NSApp  # type: ignore
                _windows_before = set(NSApp.windows()) if NSApp is not None else set()
            except Exception:
                pass

        # One small, far-off-screen native window for the lifetime of this
        # Renderer. The Cocoa_Window (macOS), Xw_Window (Linux), and
        # WNT_Window (Windows) constructors all take title + x,y,w,h.
        # Empty title so it doesn't show up in the host's task switcher
        # if it briefly appears.
        if sys.platform == "darwin":
            self._win = _NativeWindow("", -32000, -32000,
                                      window_size[0], window_size[1])
        elif sys.platform == "win32":
            # WNT_Window needs a registered window class. WS_POPUP
            # (0x80000000) gives a bare, decoration-free window we park
            # far off-screen. (Experimental — verified via CI only.)
            from OCP.WNT import WNT_WClass
            self._wclass = WNT_WClass("kibuilder_v3d", None, 0)
            self._win = _NativeWindow("kibuilder", self._wclass,
                                      0x80000000,
                                      -32000, -32000,
                                      window_size[0], window_size[1])
        else:
            # Xw_Window takes the X display connection as first arg.
            self._win = _NativeWindow(self._display, "kibuilder",
                                      -32000, -32000,
                                      window_size[0], window_size[1])
        self._win.Map()
        try:
            self._win.SetVirtual(True)
        except Exception:
            pass
        self._view.SetWindow(self._win)
        self._view.MustBeResized()
        _QAPP.processEvents()

        # macOS clamps off-screen windows back onto a visible display, so we
        # explicitly order out *only the new NSWindow(s)* that appeared after
        # our Cocoa_Window was created. NSApp.windows() also contains Qt's
        # windows (splash/project/orient), which we must NOT touch.
        # Linux's Xw_Window already honors negative coordinates.
        if sys.platform == "darwin":
            try:
                from Cocoa import NSApp  # type: ignore
                for w in NSApp.windows():
                    if w in _windows_before:
                        continue
                    w.setAlphaValue_(0.0)
                    w.orderOut_(None)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def render(self, step_path: Path, out_path: Path,
               opts: RenderOptions | None = None) -> bool:
        opts = opts or RenderOptions()
        step_path = Path(step_path)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove anything previously displayed so STEPs don't accumulate.
        self._context.RemoveAll(False)

        # Load STEP with XCAF
        doc = TDocStd_Document(TCollection_ExtendedString("part"))
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        if not reader.ReadFile(str(step_path)):
            raise RuntimeError(f"Could not read STEP: {step_path}")
        reader.Transfer(doc)

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

        user_trsf = _rotation_trsf(opts.rot_x_deg, opts.rot_y_deg, opts.rot_z_deg)

        free = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free)
        for i in range(1, free.Length() + 1):
            ais = XCAFPrs_AISObject(free.Value(i))
            ais.SetDisplayMode(1)
            ais.SetOwnDeviationCoefficient(opts.deviation_coefficient)
            ais.SetOwnDeviationAngle(opts.deviation_angle)
            if user_trsf is not None:
                ais.SetLocalTransformation(user_trsf)
            self._context.Display(ais, False)

        self._view.SetProj(V3d_TypeOfOrientation.V3d_XposYnegZpos)
        self._view.FitAll(opts.margin)
        self._view.ZFitAll()

        ss_w = opts.width * opts.supersample
        ss_h = opts.height * opts.supersample
        pix = Image_AlienPixMap()
        if not self._view.ToPixMap(pix, ss_w, ss_h):
            raise RuntimeError("ToPixMap failed")

        tmp_png = str(out_path) + ".tmp.png"
        pix.Save(TCollection_AsciiString(tmp_png))

        im = Image.open(tmp_png).convert("RGBA")
        if opts.transparent:
            arr = np.array(im)
            key = np.array(
                [int(opts.bg[0] * 255), int(opts.bg[1] * 255),
                 int(opts.bg[2] * 255)]
            )
            diff = np.abs(arr[..., :3].astype(int) - key).max(axis=-1)
            arr[diff <= 12] = (255, 255, 255, 0)
            im = Image.fromarray(arr, "RGBA")

        if opts.supersample > 1 and im.size != (opts.width, opts.height):
            im = im.resize((opts.width, opts.height), Image.LANCZOS)

        im.save(str(out_path))
        Path(tmp_png).unlink(missing_ok=True)
        return True


# Module-level convenience: lazy shared Renderer for one-shot callers.
_shared_renderer: Renderer | None = None


def get_shared_renderer() -> Renderer:
    global _shared_renderer
    if _shared_renderer is None:
        _shared_renderer = Renderer()
    return _shared_renderer


def render_step(step_path: Path, out_path: Path,
                opts: RenderOptions | None = None) -> bool:
    """One-shot render using the module-shared Renderer (window stays alive)."""
    return get_shared_renderer().render(step_path, out_path, opts)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Render a STEP via OCC V3d.")
    p.add_argument("step")
    p.add_argument("out")
    p.add_argument("--rx", type=float, default=0)
    p.add_argument("--ry", type=float, default=0)
    p.add_argument("--rz", type=float, default=0)
    args = p.parse_args()
    ok = render_step(
        Path(args.step), Path(args.out),
        RenderOptions(rot_x_deg=args.rx, rot_y_deg=args.ry, rot_z_deg=args.rz),
    )
    print("OK" if ok else "FAIL", "->", args.out)
