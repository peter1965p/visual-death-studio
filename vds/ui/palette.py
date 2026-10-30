"""Befehlspalette und globale Suche (Strg+Q): Befehle, Dateien, Einstellungen und Text in Dateien in einem Eingabefeld.

Präfixe: `>` nur Befehle, `%` Text in Dateien, `@` Einstellungen, sonst Befehle, Dateien und Einstellungen gemischt."""
import os
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from .. import options

SKIP_DIRS = {".git", ".vds", "venv", ".venv", "node_modules", "__pycache__", "build", "dist", "target", "bin", "obj", ".idea", ".gradle", "vendor"}
MAX_FILES, MAX_HITS, MAX_SHOWN = 8000, 200, 60


def fuzzy(query: str, text: str) -> int | None:
    """Trefferwert (höher = besser) oder None, wenn nicht alle Buchstaben der Reihe nach vorkommen."""
    q, t = query.lower(), text.lower()
    if not q:
        return 0
    if q in t:
        return 1000 - t.index(q) * 3 - len(t) + (200 if t.endswith(q) or Path(text).name.lower().startswith(q) else 0)
    score, pos, prev = 0, 0, -2
    for ch in q:
        i = t.find(ch, pos)
        if i < 0:
            return None
        score += 10 + (15 if i == prev + 1 else 0) + (10 if i == 0 or t[i - 1] in " /._-›" else 0)
        prev, pos = i, i + 1
    return score - len(t) // 4


def collect_actions(menubar) -> list:
    """[(Pfad wie »Datei › Neu › Projekt«, Kürzel, QAction)] aller aktiven Menüeinträge."""
    out = []

    def walk(menu, trail):
        for a in menu.actions():
            if a.isSeparator():
                continue
            label = a.text().replace("&", "")
            if a.menu() is not None:
                walk(a.menu(), trail + [label])
            elif label and a.isEnabled():
                out.append((" › ".join(trail + [label]), a.shortcut().toString(), a))
    for top in menubar.actions():
        if top.menu() is not None:
            walk(top.menu(), [top.text().replace("&", "")])
    return out


def list_files(root: Path) -> list:
    """Relative Pfade aller Dateien des Projekts (ohne Build-, Umgebungs- und Versionsordner)."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git"))
        for f in sorted(files):
            out.append((Path(dirpath) / f).relative_to(root).as_posix())
            if len(out) >= MAX_FILES:
                return out
    return out


def search_text(root: Path, needle: str, limit: int = MAX_HITS) -> list:
    """[(relativer Pfad, Zeile, Text)] – Suche ohne Beachtung der Groß-/Kleinschreibung in Textdateien unter 1 MB."""
    hits, n = [], needle.lower()
    for rel in list_files(root):
        p = root / rel
        try:
            if p.stat().st_size > 1_000_000:
                continue
            data = p.read_bytes()
            if b"\0" in data[:4096]:
                continue
            for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if n in line.lower():
                    hits.append((rel, i, line.strip()[:160]))
                    if len(hits) >= limit:
                        return hits
        except OSError:
            continue
    return hits


class CommandPalette(QDialog):
    def __init__(self, win):
        super().__init__(win, Qt.Dialog | Qt.FramelessWindowHint)
        self.win = win
        self.setModal(True)
        self.setObjectName("palette")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self); lay.setContentsMargins(10, 10, 10, 10)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Befehl, Datei oder Einstellung suchen   (> Befehle · % Text in Dateien · @ Einstellungen)")
        self.hint = QLabel(); self.hint.setObjectName("sub")
        self.list = QListWidget(); self.list.setMinimumHeight(320)
        lay.addWidget(self.edit); lay.addWidget(self.list, 1); lay.addWidget(self.hint)
        self.edit.installEventFilter(self)
        self.edit.textChanged.connect(lambda _: self._timer.start())
        self.list.itemActivated.connect(self._run)
        self.list.itemClicked.connect(self._run)
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self.refresh)
        self._actions: list = []
        self._files: list = []

    def open(self, prefix: str = ""):
        self._actions = collect_actions(self.win.menuBar())
        self._files = list_files(self.win.root) if self.win.root.is_dir() else []
        self.edit.setText(prefix)
        self.refresh()
        g = self.win.geometry()
        self.move(g.center().x() - self.width() // 2, g.top() + 90)
        self.show(); self.edit.setFocus()

    def _add(self, label, detail, data):
        it = QListWidgetItem(f"{label}    {detail}" if detail else label)
        it.setData(Qt.UserRole, data)
        self.list.addItem(it)

    def refresh(self):
        text = self.edit.text()
        self.list.clear()
        mode, q = (text[0], text[1:].strip()) if text[:1] in (">", "%", "@") else ("", text.strip())
        if mode == "%":
            if len(q) < 2:
                self.hint.setText("Mindestens zwei Zeichen für die Textsuche eingeben.")
            else:
                hits = search_text(self.win.root, q)
                for rel, line, txt in hits:
                    self._add(f"{rel}:{line}", txt, ("goto", rel, line))
                self.hint.setText(f"{len(hits)} Treffer" + (" (begrenzt)" if len(hits) >= MAX_HITS else ""))
        else:
            ranked = []
            if mode in ("", ">"):
                for label, key, act in self._actions:
                    s = fuzzy(q, label)
                    if s is not None:
                        ranked.append((s + 5, label, key, ("action", act)))
            if mode in ("", "@"):
                for k in options.DEFAULTS:
                    s = fuzzy(q, k)
                    if s is not None:
                        ranked.append((s - (0 if mode else 40), f"Einstellung: {k}", str(options.get(k)), ("settings",)))
            if mode == "":
                for rel in self._files:
                    s = fuzzy(q, rel)
                    if s is not None:
                        ranked.append((s - 20, rel, "Datei", ("file", rel)))
            ranked.sort(key=lambda r: -r[0])
            for _, label, detail, data in ranked[:MAX_SHOWN]:
                self._add(label, detail, data)
            self.hint.setText(f"{len(ranked)} Treffer")
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run(self, item=None):
        item = item or self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole)
        self.accept()
        if data[0] == "action":
            data[1].trigger()
        elif data[0] == "file":
            self.win.docs.open(self.win.root / data[1])
        elif data[0] == "goto":
            self.win.goto(self.win.root / data[1], data[2], 1)
        elif data[0] == "settings":
            self.win.show_options()

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                row = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._run()
                return True
        return super().eventFilter(obj, ev)
