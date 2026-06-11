"""Project window — components + stages panels, orient/render actions."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

import logging
from kibuilder import config as kbcfg
from kibuilder.gui.splash import keep_alive

log = logging.getLogger("kibuilder.project")


class ProjectWindow(QMainWindow):
    """Main project workspace."""

    def __init__(self, cfg: kbcfg.Config):
        super().__init__()
        self._cfg = cfg
        self.setWindowTitle(
            f"kibuilder — {cfg.source_path.name if cfg.source_path else 'untitled'}"
        )
        self.resize(1100, 720)
        log.debug("ProjectWindow ctor (id=%s, source=%s)", id(self), cfg.source_path)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # Top: PCB info — no hardcoded colours so dark/light mode both work
        info = QLabel(f"<b>PCB:</b> {cfg.project.pcb}")
        info.setContentsMargins(6, 6, 6, 6)
        outer.addWidget(info)

        # Body: two-pane splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # --- Components panel ---
        comp_panel = QWidget()
        cl = QVBoxLayout(comp_panel)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.addWidget(QLabel(f"<b>Components</b> ({len(cfg.components)})"))
        self.comp_list = QListWidget()
        self.comp_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self.comp_list.itemDoubleClicked.connect(self._orient_selected_item)
        for key, comp in cfg.components.items():
            label = key
            if any((comp.rot_x, comp.rot_y, comp.rot_z)):
                label += f"   (rot {int(comp.rot_x)}/{int(comp.rot_y)}/{int(comp.rot_z)})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.comp_list.addItem(item)
        cl.addWidget(self.comp_list, 1)

        btns = QHBoxLayout()
        b_orient = QPushButton("Orient selected…")
        b_orient.clicked.connect(self._orient_selected)
        btns.addWidget(b_orient)
        b_add_stage = QPushButton("Add to stage…")
        b_add_stage.clicked.connect(self._add_to_stage)
        btns.addWidget(b_add_stage)
        b_sync = QPushButton("Sync from PCB")
        b_sync.setToolTip(
            "Re-walk the .kicad_pcb and add any 3D models that are "
            "referenced by footprints but missing from this config."
        )
        b_sync.clicked.connect(self._sync_from_pcb)
        btns.addWidget(b_sync)
        cl.addLayout(btns)

        splitter.addWidget(comp_panel)

        # --- Stages panel ---
        stage_panel = QWidget()
        sl = QVBoxLayout(stage_panel)
        sl.setContentsMargins(8, 8, 8, 8)
        sl.addWidget(QLabel(f"<b>Stages</b> ({len(cfg.stages)})"))
        self.stage_list = QListWidget()
        self.stage_list.itemDoubleClicked.connect(self._preview_selected_stage_item)
        for s in cfg.stages:
            text = f"{s.n}. {s.title}  —  {len(s.parts)} part(s)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, s.n)
            self.stage_list.addItem(item)
        sl.addWidget(self.stage_list, 1)

        sbtns = QHBoxLayout()
        b_preview = QPushButton("Preview…")
        b_preview.setToolTip(
            "Show parts list and board/page image for the selected stage "
            "(double-clicking a stage does the same)."
        )
        b_preview.clicked.connect(self._preview_selected_stage)
        sbtns.addWidget(b_preview)
        b_new = QPushButton("+ Stage")
        b_new.clicked.connect(self._new_stage)
        sbtns.addWidget(b_new)
        b_rm = QPushButton("− Remove stage")
        b_rm.clicked.connect(self._remove_stage)
        sbtns.addWidget(b_rm)
        b_auto = QPushButton("Auto-arrange by height")
        b_auto.setToolTip(
            "Measure each STEP's Z extent and cluster components into stages "
            "from shortest to tallest. Replaces the current stage list."
        )
        b_auto.clicked.connect(self._auto_stages_by_height)
        sbtns.addWidget(b_auto)
        sl.addLayout(sbtns)

        splitter.addWidget(stage_panel)
        splitter.setSizes([550, 550])

        # Bottom: render buttons
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)
        bottom = QHBoxLayout()
        b_clean = QPushButton("Clean temp files")
        b_clean.setToolTip(
            "Remove tmp*.kicad_pcb and tmp*.kicad_prl files left over from "
            "interrupted kicad-cli renders."
        )
        b_clean.clicked.connect(self._clean_temp_files)
        bottom.addWidget(b_clean)
        bottom.addStretch(1)
        b_render = QPushButton("Render parts")
        b_render.clicked.connect(self._render_parts)
        bottom.addWidget(b_render)
        b_build = QPushButton("Build guide")
        # Keep the bright-yellow accent on this one, with explicit dark text
        # so it's readable on both light and dark mode.
        b_build.setStyleSheet(
            "QPushButton { background: #ffd400; color: #111; "
            "font-weight: bold; padding: 8px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #ffe04d; }"
        )
        b_build.clicked.connect(self._build_guide)
        bottom.addWidget(b_build)
        outer.addLayout(bottom)

        self._set_status("Ready.")
        self.destroyed.connect(lambda *_: log.debug("ProjectWindow destroyed"))

    def closeEvent(self, ev):  # noqa: N802 (Qt naming)
        log.debug("ProjectWindow closeEvent")
        super().closeEvent(ev)

    # ------------------------------------------------------------------
    def _set_status(self, msg: str):
        self.statusBar().showMessage(msg)

    # ------------------------------------------------------------------
    def _orient_selected_item(self, item: QListWidgetItem):
        from kibuilder.gui.orient import OrientWindow
        key = item.data(Qt.ItemDataRole.UserRole)
        log.debug("opening orient for %s", key)
        win = OrientWindow(self._cfg, None, selected_key=key)
        keep_alive(win)
        win.saved.connect(self._on_orient_saved)
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_orient_saved(self, key: str):
        log.debug("orient saved: %s", key)
        try:
            self._reload_components()
        except Exception:
            log.exception("reload after orient save failed")
        # Bring the project window back to the foreground.
        self.show()
        self.raise_()
        self.activateWindow()

    def _orient_selected(self):
        items = self.comp_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Orient", "Select a component first.")
            return
        self._orient_selected_item(items[0])

    def _sync_from_pcb(self):
        from kibuilder.gui.new_project import sync_components_from_pcb
        try:
            added = sync_components_from_pcb(self._cfg)
        except Exception as e:
            log.exception("sync from PCB failed")
            QMessageBox.critical(self, "Sync failed", str(e))
            return
        if not added:
            QMessageBox.information(
                self, "Sync from PCB",
                "Config is already in sync — no new components found.",
            )
            return
        kbcfg.save(self._cfg)
        self._reload_components()
        QMessageBox.information(
            self, "Sync from PCB",
            f"Added {len(added)} new component(s):\n\n"
            + "\n".join(f"  • {k}" for k in added)
            + "\n\nTip: hit Auto-arrange by height to re-bucket the stages.",
        )

    def _reload_components(self):
        # Refresh rotation badges after the orient window closes
        try:
            self._cfg = kbcfg.load(self._cfg.source_path)
        except Exception:
            return
        self.comp_list.clear()
        for key, comp in self._cfg.components.items():
            label = key
            if any((comp.rot_x, comp.rot_y, comp.rot_z)):
                label += f"   (rot {int(comp.rot_x)}/{int(comp.rot_y)}/{int(comp.rot_z)})"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.comp_list.addItem(it)

    # ------------------------------------------------------------------
    def _add_to_stage(self):
        items = self.comp_list.selectedItems()
        if not items:
            return
        keys = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        menu = QMenu(self)
        for s in self._cfg.stages:
            act = QAction(f"{s.n}. {s.title}", self)
            act.triggered.connect(
                lambda _, stg=s: self._do_add_to_stage(stg, keys)
            )
            menu.addAction(act)
        menu.exec(self.cursor().pos())

    def _do_add_to_stage(self, stg: kbcfg.StageSpec, keys: list[str]):
        for k in keys:
            stg.parts.append(kbcfg.StagePart(key=k, qty=1, label=k))
        kbcfg.save(self._cfg)
        self._refresh_stages()
        self._set_status(f"Added {len(keys)} part(s) to stage {stg.n}.")

    def _refresh_stages(self):
        self.stage_list.clear()
        for s in self._cfg.stages:
            text = f"{s.n}. {s.title}  —  {len(s.parts)} part(s)"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, s.n)
            self.stage_list.addItem(it)

    def _new_stage(self):
        n = max((s.n for s in self._cfg.stages), default=0) + 1
        self._cfg.stages.append(
            kbcfg.StageSpec(n=n, title=f"Stage {n}", sub="", parts=[])
        )
        kbcfg.save(self._cfg)
        self._refresh_stages()

    def _remove_stage(self):
        items = self.stage_list.selectedItems()
        if not items:
            return
        n = items[0].data(Qt.ItemDataRole.UserRole)
        self._cfg.stages = [s for s in self._cfg.stages if s.n != n]
        kbcfg.save(self._cfg)
        self._refresh_stages()

    def _preview_selected_stage_item(self, item: QListWidgetItem):
        from kibuilder.gui.stage_preview import StagePreview
        n = item.data(Qt.ItemDataRole.UserRole)
        stage = next((s for s in self._cfg.stages if s.n == n), None)
        if stage is None:
            return
        dlg = StagePreview(self._cfg, stage, self)
        dlg.changed.connect(self._refresh_stages)
        dlg.exec()

    def _preview_selected_stage(self):
        items = self.stage_list.selectedItems()
        if not items:
            QMessageBox.information(
                self, "Preview", "Select a stage to preview first."
            )
            return
        self._preview_selected_stage_item(items[0])

    def _auto_stages_by_height(self):
        ans = QMessageBox.question(
            self, "Auto-arrange stages",
            "This will measure every component's STEP height and rebuild "
            "the stage list from shortest to tallest, replacing any stages "
            "you've already defined.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._set_status("Measuring component heights…")
        QApplication.processEvents()
        try:
            from kibuilder.heights import auto_stages_by_height
            new_stages = auto_stages_by_height(self._cfg)
        except Exception as e:
            log.exception("auto-stage failed")
            QMessageBox.critical(self, "Auto-arrange failed", str(e))
            self._set_status("Auto-arrange failed.")
            return
        self._cfg.stages = new_stages
        kbcfg.save(self._cfg)
        self._refresh_stages()
        self._set_status(
            f"Auto-arranged into {len(new_stages)} stages by height."
        )

    # ------------------------------------------------------------------
    def _render_parts(self):
        import subprocess
        from kibuilder.render.part import Renderer, RenderOptions
        out_root = Path(self._cfg.source_path).parent / self._cfg.project.output / "_components"
        out_root.mkdir(parents=True, exist_ok=True)
        r = Renderer()
        total = len(self._cfg.components)
        ok = 0
        for i, (key, comp) in enumerate(self._cfg.components.items(), 1):
            try:
                step = kbcfg.resolve_step(self._cfg, comp)
            except FileNotFoundError as e:
                self._set_status(f"({i}/{total}) MISSING {key}: {e}")
                continue
            self._set_status(f"({i}/{total}) rendering {key}…")
            QApplication.processEvents()
            r.render(
                step, out_root / f"{key}.png",
                RenderOptions(rot_x_deg=comp.rot_x, rot_y_deg=comp.rot_y,
                              rot_z_deg=comp.rot_z),
            )
            ok += 1
        self._set_status(f"Rendered {ok}/{total} parts → {out_root}")
        # Open the output folder in Finder so the user can see what landed.
        try:
            subprocess.run(["open", str(out_root)], check=False)
        except Exception:
            pass

    def _clean_temp_files(self):
        from kibuilder.render.board import purge_temp_files
        project_dir = Path(self._cfg.source_path).parent
        deleted = purge_temp_files(project_dir)
        msg = (
            f"Removed {len(deleted)} temp file(s) from {project_dir}."
            if deleted else
            "No temp files to clean."
        )
        self._set_status(msg)
        QMessageBox.information(self, "Clean temp files", msg)

    def _build_guide(self):
        import shutil
        import subprocess
        from kibuilder.render.part import Renderer, RenderOptions
        from kibuilder.render.board import render_cumulative, purge_temp_files
        from kibuilder.guide import build_pages, build_pdf, build_markdown

        # Sweep any leftovers from a prior interrupted build before starting.
        project_dir = Path(self._cfg.source_path).parent
        leftover = purge_temp_files(project_dir)
        if leftover:
            log.info("purged %d leftover temp file(s) before build", len(leftover))

        if shutil.which("kicad-cli") is None:
            QMessageBox.critical(
                self, "kicad-cli missing",
                "Building the guide needs `kicad-cli` on PATH. Install KiCad "
                "with command-line tools and try again.",
            )
            return
        if not self._cfg.stages:
            QMessageBox.warning(
                self, "No stages",
                "Define at least one stage (or use Auto-arrange by height) "
                "before building the guide.",
            )
            return

        out_root = Path(self._cfg.source_path).parent / self._cfg.project.output
        parts_dir = out_root / "_components"
        boards_dir = out_root / "_cum"
        out_root.mkdir(parents=True, exist_ok=True)

        n_components = len(self._cfg.components)
        n_stages = len(self._cfg.stages)
        # parts + boards + pages + 1 final PDF step
        total_steps = n_components + 2 * n_stages + 1

        dlg = QProgressDialog("Preparing…", None, 0, total_steps, self)
        dlg.setWindowTitle("Building guide")
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setCancelButton(None)
        dlg.setMinimumWidth(460)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        step = 0
        def tick(label: str):
            nonlocal step
            step += 1
            dlg.setLabelText(label)
            dlg.setValue(step)
            self._set_status(label)
            QApplication.processEvents()

        try:
            # 1) Per-component renders (V3d, transparent bg)
            r = Renderer()
            for i, (key, comp) in enumerate(self._cfg.components.items(), 1):
                tick(f"Component {i}/{n_components}: {key}")
                try:
                    step_path = kbcfg.resolve_step(self._cfg, comp)
                except FileNotFoundError:
                    log.warning("STEP missing for %s, skipping", key)
                    continue
                try:
                    r.render(
                        step_path, parts_dir / f"{key}.png",
                        RenderOptions(
                            rot_x_deg=comp.rot_x,
                            rot_y_deg=comp.rot_y,
                            rot_z_deg=comp.rot_z,
                        ),
                    )
                except Exception:
                    log.exception("component render failed for %s", key)

            # 2) Cumulative board renders (kicad-cli)
            def _board_progress(idx, n_total, stage):
                tick(f"Board {idx}/{n_total}: stage {stage.n} — {stage.title}")

            try:
                render_cumulative(
                    self._cfg, boards_dir, progress=_board_progress,
                )
            except Exception as e:
                log.exception("board rendering failed")
                QMessageBox.critical(self, "Board render failed", str(e))
                self._set_status("Board render failed.")
                return

            # 3) Compose pages
            def _page_progress(idx, n_total, stage):
                tick(f"Page {idx}/{n_total}: {stage.title}")

            try:
                pages = build_pages(
                    self._cfg, parts_dir, boards_dir, out_root,
                    progress=_page_progress,
                )
            except Exception as e:
                log.exception("page composition failed")
                QMessageBox.critical(self, "Compose failed", str(e))
                self._set_status("Compose failed.")
                return

            # 4) Bundle into a single landscape PDF
            tick("Writing PDF…")
            pdf_name = (
                Path(self._cfg.project.pcb).stem or "kibuilder"
            ) + "_guide.pdf"
            pdf_path = out_root / pdf_name
            try:
                build_pdf(pages, pdf_path)
            except Exception as e:
                log.exception("PDF export failed")
                QMessageBox.warning(
                    self, "PDF export failed",
                    f"JPG pages were built but the PDF failed: {e}",
                )
                pdf_path = None

            # 5) Emit a GitHub-viewable markdown guide alongside everything
            try:
                build_markdown(
                    self._cfg, pages, out_root / "ASSEMBLY.md",
                    pdf_path=pdf_path,
                )
            except Exception:
                log.exception("markdown export failed (non-fatal)")

        finally:
            dlg.close()

        msg = f"Built {len(pages)} pages"
        if pdf_path:
            msg += f"  +  {pdf_path.name}"
        msg += f"  →  {out_root}"
        self._set_status(msg)
        try:
            subprocess.run(["open", str(out_root)], check=False)
        except Exception:
            pass
