"""Test-Explorer: Baum aller Tests mit Status, Filter, Suche, Fehlerdetails und Aktionen (ausführen, debuggen, zum Test springen)."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSplitter, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..icons import icon

ID = Qt.UserRole
IDS = Qt.UserRole + 1
ICON = {"passed": "t-pass", "failed": "t-fail", "error": "t-fail", "skipped": "t-skip", "running": "t-run", None: "t-none"}
FILTERS = ["Alle", "Fehlgeschlagen", "Bestanden", "Übersprungen", "Nicht ausgeführt"]


class TestExplorer(QWidget):
    __test__ = False
    jumpTo = Signal(str, int)                 # absoluter Pfad, Zeile
    debugRequested = Signal(str, list)        # Framework-Name, Test-IDs

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.svc = service
        self.status: dict = {}                # id -> Status (inkl. "running")
        self.leaves: dict = {}
        self.b_run = QPushButton("▶  Alle ausführen"); self.b_run.setObjectName("primary")
        self.b_failed = QPushButton("Fehlgeschlagene")
        self.b_refresh = QToolButton(); self.b_refresh.setText("↻"); self.b_refresh.setToolTip("Tests neu entdecken")
        self.b_stop = QToolButton(); self.b_stop.setText("■"); self.b_stop.setToolTip("Lauf abbrechen")
        self.filter = QComboBox(); self.filter.addItems(FILTERS)
        self.search = QLineEdit(placeholderText="Tests suchen …")
        self.summary = QLabel(); self.summary.setObjectName("sub")
        top = QHBoxLayout(); top.setContentsMargins(6, 4, 6, 0)
        for w in (self.b_run, self.b_failed, self.b_refresh, self.b_stop):
            top.addWidget(w)
        top.addWidget(self.filter); top.addWidget(self.search, 1); top.addWidget(self.summary)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Test", "Dauer"]); self.tree.setColumnWidth(0, 380)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail = QPlainTextEdit(readOnly=True)
        self.detail.setPlaceholderText("Wähle einen Test, um Fehlermeldung und Ablaufverfolgung zu sehen.")
        split = QSplitter(Qt.Horizontal); split.addWidget(self.tree); split.addWidget(self.detail); split.setSizes([520, 480])
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)
        lay.addLayout(top); lay.addWidget(split, 1)
        self.b_run.clicked.connect(lambda: self.svc.run(None))
        self.b_failed.clicked.connect(self.run_failed)
        self.b_refresh.clicked.connect(self.svc.discover)
        self.b_stop.clicked.connect(self.svc.cancel)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        self.search.textChanged.connect(self.apply_filter)
        self.tree.currentItemChanged.connect(lambda cur, _p: self._show_detail(cur))
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._jump(it))
        self.tree.customContextMenuRequested.connect(self._menu)
        self.svc.discovered.connect(self.build)
        self.svc.resultsChanged.connect(self._results)
        self.svc.started.connect(self._started)
        self.svc.running.connect(self._busy)
        self._busy(False)

    # --- Aufbau -------------------------------------------------------------------------------------------------------
    def build(self, cases: list):
        self.tree.clear(); self.leaves = {}; self.status = {}
        groups: dict = {}

        def group(path: tuple) -> QTreeWidgetItem:
            if path in groups:
                return groups[path]
            parent = group(path[:-1]) if len(path) > 1 else self.tree.invisibleRootItem()
            it = QTreeWidgetItem(parent, [path[-1], ""])
            it.setIcon(0, icon("t-none"))
            it.setData(0, IDS, [])
            groups[path] = it
            return it
        for c in cases:
            path = ((c.file,) if c.file else ()) + tuple(c.group)
            parent = group(path) if path else self.tree.invisibleRootItem()
            leaf = QTreeWidgetItem(parent, [c.name, ""])
            leaf.setIcon(0, icon("t-none")); leaf.setData(0, ID, c.id)
            self.leaves[c.id] = leaf
        for it in groups.values():
            it.setExpanded(len(groups) < 40)
        self._collect_ids(self.tree.invisibleRootItem())
        self._update_summary()
        self.apply_filter()

    def _collect_ids(self, item) -> list:
        ids = []
        for i in range(item.childCount()):
            ch = item.child(i)
            ids += [ch.data(0, ID)] if ch.data(0, ID) else self._collect_ids(ch)
        if item is not self.tree.invisibleRootItem():
            item.setData(0, IDS, ids)
        return ids

    # --- Zustand ------------------------------------------------------------------------------------------------------------
    def _busy(self, busy: bool):
        self.b_run.setEnabled(not busy); self.b_failed.setEnabled(not busy); self.b_refresh.setEnabled(not busy); self.b_stop.setEnabled(busy)
        self.b_run.setText("Läuft …" if busy else "▶  Alle ausführen")

    def _started(self, ids: list):
        for i in ids:
            self.status[i] = "running"
        self._refresh_icons()

    def _results(self, res: dict):
        for i, r in res.items():
            self.status[i] = r.status
            leaf = self.leaves.get(i)
            if leaf:
                leaf.setText(1, f"{r.seconds * 1000:.0f} ms" if r.seconds else "")
        self._refresh_icons()
        self._show_detail(self.tree.currentItem())

    def _refresh_icons(self):
        for i, leaf in self.leaves.items():
            leaf.setIcon(0, icon(ICON.get(self.status.get(i), "t-none")))
        self._rollup(self.tree.invisibleRootItem())
        self._update_summary()
        self.apply_filter()

    def _rollup(self, item) -> list:
        sts = []
        for i in range(item.childCount()):
            ch = item.child(i)
            sts += [self.status.get(ch.data(0, ID))] if ch.data(0, ID) else self._rollup(ch)
        if item is not self.tree.invisibleRootItem():
            s = ("running" if "running" in sts else "failed" if any(x in ("failed", "error") for x in sts)
                 else "passed" if sts and all(x == "passed" for x in sts) else "skipped" if sts and all(x in ("passed", "skipped") for x in sts) and "skipped" in sts else None)
            item.setIcon(0, icon(ICON.get(s, "t-none")))
        return sts

    def _update_summary(self):
        n = len(self.leaves)
        c = {k: sum(1 for i in self.leaves if self.status.get(i) == k) for k in ("passed", "failed", "skipped")}
        c["failed"] += sum(1 for i in self.leaves if self.status.get(i) == "error")
        self.summary.setText(f"{n} Tests  ·  ✓ {c['passed']}  ✕ {c['failed']}  – {c['skipped']}" if n else "Keine Tests gefunden")

    def apply_filter(self):
        mode, q = self.filter.currentIndex(), self.search.text().strip().lower()
        want = {1: ("failed", "error"), 2: ("passed",), 3: ("skipped",), 4: (None,)}.get(mode)

        def visit(item) -> bool:
            if item.data(0, ID):
                st = self.status.get(item.data(0, ID))
                show = (want is None or st in want) and (not q or q in item.text(0).lower() or q in (item.parent().text(0).lower() if item.parent() else ""))
                item.setHidden(not show)
                return show
            any_shown = False
            for i in range(item.childCount()):
                any_shown |= visit(item.child(i))
            item.setHidden(not any_shown)
            return any_shown
        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    # --- Details & Aktionen ------------------------------------------------------------------------------------------------------
    def _show_detail(self, item):
        if not item:
            return self.detail.clear()
        tid = item.data(0, ID)
        r = self.svc.results.get(tid) if tid else None
        if r is None:
            ids = item.data(0, IDS) or []
            bad = [i for i in ids if self.svc.results.get(i) and self.svc.results[i].status in ("failed", "error")]
            return self.detail.setPlainText("\n\n".join(f"✕ {i}\n{self.svc.results[i].message}" for i in bad[:20]) if bad else "")
        self.detail.setPlainText(f"{r.status.upper()}  {tid}\n\n{r.message}" if r.message else f"{r.status.upper()}  {tid}")

    def _ids_of(self, item) -> list:
        return [item.data(0, ID)] if item.data(0, ID) else list(item.data(0, IDS) or [])

    def run_failed(self):
        self.svc.run([i for i, s in self.status.items() if s in ("failed", "error")] or None)

    def _jump(self, item):
        ids = self._ids_of(item)
        if not ids or ids[0] not in self.svc.cases:
            return
        c = self.svc.cases[ids[0]][1]
        if c.file:
            self.jumpTo.emit(str(self.svc.root / c.file), c.line if item.data(0, ID) else 1)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        ids = self._ids_of(it)
        m = QMenu(self)
        m.addAction("Ausführen", lambda: self.svc.run(ids))
        fw = self.svc.cases[ids[0]][0] if ids and ids[0] in self.svc.cases else None
        if fw and fw.can_debug:
            m.addAction("Debuggen", lambda: self.debugRequested.emit(fw.name, ids))
        m.addAction("Gehe zu Test", lambda: self._jump(it))
        m.exec(self.tree.viewport().mapToGlobal(pos))
