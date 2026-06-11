"""Splash / welcome window — pick or create a kibuilder project."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Module-level live-window registry so Python doesn't garbage-collect
# windows the moment their last Python reference goes out of scope.
_OPEN_WINDOWS: set = set()


def keep_alive(win):
    """Hold a window alive at module scope; release it when it closes."""
    _OPEN_WINDOWS.add(win)
    win.destroyed.connect(lambda *_: _OPEN_WINDOWS.discard(win))
    return win


class Splash(QMainWindow):
    """Welcome window: open existing yaml, new from .kicad_pcb, or recent."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("kibuilder")
        self.resize(720, 520)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(40, 36, 40, 36)
        outer.setSpacing(18)

        # Header
        title = QLabel("kibuilder")
        f = QFont(); f.setPointSize(36); f.setBold(True)
        title.setFont(f)
        outer.addWidget(title)

        subtitle = QLabel("Visual step-by-step assembly guides for KiCAD PCBs.")
        # Use Qt's "disabled" palette role so it adapts to dark/light mode.
        subtitle.setEnabled(False)
        outer.addWidget(subtitle)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)

        # Big actions
        actions = QHBoxLayout()
        actions.setSpacing(14)

        for label, slot in (
            ("Open project…\n(.yaml)", self.open_existing),
            ("New project…\n(from .kicad_pcb)", self.new_from_pcb),
        ):
            btn = QPushButton(label)
            btn.setMinimumHeight(120)
            font = btn.font(); font.setPointSize(16); btn.setFont(font)
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        outer.addLayout(actions)

        # Recent
        outer.addWidget(QLabel("Recent projects"))
        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(self._open_recent_item)
        outer.addWidget(self.recent_list, 1)

        self._settings = QSettings("kibuilder", "kibuilder")
        self._refresh_recent()

    # ------------------------------------------------------------------
    def _refresh_recent(self):
        self.recent_list.clear()
        recents = self._settings.value("recent_projects", []) or []
        for p in recents:
            if Path(p).exists():
                item = QListWidgetItem(p)
                item.setData(Qt.ItemDataRole.UserRole, p)
                self.recent_list.addItem(item)

    def _add_recent(self, path: str):
        recents = list(self._settings.value("recent_projects", []) or [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._settings.setValue("recent_projects", recents[:10])

    def _open_recent_item(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        self._open_project(Path(path))

    # ------------------------------------------------------------------
    def open_existing(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open kibuilder config", "", "kibuilder YAML (*.yaml *.yml)",
        )
        if path:
            self._open_project(Path(path))

    def new_from_pcb(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick a .kicad_pcb", "", "KiCAD PCB (*.kicad_pcb)",
        )
        if not path:
            return
        from kibuilder.gui.new_project import new_project_from_pcb
        yaml_path = new_project_from_pcb(Path(path), parent=self)
        if yaml_path:
            self._open_project(yaml_path)

    def _open_project(self, yaml_path: Path):
        import logging
        log = logging.getLogger("kibuilder.splash")
        from kibuilder.gui.project import ProjectWindow
        from kibuilder import config as kbcfg
        try:
            cfg = kbcfg.load(yaml_path)
        except Exception as e:
            log.exception("config load failed")
            QMessageBox.critical(self, "Open failed", f"{e}")
            return
        self._add_recent(str(yaml_path))
        self._refresh_recent()
        proj = ProjectWindow(cfg)
        keep_alive(proj)
        log.debug("ProjectWindow created; keep_alive set has %d entries", len(_OPEN_WINDOWS))
        proj.show()
        # Force Qt to actually paint the project window before we close the
        # splash. Without this, the splash close briefly sees "no visible
        # windows" and the app can quit (quitOnLastWindowClosed=True).
        QApplication.processEvents()
        proj.raise_()
        proj.activateWindow()
        log.debug("ProjectWindow shown; closing splash")
        self.close()


def run():
    import logging
    log = logging.getLogger("kibuilder.splash")
    app = QApplication.instance() or QApplication(sys.argv)
    # Make doubly sure the app doesn't quit between window transitions.
    app.setQuitOnLastWindowClosed(True)
    win = Splash()
    keep_alive(win)
    win.show()
    log.debug("Splash shown, entering Qt event loop")
    rc = app.exec()
    log.debug("Qt event loop exited with code %s", rc)
    sys.exit(rc)


if __name__ == "__main__":
    run()
