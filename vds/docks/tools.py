"""Eigenschaften-Fenster, Toolbox und Haltepunkte-Liste."""
import datetime
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import QLineEdit, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ..build.languages import BY_ID, LANGS, lang_for
from ..designer.canvas import MIME
from ..designer.controls import CATEGORIES, SPECS
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


class _Tree(QTreeWidget):
    """Baum mit Drag-Unterstützung: Controls werden als MIME-Daten auf den Designer gezogen."""

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, items):
        m = QMimeData()
        if items and items[0].data(0, CTRL_ROLE):
            m.setData(MIME, items[0].data(0, CTRL_ROLE).encode())
        return m


class Toolbox(QWidget):
    """Toolbox: alle Steuerelemente des Designers (nach Kategorien und A–Z, mit Suche) plus Codeausschnitte für die Sprache der aktuellen Datei."""
    insertSnippet = Signal(str)
    controlActivated = Signal(str)     # Doppelklick auf ein Control -> im aktiven Designer einfügen

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lang_id: str | None = None
        self.search = QLineEdit(placeholderText="Toolbox durchsuchen …")
        self.tree = _Tree(); self.tree.setHeaderHidden(True)
        self.tree.setDragEnabled(True); self.tree.setDragDropMode(QTreeWidget.DragOnly)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self.search); lay.addWidget(self.tree, 1)
        self.search.textChanged.connect(self.apply_filter)
        self.tree.itemDoubleClicked.connect(self._double)
        self._expanded: dict = {}
        self.rebuild()

    # --- Aufbau ---------------------------------------------------------------------------------------------------
    def set_language(self, lang_id: str | None):
        if lang_id != self.lang_id:
            self.lang_id = lang_id
            self.rebuild()

    def _remember(self):
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            self._expanded[it.text(0)] = it.isExpanded()

    def rebuild(self):
        self._remember()
        self.tree.clear()
        by_cat: dict = {}
        for spec in SPECS:
            by_cat.setdefault(spec.category, []).append(spec)
        for cat in CATEGORIES:
            if cat in by_cat:
                g = QTreeWidgetItem(self.tree, [f"{cat}  ({len(by_cat[cat])})"])
                g.setData(0, Qt.UserRole + 2, cat)
                for spec in by_cat[cat]:
                    self._control(g, spec)
        allg = QTreeWidgetItem(self.tree, [f"Alle Steuerelemente (A–Z)  ({len(SPECS)})"])
        for spec in sorted(SPECS, key=lambda x: x.type.lower()):
            self._control(allg, spec)
        lang = BY_ID.get(self.lang_id or "")
        general = QTreeWidgetItem(self.tree, ["Allgemein"])
        for label, text in [("TODO-Kommentar", "TODO: "), ("Datum", datetime.date.today().isoformat()), ("Uhrzeit", datetime.datetime.now().strftime("%H:%M")),
                            ("Lorem ipsum", "Lorem ipsum dolor sit amet, consectetur adipiscing elit.")]:
            self._snippet(general, label, text)
        if lang and lang.snippets:
            g = QTreeWidgetItem(self.tree, [f"Codeausschnitte – {lang.name}  ({len(lang.snippets)})"])
            for label, text in lang.snippets.items():
                self._snippet(g, label, text)
        elif not lang:
            hint = QTreeWidgetItem(self.tree, ["Codeausschnitte: öffne eine Code-Datei"])
            hint.setFlags(Qt.NoItemFlags)
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            default = i == 0 or it.text(0).startswith("Codeausschnitte")
            it.setExpanded(self._expanded.get(it.text(0), default))
        self.apply_filter()

    def _control(self, parent, spec):
        it = QTreeWidgetItem(parent, [spec.type])
        it.setIcon(0, control_icon(spec.type))
        it.setData(0, CTRL_ROLE, spec.type)
        it.setToolTip(0, f"{spec.type} ({spec.qt.__name__}) – auf das Formular ziehen oder doppelklicken")

    @staticmethod
    def _snippet(parent, label, text):
        it = QTreeWidgetItem(parent, [label])
        it.setData(0, Qt.UserRole, text)
        it.setToolTip(0, text)

    # --- Suche -------------------------------------------------------------------------------------------------------
    def apply_filter(self):
        q = self.search.text().strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            shown = 0
            for j in range(g.childCount()):
                ch = g.child(j)
                hit = not q or q in ch.text(0).lower()
                ch.setHidden(not hit)
                shown += hit
            g.setHidden(bool(q) and shown == 0)
            if q and shown:
                g.setExpanded(True)

    def _double(self, it, _c):
        if it.data(0, CTRL_ROLE):
            self.controlActivated.emit(it.data(0, CTRL_ROLE))
        elif it.data(0, Qt.UserRole):
            self.insertSnippet.emit(it.data(0, Qt.UserRole))


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
