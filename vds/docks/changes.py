"""Änderungen-Panel: Tab „Claude“ (Review der KI-Änderungen mit Behalten/Zurücksetzen) und Tab „Git“ (Status, Stage, Commit)."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from ..diff import changes as C
from ..theme import t

STATUS_COLOR = {k: t(v) for k, v in {"M": "#ffc474", "A": "#3dffa1", "D": "#ff4d6d", "?": "#3dffa1"}.items()}
STATUS_NAME = {"M": "geändert", "A": "neu", "D": "gelöscht"}


class DiffRequest:
    """Beschreibt, was im Diff-Tab gezeigt werden soll."""
    def __init__(self, key, title, left, right, ltitle, rtitle, filename, left_path=None, right_path=None):
        self.key, self.title, self.left, self.right = key, title, left, right
        self.ltitle, self.rtitle, self.filename = ltitle, rtitle, filename
        self.left_path, self.right_path = left_path, right_path
        self.left_apply = self.right_apply = None   # optional: eigene Schreib-Callbacks statt Dateipfaden


class ChangesPanel(QWidget):
    diffRequested = Signal(object)        # DiffRequest
    filesChanged = Signal()               # Dateien auf der Platte wurden verändert (Editor neu laden)
    pendingChanged = Signal(int)          # Anzahl offener Claude-Änderungen

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.snapshot: dict | None = None
        self.claude_changes: list = []
        self.top: Path | None = None
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_claude(), "Claude")
        self.tabs.addTab(self._build_git(), "Git")
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda i: i == 1 and self.refresh_git())

    def set_root(self, root: Path):
        self.root, self.snapshot, self.claude_changes = Path(root), None, []
        self._fill_claude()
        self.refresh_git()

    # ================= Claude-Review =================================================================
    def _build_claude(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(6, 6, 6, 6)
        self.c_info = QLabel(); self.c_info.setWordWrap(True); self.c_info.setObjectName("sub")
        self.c_list = QListWidget(); self.c_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.c_list.itemDoubleClicked.connect(lambda it: self._open_claude(it.data(Qt.UserRole)))
        self.c_list.setContextMenuPolicy(Qt.CustomContextMenu); self.c_list.customContextMenuRequested.connect(self._claude_menu)
        row = QHBoxLayout()
        self.b_keep, self.b_revert = QPushButton("Behalten"), QPushButton("Zurücksetzen")
        self.b_keep_all, self.b_revert_all = QPushButton("Alle behalten"), QPushButton("Alle zurücksetzen")
        self.b_keep.clicked.connect(lambda: self._keep(self._selected_claude()))
        self.b_revert.clicked.connect(lambda: self._revert(self._selected_claude()))
        self.b_keep_all.clicked.connect(lambda: self._keep(self.claude_changes))
        self.b_revert_all.clicked.connect(lambda: self._revert(self.claude_changes))
        row.addWidget(self.b_keep); row.addWidget(self.b_revert)
        row2 = QHBoxLayout(); row2.addWidget(self.b_keep_all); row2.addWidget(self.b_revert_all)
        lay.addWidget(self.c_info); lay.addWidget(self.c_list, 1); lay.addLayout(row); lay.addLayout(row2)
        return w

    def begin_claude_run(self):
        """Vor einem Claude-Lauf: Ausgangszustand merken (bleibt bestehen, solange Änderungen unbearbeitet sind)."""
        if self.snapshot is None or not self.claude_changes:
            self.snapshot = C.take_snapshot(self.root)

    def end_claude_run(self):
        self.refresh_claude()
        if self.claude_changes:
            self.tabs.setCurrentIndex(0)

    def refresh_claude(self):
        self.claude_changes = C.diff_snapshot(self.root, self.snapshot) if self.snapshot is not None else []
        self._fill_claude()

    def _fill_claude(self):
        self.c_list.clear()
        for ch in self.claude_changes:
            it = QListWidgetItem(f"{ch.status}   {ch.rel}")
            it.setForeground(QColor(STATUS_COLOR[ch.status])); it.setData(Qt.UserRole, ch)
            it.setToolTip(f"{STATUS_NAME[ch.status]} – Doppelklick zeigt die Änderungen")
            self.c_list.addItem(it)
        n = len(self.claude_changes)
        self.c_info.setText(f"{n} Datei(en) von Claude geändert – prüfe die Änderungen per Doppelklick." if n
                            else "Keine ausstehenden Änderungen von Claude.")
        for b in (self.b_keep, self.b_revert, self.b_keep_all, self.b_revert_all):
            b.setEnabled(n > 0)
        self.pendingChanged.emit(n)

    def _selected_claude(self):
        return [i.data(Qt.UserRole) for i in self.c_list.selectedItems()]

    def _claude_menu(self, pos):
        m = QMenu(self)
        m.addAction("Änderungen anzeigen", lambda: [self._open_claude(c) for c in self._selected_claude()])
        m.addAction("Behalten", lambda: self._keep(self._selected_claude()))
        m.addAction("Zurücksetzen", lambda: self._revert(self._selected_claude()))
        m.exec(self.c_list.viewport().mapToGlobal(pos))

    def _open_claude(self, ch):
        p = self.root / ch.rel
        cur = C.read_text(p) if p.exists() else ""
        self.diffRequested.emit(DiffRequest(f"claude:{ch.rel}", f"{Path(ch.rel).name} (Claude)", ch.old or "", cur or "",
                                            "Vor Claude", "Aktuell", ch.rel, right_path=p))

    def _keep(self, changes):
        for ch in changes:
            if ch.status == "D":
                self.snapshot.pop(ch.rel, None)
            else:
                self.snapshot[ch.rel] = ch.new
        self.refresh_claude()

    def _revert(self, changes):
        if not changes:
            return
        if QMessageBox.question(self, "Zurücksetzen", f"{len(changes)} Datei(en) auf den Stand vor Claude zurücksetzen?") != QMessageBox.Yes:
            return
        for ch in changes:
            p = self.root / ch.rel
            if ch.status == "A":
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(ch.old or "", encoding="utf-8")
        self.refresh_claude()
        self.filesChanged.emit()

    # ================= Git ========================================================================
    def _build_git(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(6, 6, 6, 6)
        self.g_info = QLabel(); self.g_info.setObjectName("sub"); self.g_info.setWordWrap(True)
        self.g_list = QListWidget(); self.g_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.g_list.itemDoubleClicked.connect(lambda it: self._open_git(it.data(Qt.UserRole)))
        self.g_list.setContextMenuPolicy(Qt.CustomContextMenu); self.g_list.customContextMenuRequested.connect(self._git_menu)
        self.g_msg = QPlainTextEdit(); self.g_msg.setPlaceholderText("Commit-Nachricht"); self.g_msg.setFixedHeight(54)
        r1 = QHBoxLayout()
        self.b_refresh, self.b_stage, self.b_unstage = QPushButton("Aktualisieren"), QPushButton("Stagen"), QPushButton("Unstagen")
        self.b_refresh.clicked.connect(self.refresh_git)
        self.b_stage.clicked.connect(lambda: self._git_op("stage"))
        self.b_unstage.clicked.connect(lambda: self._git_op("unstage"))
        for b in (self.b_refresh, self.b_stage, self.b_unstage):
            r1.addWidget(b)
        self.b_commit = QPushButton("Commit"); self.b_commit.clicked.connect(self._commit)
        self.b_init = QPushButton("Repository initialisieren"); self.b_init.clicked.connect(self._init)
        lay.addWidget(self.g_info); lay.addWidget(self.g_list, 1); lay.addLayout(r1); lay.addWidget(self.g_msg); lay.addWidget(self.b_commit); lay.addWidget(self.b_init)
        return w

    def refresh_git(self):
        self.top = C.toplevel(self.root) if self.root.exists() else None
        self.g_list.clear()
        has = self.top is not None
        for w in (self.g_list, self.g_msg, self.b_stage, self.b_unstage, self.b_commit):
            w.setVisible(has)
        self.b_init.setVisible(not has)
        if not has:
            self.g_info.setText("Dieser Ordner ist kein Git-Repository.")
            return
        entries = C.status(self.top)
        self.g_info.setText(f"Branch: {C.branch(self.top)}   ·   {len(entries)} Änderung(en)")
        for e in entries:
            it = QListWidgetItem(f"{e.label}   {e.rel}")
            it.setForeground(QColor("#3dffa1" if e.staged and not e.unstaged else STATUS_COLOR.get(e.x if e.x != " " else e.y, "#ffc474")))
            it.setData(Qt.UserRole, e)
            it.setToolTip("gestaged" if e.staged and not e.unstaged else "teilweise gestaged" if e.staged else "nicht gestaged")
            self.g_list.addItem(it)

    def _sel_git(self):
        return [i.data(Qt.UserRole) for i in self.g_list.selectedItems()]

    def _git_menu(self, pos):
        m = QMenu(self)
        m.addAction("Änderungen anzeigen", lambda: [self._open_git(e) for e in self._sel_git()])
        m.addAction("Stagen", lambda: self._git_op("stage")); m.addAction("Unstagen", lambda: self._git_op("unstage"))
        m.addSeparator(); m.addAction("Änderungen verwerfen…", self._discard)
        m.exec(self.g_list.viewport().mapToGlobal(pos))

    def _git_op(self, op):
        es = self._sel_git()
        if es:
            rc, out = (C.stage if op == "stage" else C.unstage)(self.top, [e.rel for e in es])
            if rc:
                QMessageBox.warning(self, "Git", out.strip())
            self.refresh_git()

    def _discard(self):
        es = self._sel_git()
        if es and QMessageBox.question(self, "Verwerfen", f"Änderungen an {len(es)} Datei(en) unwiderruflich verwerfen?") == QMessageBox.Yes:
            rc, out = C.discard(self.top, es)
            if rc:
                QMessageBox.warning(self, "Git", out.strip())
            self.refresh_git(); self.filesChanged.emit()

    def _commit(self):
        msg = self.g_msg.toPlainText().strip()
        if not msg:
            return QMessageBox.information(self, "Commit", "Bitte eine Commit-Nachricht eingeben.")
        rc, out = C.commit(self.top, msg)
        if rc:
            return QMessageBox.warning(self, "Commit", out.strip() or "Commit fehlgeschlagen (nichts gestaged?).")
        self.g_msg.clear(); self.refresh_git()

    def _init(self):
        rc, out = C.git(self.root, "init", "-q")
        if rc:
            QMessageBox.warning(self, "Git", out.strip())
        self.refresh_git()

    def _open_git(self, e):
        p = self.top / e.rel
        head = C.head_text(self.top, e.rel) if e.x != "?" else ""
        cur = (C.read_text(p) or "") if p.exists() else ""
        self.diffRequested.emit(DiffRequest(f"git:{e.rel}", f"{p.name} (HEAD)", head, cur, "HEAD", "Arbeitskopie", e.rel, right_path=p))
