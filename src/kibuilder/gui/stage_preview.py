"""Read-only preview of a single assembly stage.

Shows the parts list and whichever build artifact is freshest:
    1. Composed assembly page (out_dir/NN_slug.jpg) — if Build guide has run
    2. Cumulative board render (_cum/NN.jpg)    — if boards exist
    3. Fallback message asking the user to build the guide first.
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from kibuilder import config as kbcfg

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower()).strip("_")[:30] or "stage"


class StagePreview(QDialog):
    """Read+edit view of one stage. Emits `changed` when parts are removed."""

    changed = pyqtSignal()

    def __init__(self,
                 cfg: kbcfg.Config,
                 stage: kbcfg.StageSpec,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Stage {stage.n} — {stage.title}")
        self.resize(1200, 800)
        self._cfg = cfg
        self._stage = stage

        layout = QHBoxLayout(self)

        # --- Image preview (left) -----------------------------------------
        img_col = QVBoxLayout()
        self._image = QLabel("(no preview yet)")
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(820, 620)
        self._image.setStyleSheet(
            "background:#f4f4f4; border:1px solid #ddd;"
        )
        img_col.addWidget(self._image, 1)
        self._note = QLabel("")
        self._note.setStyleSheet("color:#777;")
        self._note.setWordWrap(True)
        img_col.addWidget(self._note)
        layout.addLayout(img_col, 3)

        # --- Title + parts list (right) -----------------------------------
        info = QVBoxLayout()
        info.addWidget(QLabel(f"<b>Stage {stage.n}</b>  ·  Title:"))
        self._title_edit = QLineEdit(stage.title)
        self._title_edit.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self._title_edit.setPlaceholderText("Stage title")
        self._title_edit.editingFinished.connect(self._on_title_changed)
        info.addWidget(self._title_edit)

        info.addWidget(QLabel("Subtitle / description:"))
        self._sub_edit = QLineEdit(stage.sub)
        self._sub_edit.setPlaceholderText(
            "Short instruction shown under the title on the page"
        )
        self._sub_edit.editingFinished.connect(self._on_sub_changed)
        info.addWidget(self._sub_edit)

        self._parts_label = QLabel()
        info.addWidget(self._parts_label)

        self._plist = QListWidget()
        self._plist.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        info.addWidget(self._plist, 1)
        self._refresh_parts()

        # Edit row: remove selected parts from this stage
        edit_row = QHBoxLayout()
        b_remove = QPushButton("Remove selected from stage")
        b_remove.setToolTip(
            "Removes the highlighted parts from this stage only — the "
            "component itself stays in the config."
        )
        b_remove.clicked.connect(self._remove_selected)
        edit_row.addWidget(b_remove)
        info.addLayout(edit_row)

        # Re-render: rebuild this one stage's board + page without
        # touching the rest of the guide.
        self._b_rerender = QPushButton("Re-render this stage")
        self._b_rerender.setToolTip(
            "Re-runs kicad-cli for this stage only and recomposes its "
            "assembly page. Use after editing parts."
        )
        self._b_rerender.clicked.connect(self._rerender_stage)
        info.addWidget(self._b_rerender)

        # Cumulative summary: everything populated through this stage
        self._cum_label = QLabel()
        info.addWidget(self._cum_label)
        self._refresh_cum_label()

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        info.addWidget(close)

        layout.addLayout(info, 2)

        self._load_preview()

    # ------------------------------------------------------------------
    def _cumulative_part_count(self) -> int:
        """Sum of qty across all stages up to and including this one."""
        total = 0
        for s in sorted(self._cfg.stages, key=lambda x: x.n):
            for p in s.parts:
                total += p.qty
            if s.n == self._stage.n:
                break
        return total

    def _refresh_parts(self):
        self._plist.clear()
        for i, p in enumerate(self._stage.parts):
            text = f"  ×{p.qty}    {p.key}"
            if p.label and p.label != p.key:
                text += f"    — {p.label}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._plist.addItem(item)
        if not self._stage.parts:
            self._plist.addItem(QListWidgetItem(
                "  (no parts — this stage is informational)"
            ))
        self._parts_label.setText(
            f"<b>Parts to add this stage ({len(self._stage.parts)})</b>"
        )

    def _refresh_cum_label(self):
        self._cum_label.setText(
            f"<i>Board total through stage {self._stage.n}: "
            f"{self._cumulative_part_count()} component instance(s)</i>"
        )

    def _on_title_changed(self):
        new = self._title_edit.text().strip()
        if not new or new == self._stage.title:
            return
        self._stage.title = new
        kbcfg.save(self._cfg)
        self.setWindowTitle(f"Stage {self._stage.n} — {new}")
        self._note.setText(
            f"Title saved. Re-render this stage to refresh the page image."
        )
        self.changed.emit()

    def _on_sub_changed(self):
        new = self._sub_edit.text().strip()
        if new == self._stage.sub:
            return
        self._stage.sub = new
        kbcfg.save(self._cfg)
        self._note.setText(
            "Subtitle saved. Re-render this stage to refresh the page image."
        )
        self.changed.emit()

    def _rerender_stage(self):
        from PyQt6.QtWidgets import QApplication
        from kibuilder.render.board import render_stage_board
        from kibuilder.guide import compose_page

        if self._cfg.source_path is None:
            return
        out_root = self._cfg.source_path.parent / self._cfg.project.output
        boards_dir = out_root / "_cum"
        parts_dir = out_root / "_components"

        self._b_rerender.setEnabled(False)

        # 3 discrete ticks: starting → board done → page done
        dlg = QProgressDialog(
            "Rendering board with kicad-cli (can take 5–10 s)…",
            None, 0, 3, self,
        )
        dlg.setWindowTitle(f"Re-rendering stage {self._stage.n}")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setCancelButton(None)
        dlg.setMinimumWidth(420)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        try:
            dlg.setValue(1)
            QApplication.processEvents()
            try:
                board_path = render_stage_board(
                    self._cfg, self._stage.n, boards_dir,
                )
            except Exception as e:
                QMessageBox.critical(self, "Board render failed", str(e))
                return
            if board_path is None:
                QMessageBox.warning(
                    self, "Board render failed",
                    "kicad-cli returned no output — check console for details.",
                )
                return

            dlg.setLabelText("Composing assembly page…")
            dlg.setValue(2)
            QApplication.processEvents()
            out_page = (
                out_root / f"{self._stage.n:02d}_{_slug(self._stage.title)}.jpg"
            )
            try:
                compose_page(self._stage, board_path, parts_dir, out_page)
            except Exception as e:
                QMessageBox.critical(self, "Compose failed", str(e))
                return

            dlg.setValue(3)
            QApplication.processEvents()

            self._load_preview()
            self._note.setText(
                f"Re-rendered stage {self._stage.n}  ·  {out_page.name}"
            )
        finally:
            dlg.close()
            self._b_rerender.setEnabled(True)

    def _remove_selected(self):
        items = self._plist.selectedItems()
        # Drop the placeholder row if it's selected; it has no UserRole int
        idxs = sorted(
            (it.data(Qt.ItemDataRole.UserRole) for it in items
             if it.data(Qt.ItemDataRole.UserRole) is not None),
            reverse=True,
        )
        if not idxs:
            QMessageBox.information(
                self, "Remove parts",
                "Select one or more parts in the list first.",
            )
            return
        removed_keys = [self._stage.parts[i].key for i in idxs]
        for i in idxs:
            del self._stage.parts[i]
        kbcfg.save(self._cfg)
        self._refresh_parts()
        self._refresh_cum_label()
        self.changed.emit()
        # Status: lightweight feedback in the note label
        self._note.setText(
            "Removed: " + ", ".join(removed_keys)
            + "  ·  rebuild the guide to refresh the board image."
        )

    def _load_preview(self):
        if self._cfg.source_path is None:
            self._note.setText("Config has no on-disk path; nothing to preview.")
            return
        out_root = self._cfg.source_path.parent / self._cfg.project.output
        candidates = [
            (out_root / f"{self._stage.n:02d}_{_slug(self._stage.title)}.jpg",
             "Composed guide page"),
            (out_root / "_cum" / f"{self._stage.n:02d}.jpg",
             "Cumulative board render (page not composed yet)"),
        ]
        for path, label in candidates:
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    self._image.setPixmap(pm.scaled(
                        self._image.width(),
                        self._image.height(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    self._note.setText(f"{label}  ·  {path.name}")
                    return
        self._note.setText(
            "No render yet for this stage — run Build guide first."
        )

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        # Reflow image to new size
        self._load_preview()
