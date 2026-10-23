"""Eigenschaften-Fenster, Toolbox und Haltepunkte-Liste."""
import datetime
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem

from ..build.languages import LANGS, lang_for
from ..designer.canvas import MIME
from ..designer.controls import SPECS
from ..icons import control_icon

CTRL_ROLE = Qt.UserRole + 1


class Properties(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.horizontalHeader().hide(); self.verticalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        self.setColumnWidth(0, 110)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setShowGrid(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

    def show_path(self, path: str | None):
        rows = []
        if path:
            p = Path(path)
            st = p.stat()
            lang = lang_for(p)
            rows = [("Dateiname", p.name), ("Vollständiger Pfad", str(p)),
                    ("Typ", "Ordner" if p.is_dir() else (lang.name if lang else "Datei")),
                    ("Größe", "" if p.is_dir() else f"{st.st_size:,} Bytes".replace(",", ".")),
                    ("Geändert", datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M:%S")),
                    ("Buildaktion", "Kompilieren" if lang and not p.is_dir() else "Keine")]
        self.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            a = QTableWidgetItem(k); a.setForeground(Qt.gray)
            self.setItem(i, 0, a); self.setItem(i, 1, QTableWidgetItem(v))
            self.item(i, 1).setToolTip(v)


class Toolbox(QTreeWidget):
    insertSnippet = Signal(str)
    controlActivated = Signal(str)     # Doppelklick auf ein Control -> im aktiven Designer einfügen

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragOnly)
        groups = {}
        for spec in SPECS:
            g = groups.get(spec.category) or groups.setdefault(spec.category, QTreeWidgetItem(self, [spec.category]))
            it = QTreeWidgetItem(g, [spec.type])
            it.setIcon(0, control_icon(spec.type))
            it.setData(0, CTRL_ROLE, spec.type)
        general = QTreeWidgetItem(self, ["Allgemein"])
        for label, text in [("TODO-Kommentar", "TODO: "), ("Datum/Uhrzeit", datetime.date.today().isoformat())]:
            self._add(general, label, text)
        for l in LANGS:
            if l.snippets:
                g = QTreeWidgetItem(self, [f"Codeausschnitte – {l.name}"])
                for label, text in l.snippets.items():
                    self._add(g, label, text)
        self.expandAll()
        for i in range(self.topLevelItemCount()):
            if self.topLevelItem(i).text(0) == "Allgemein" or self.topLevelItem(i).text(0).startswith("Codeausschnitte"):
                self.topLevelItem(i).setExpanded(False)
        self.itemDoubleClicked.connect(self._double)

    def _double(self, it, _c):
        if it.data(0, CTRL_ROLE):
            self.controlActivated.emit(it.data(0, CTRL_ROLE))
        elif it.data(0, Qt.UserRole):
            self.insertSnippet.emit(it.data(0, Qt.UserRole))

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, items):
        m = QMimeData()
        if items and items[0].data(0, CTRL_ROLE):
            m.setData(MIME, items[0].data(0, CTRL_ROLE).encode())
        return m

    @staticmethod
    def _add(parent, label, text):
        it = QTreeWidgetItem(parent, [label])
        it.setData(0, Qt.UserRole, text)


class Breakpoints(QTableWidget):
    activated = Signal(str, int)
    toggled = Signal(str, int, bool)     # Pfad, Zeile, aktiv
    removed = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["", "Name", "Bedingung", "Datei"])
        self.verticalHeader().hide()
        self.setColumnWidth(0, 30); self.setColumnWidth(1, 220); self.setColumnWidth(2, 220)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cellDoubleClicked.connect(self._dbl)
        self.itemChanged.connect(self._changed)
        self._rows: list = []

    def update_list(self, items):  # [(path, line, condition, enabled)]
        self.blockSignals(True)
        self._rows = sorted(items)
        self.setRowCount(len(self._rows))
        for i, (path, line, cond, enabled) in enumerate(self._rows):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
            self.setItem(i, 0, chk)
            self.setItem(i, 1, QTableWidgetItem(f"{Path(path).name}, Zeile {line}"))
            self.setItem(i, 2, QTableWidgetItem(f"Wenn {cond}" if cond else ""))
            self.setItem(i, 3, QTableWidgetItem(path))
        self.blockSignals(False)

    def _changed(self, item):
        if item.column() == 0 and item.row() < len(self._rows):
            path, line, _c, _e = self._rows[item.row()]
            self.toggled.emit(path, line, item.checkState() == Qt.Checked)

    def _dbl(self, row, col):
        if col != 0:
            self.activated.emit(self._rows[row][0], self._rows[row][1])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            for r in sorted({i.row() for i in self.selectedItems()}, reverse=True):
                self.removed.emit(self._rows[r][0], self._rows[r][1])
        else:
            super().keyPressEvent(e)
