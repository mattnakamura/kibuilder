"""Interactive orientation editor for STEP files.

Loads a kibuilder YAML config, lets you pick a component, tweak Rx/Ry/Rz
with sliders / 90° flip buttons, see a live V3d preview, and save back
to the config.

Run:
    kibuilder orient path/to/kibuilder.yaml
    kibuilder orient path/to/kibuilder.yaml --part JST_PH
    kibuilder orient path/to/file.step   # ad-hoc, no config
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kibuilder import config as kbcfg
from kibuilder.render.part import RenderOptions, render_step


class OrientWindow(QMainWindow):
    """Standalone orient window. Emits `saved` with the component key on save."""

    saved = pyqtSignal(str)  # emits component key when the user saves

    def __init__(self, cfg: kbcfg.Config | None, step_path: Path | None,
                 selected_key: str | None = None, parent=None):
        # No parent → independent top-level window; closing it can't cascade to the caller.
        super().__init__()
        self.setWindowTitle("kibuilder — orient")
        self.resize(1280, 800)

        self._cfg = cfg
        self._step_override = step_path
        self._tmp = Path(tempfile.mkdtemp(prefix="kibuilder_orient_"))

        # --- Layout ----------------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # Preview
        self.preview = QLabel("(no render yet)")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(800, 600)
        self.preview.setStyleSheet(
            "background: #f4f4f4; border: 1px solid #ddd;"
        )
        layout.addWidget(self.preview, 3)

        # Controls
        ctrls = QVBoxLayout()
        layout.addLayout(ctrls, 1)

        ctrls.addWidget(QLabel("Component"))
        self.combo = QComboBox()
        if cfg:
            for key in cfg.components:
                self.combo.addItem(key)
            if selected_key and selected_key in cfg.components:
                self.combo.setCurrentText(selected_key)
        else:
            self.combo.addItem(step_path.stem if step_path else "(none)")
            self.combo.setEnabled(False)
        self.combo.currentTextChanged.connect(self._on_component_changed)
        ctrls.addWidget(self.combo)

        self.sliders: dict[str, tuple[QSlider, QSpinBox]] = {}
        for axis in ("rot_x", "rot_y", "rot_z"):
            ctrls.addWidget(QLabel(axis))
            row = QHBoxLayout()
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(-180, 180)
            sl.setSingleStep(1)
            sl.setTickPosition(QSlider.TickPosition.TicksBelow)
            sl.setTickInterval(45)
            sp = QSpinBox()
            sp.setRange(-180, 180)
            sp.setSuffix("°")
            sl.valueChanged.connect(sp.setValue)
            sp.valueChanged.connect(sl.setValue)
            sl.valueChanged.connect(self._schedule_render)
            row.addWidget(sl, 1)
            row.addWidget(sp)
            ctrls.addLayout(row)
            self.sliders[axis] = (sl, sp)

        # Quick flip buttons
        flips = QHBoxLayout()
        for label, axis in (("±X 90°", "rot_x"), ("±Y 90°", "rot_y"),
                            ("±Z 90°", "rot_z")):
            b = QPushButton(label)
            b.clicked.connect(lambda _, a=axis: self._flip(a, 90))
            flips.addWidget(b)
        ctrls.addLayout(flips)

        zero = QPushButton("Reset to 0/0/0")
        zero.clicked.connect(self._reset)
        ctrls.addWidget(zero)

        save = QPushButton("Save to config")
        save.setEnabled(cfg is not None)
        save.clicked.connect(self._save)
        ctrls.addWidget(save)

        ctrls.addStretch(1)

        self.status = QLabel("")
        ctrls.addWidget(self.status)

        # --- Render debounce timer -----------------------------------
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(150)
        self._render_timer.timeout.connect(self._render_now)

        self._on_component_changed(self.combo.currentText())

    # ------------------------------------------------------------------
    def _current_step(self) -> Path | None:
        if self._cfg and self.combo.currentText() in self._cfg.components:
            comp = self._cfg.components[self.combo.currentText()]
            try:
                return kbcfg.resolve_step(self._cfg, comp)
            except FileNotFoundError as e:
                self.status.setText(str(e))
                return None
        return self._step_override

    def _on_component_changed(self, _key: str):
        rx = ry = rz = 0.0
        if self._cfg and self.combo.currentText() in self._cfg.components:
            comp = self._cfg.components[self.combo.currentText()]
            rx, ry, rz = comp.rot_x, comp.rot_y, comp.rot_z
        for axis, val in (("rot_x", rx), ("rot_y", ry), ("rot_z", rz)):
            sl, sp = self.sliders[axis]
            sl.blockSignals(True); sp.blockSignals(True)
            sl.setValue(int(val)); sp.setValue(int(val))
            sl.blockSignals(False); sp.blockSignals(False)
        self._render_now()

    def _schedule_render(self):
        self._render_timer.start()

    def _flip(self, axis: str, step: int):
        sl, sp = self.sliders[axis]
        sl.setValue(((sl.value() + step + 180) % 360) - 180)

    def _reset(self):
        for axis in self.sliders:
            sl, sp = self.sliders[axis]
            sl.setValue(0)

    def _save(self):
        if not self._cfg:
            return
        key = self.combo.currentText()
        comp = self._cfg.components.get(key)
        if not comp:
            return
        comp.rot_x = float(self.sliders["rot_x"][0].value())
        comp.rot_y = float(self.sliders["rot_y"][0].value())
        comp.rot_z = float(self.sliders["rot_z"][0].value())
        path = kbcfg.save(self._cfg)
        self.status.setText(f"saved {key} → {path}")
        # Emit BEFORE closing so the project window can refresh + raise itself
        # while this window is still alive (avoids destruction-time races).
        import logging
        logging.getLogger("kibuilder.orient").debug("emit saved(%s) → close", key)
        self.saved.emit(key)
        QTimer.singleShot(150, self.close)

    def _render_now(self):
        step = self._current_step()
        if not step or not step.exists():
            self.preview.setText("(STEP not found)")
            return
        rx = float(self.sliders["rot_x"][0].value())
        ry = float(self.sliders["rot_y"][0].value())
        rz = float(self.sliders["rot_z"][0].value())
        out = self._tmp / "preview.png"
        try:
            render_step(
                step,
                out,
                RenderOptions(
                    width=900, height=700,
                    supersample=1,           # speed > polish for live preview
                    margin=0.20,
                    rot_x_deg=rx, rot_y_deg=ry, rot_z_deg=rz,
                ),
            )
            self.preview.setPixmap(
                QPixmap(str(out)).scaled(
                    self.preview.width(), self.preview.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.status.setText(f"{step.name}   rx={rx:.0f} ry={ry:.0f} rz={rz:.0f}")
        except Exception as e:
            self.preview.setText(f"render error:\n{e}")


def run(target: str, part: str | None = None):
    """CLI entry. `target` is either a YAML config or a .step file."""
    app = QApplication.instance() or QApplication(sys.argv)

    p = Path(target)
    cfg = None
    step_override = None
    if p.suffix.lower() in (".yaml", ".yml"):
        cfg = kbcfg.load(p)
    elif p.suffix.lower() in (".step", ".stp"):
        step_override = p
    else:
        # last-resort: try yaml first, then assume it's a path to a step file
        try:
            cfg = kbcfg.load(p)
        except Exception:
            step_override = p

    win = OrientWindow(cfg, step_override, selected_key=part)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("target", help="kibuilder.yaml or a .step file")
    p.add_argument("--part", help="component key to focus")
    args = p.parse_args()
    run(args.target, args.part)
