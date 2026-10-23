"""Verweise-Fenster: Ergebnisse von „Alle Verweise suchen“ (Language Server oder Wortsuche)."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class ReferencesPanel(QWidget):
    activated = Signal(str, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.info = QLabel(); self.info.setObjectName("sub")
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Datei", "Zeile", "Text"])
        self.tree.setColumnWidth(0, 240); self.tree.setColumnWidth(1, 60)
        self.tree.header().setStretchLastSection(True)
        self.tree.setRootIsDecorated(False)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 4, 0, 0); lay.addWidget(self.info); lay.addWidget(self.tree, 1)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.activated.emit(it.data(0, Qt.UserRole), int(it.text(1)), it.data(1, Qt.UserRole)))
        self.show_results("", [], Path("."))

    def show_results(self, word: str, refs: list, root: Path):
        """refs: [(Pfad, Zeile, Spalte, Text)]"""
        self.tree.clear()
        for path, line, col, text in refs:
            try:
                rel = str(Path(path).relative_to(root))
            except ValueError:
                rel = path
            it = QTreeWidgetItem(self.tree, [rel, str(line), text])
            it.setData(0, Qt.UserRole, path); it.setData(1, Qt.UserRole, col)
        files = len({r[0] for r in refs})
        self.info.setText(f"„{word}“: {len(refs)} Verweis(e) in {files} Datei(en)" if word else "Noch keine Suche – Umschalt+F12 auf einem Namen.")
