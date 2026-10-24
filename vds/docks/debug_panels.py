"""Debug-Fenster: Lokal (Variablenbaum mit Lazy-Expand und Änderungs-Hervorhebung), Überwachung, Aufrufliste, Direktfenster."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QHeaderView, QLineEdit, QMenu, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from ..theme import t

REF = Qt.UserRole
LOADED = Qt.UserRole + 1
CHANGED = QColor(t("#ff7a93"))
DIM = QColor(t("#8fa3c7"))
ERR = QColor(t("#ff4d6d"))
LOCAL_SCOPES = ("locals", "arguments", "lokal", "args", "local")
NOISE = ("special variables", "function variables", "class variables")   # technische Gruppen von debugpy ausblenden


def _tree(headers, widths):
    t = QTreeWidget()
    t.setHeaderLabels(headers)
    t.setUniformRowHeights(True)
    t.setAlternatingRowColors(False)
    for i, w in enumerate(widths):
        t.setColumnWidth(i, w)
    t.header().setStretchLastSection(True)
    return t


def _fill(item: QTreeWidgetItem, v: dict):
    item.setText(0, v["name"]); item.setText(1, v["value"]); item.setText(2, v.get("type", ""))
    item.setToolTip(1, v["value"])
    if v.get("ref", 0) > 0:
        item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
        item.setData(0, REF, v["ref"])


class VariablesTree(QTreeWidget):
    """Lokale Variablen des gewählten Frames. Geänderte Werte seit dem letzten Anhalten erscheinen rosa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Name", "Wert", "Typ"])
        self.setColumnWidth(0, 170); self.setColumnWidth(1, 260)
        self.header().setStretchLastSection(True)
        self.setUniformRowHeights(True)
        self.session = None
        self.prev: dict = {}
        self._gen = 0
        self._nlocal = 0
        self.itemExpanded.connect(self._expanded)

    def reset_state(self):
        """Neue Sitzung/Ende: Baum leeren und Änderungsvergleich zurücksetzen (nicht 'reset' nennen: überschreibt eine Qt-Methode)."""
        self._gen += 1
        self.prev = {}
        self.clear()

    def grey_out(self):
        """Programm läuft wieder: Werte sind nicht mehr aktuell."""
        for i in range(self.topLevelItemCount()):
            for c in range(3):
                self.topLevelItem(i).setForeground(c, QBrush(DIM))

    def refresh(self, session):
        self.session = session
        self._gen += 1
        gen = self._gen
        self.clear()
        self._nlocal = 0                      # echte Variablen stehen vor den eingeklappten Gruppen (z. B. Globals)
        old, new = dict(self.prev), {}

        def got_scopes(scopes):
            if gen != self._gen:
                return
            for name, ref in scopes:
                low = name.lower()
                if low.startswith("register"):
                    continue
                if low in LOCAL_SCOPES:
                    session.variables(ref, lambda vs, g=gen: g == self._gen and self._add(None, vs, old, new))
                else:                           # z. B. Globals: eingeklappt, lädt beim Aufklappen
                    grp = QTreeWidgetItem(self, [name])
                    grp.setData(0, REF, ref); grp.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                    grp.setForeground(0, QBrush(DIM))
        session.scopes(got_scopes)

    def _add(self, parent, vs, old, new):
        for v in vs:
            if (v["name"].startswith("__") and v["name"].endswith("__")) or v["name"] in NOISE:
                continue
            if parent is None:
                item = QTreeWidgetItem()
                self.insertTopLevelItem(self._nlocal, item)
                self._nlocal += 1
            else:
                item = QTreeWidgetItem(parent)
            _fill(item, v)
            if parent is None:
                key = v["name"]
                new[key] = v["value"]
                if key in old and old[key] != v["value"]:
                    f = QFont(item.font(1)); f.setBold(True)
                    item.setForeground(1, QBrush(CHANGED)); item.setFont(1, f)
        if parent is None:
            self.prev.update(new)

    def _expanded(self, item):
        ref = item.data(0, REF)
        if not ref or item.data(0, LOADED) or not self.session:
            return
        item.setData(0, LOADED, True)
        gen = self._gen
        self.session.variables(ref, lambda vs: gen == self._gen and self._add(item, vs, {}, {}))


class WatchPanel(QWidget):
    """Überwachte Ausdrücke – werden bei jedem Anhalten im gewählten Frame neu ausgewertet."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.exprs: list[str] = []
        self.session = None
        self._gen = 0
        self.tree = _tree(["Name", "Wert", "Typ"], [170, 260, 80])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemExpanded.connect(self._expanded)
        self.edit = QLineEdit(placeholderText="Ausdruck hinzufügen …  (Enter)")
        self.edit.returnPressed.connect(self._add)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self.tree, 1); lay.addWidget(self.edit)
        self.render()

    def _add(self):
        e = self.edit.text().strip()
        if e and e not in self.exprs:
            self.exprs.append(e)
        self.edit.clear()
        self.refresh(self.session)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or it.parent():
            return
        m = QMenu(self)
        m.addAction("Entfernen", lambda: (self.exprs.remove(it.text(0)), self.refresh(self.session)))
        m.addAction("Alle entfernen", lambda: (self.exprs.clear(), self.refresh(self.session)))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def keyPressEvent(self, e):
        it = self.tree.currentItem()
        if e.key() == Qt.Key_Delete and it and not it.parent() and it.text(0) in self.exprs:
            self.exprs.remove(it.text(0)); self.refresh(self.session)
        else:
            super().keyPressEvent(e)

    def render(self):
        self.tree.clear()
        for e in self.exprs:
            it = QTreeWidgetItem(self.tree, [e, "", ""])
            it.setForeground(1, QBrush(DIM))

    def refresh(self, session):
        self.session = session
        self._gen += 1
        gen = self._gen
        self.render()
        if not session or session.state != "paused":
            return
        for i, e in enumerate(self.exprs):
            item = self.tree.topLevelItem(i)

            def got(ok, result, typ, ref, item=item):
                if gen != self._gen:
                    return
                item.setText(1, result); item.setText(2, typ); item.setToolTip(1, result)
                item.setForeground(1, QBrush(QColor(t("#dbe6ff")) if ok else ERR))
                if ok and ref > 0:
                    item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator); item.setData(0, REF, ref)
            session.evaluate(e, got, "watch")

    def grey_out(self):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setForeground(1, QBrush(DIM))

    def _expanded(self, item):
        ref = item.data(0, REF)
        if not ref or item.data(0, LOADED) or not self.session:
            return
        item.setData(0, LOADED, True)
        gen = self._gen

        def got(vs):
            if gen != self._gen:
                return
            for v in vs:
                _fill(QTreeWidgetItem(item), v)
        self.session.variables(ref, got)


class CallStackPanel(QTreeWidget):
    frameActivated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["", "Name", "Ort"])
        self.setColumnWidth(0, 26); self.setColumnWidth(1, 220)
        self.header().setStretchLastSection(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.itemClicked.connect(lambda it, _c: self.frameActivated.emit(self.indexOfTopLevelItem(it)))

    def show_frames(self, frames, sel: int):
        self.clear()
        for i, f in enumerate(frames):
            where = f"{Path(f.path).name}:{f.line}" if f.path else "(kein Quelltext)"
            it = QTreeWidgetItem(self, ["➜" if i == sel else "", f.name, where])
            it.setToolTip(2, f.path or "")
            if i == sel:
                it.setForeground(0, QBrush(QColor(t("#ffd60a"))))
                font = QFont(it.font(1)); font.setBold(True)
                it.setFont(1, font); it.setFont(2, font)
            elif not f.path:
                for c in (1, 2):
                    it.setForeground(c, QBrush(DIM))


class ImmediatePanel(QWidget):
    """Direktfenster: Ausdrücke im angehaltenen Programm auswerten."""
    submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.out = QPlainTextEdit(readOnly=True)
        self.edit = QLineEdit(placeholderText="Ausdruck auswerten …  (Enter)")
        self.edit.returnPressed.connect(self._send)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self.out, 1); lay.addWidget(self.edit)
        self.line("Direktfenster – Ausdrücke im angehaltenen Programm auswerten, z. B. n * 2 oder len(liste).", DIM)
        self.history: list[str] = []
        self.hpos = 0

    def line(self, text, color=None):
        from PySide6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setForeground(color or QColor(t("#dbe6ff")))
        c = self.out.textCursor(); c.movePosition(c.MoveOperation.End); c.insertText(text + "\n", fmt)
        self.out.setTextCursor(c); self.out.ensureCursorVisible()

    def _send(self):
        t = self.edit.text().strip()
        if t:
            self.history.append(t); self.hpos = len(self.history)
            self.line("> " + t, QColor(t("#5ee7ff")))
            self.submitted.emit(t)
        self.edit.clear()

    def keyPressEvent(self, e):
        super().keyPressEvent(e)
