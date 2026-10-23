"""Refactoring-Hilfen für das Hauptfenster: Vorschau-Dialog, Anwenden von Änderungen (offene Editoren mit Undo, geschlossene Dateien direkt),
Textumbenennung und Wortsuche als Rückfall, wenn kein Language Server das kann."""
import difflib
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from .build.languages import lang_for
from .diff.changes import SKIP_DIRS
from .lsp.edits import apply_edits


def project_files(root: Path, lang_id: str | None, limit: int = 3000) -> list:
    """Quelldateien derselben Sprache im Projekt (ohne venv, node_modules, .git …)."""
    out = []
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts[:-1]):
            lg = lang_for(p)
            if lg and (lang_id is None or lg.id == lang_id):
                out.append(p)
                if len(out) >= limit:
                    break
    return out


def word_edits(files: list, old: str, new: str | None = None) -> dict:
    """Alle Vorkommen von `old` als ganzes Wort -> {Pfad: [(Zeile0, Spalte0, Zeile0, Spalte0, new)]}; new None = nur finden."""
    pat = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])")
    out: dict = {}
    for p in files:
        try:
            lines = p.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines):
            for m in pat.finditer(line):
                out.setdefault(str(p), []).append((i, m.start(), i, m.end(), new if new is not None else old))
    return out


def changed_lines(old: str, new: str) -> int:
    a, b = old.split("\n"), new.split("\n")
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal")


class PreviewDialog(QDialog):
    """Zeigt, welche Dateien geändert werden; einzelne lassen sich abwählen."""

    def __init__(self, parent, title: str, rows: list, root: Path):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 420)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Datei", "Geänderte Zeilen"]); self.tree.setColumnWidth(0, 440)
        for path, n in rows:
            try:
                rel = str(Path(path).relative_to(root))
            except ValueError:
                rel = path
            it = QTreeWidgetItem(self.tree, [rel, str(n)])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable); it.setCheckState(0, Qt.Checked); it.setData(0, Qt.UserRole, path)
        total = sum(n for _, n in rows)
        info = QLabel(f"{total} Zeile(n) in {len(rows)} Datei(en) werden geändert. Dateien, die nicht geöffnet sind, werden direkt auf der Platte geändert.")
        info.setWordWrap(True); info.setObjectName("sub")
        ok, cancel = QPushButton("Übernehmen"), QPushButton("Abbrechen")
        ok.setObjectName("primary"); ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(cancel); row.addWidget(ok)
        lay = QVBoxLayout(self); lay.addWidget(info); lay.addWidget(self.tree, 1); lay.addLayout(row)

    def selected(self) -> list:
        return [self.tree.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tree.topLevelItemCount())
                if self.tree.topLevelItem(i).checkState(0) == Qt.Checked]


def preview_rows(edits: dict) -> list:
    rows = []
    for path, es in edits.items():
        try:
            old = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rows.append((path, changed_lines(old, apply_edits(old, es))))
    return rows


def apply_edits_to_workspace(window, edits: dict) -> tuple:
    """Wendet Änderungen an: offene Editoren (rückgängig machbar) und Dateien auf der Platte. Gibt (Dateien, Fehler) zurück."""
    done, errors = 0, []
    for path, es in edits.items():
        p = Path(path)
        doc = window.docs.docs.get(p.resolve())
        try:
            if doc is not None and doc.kind == "code":
                ed = doc.editor
                new = apply_edits(ed.toPlainText(), es)
                if new != ed.toPlainText():
                    line = ed.textCursor().blockNumber()
                    c = QTextCursor(ed.document())
                    c.beginEditBlock(); c.select(QTextCursor.Document); c.insertText(new); c.endEditBlock()
                    c2 = ed.textCursor(); c2.setPosition(ed.document().findBlockByNumber(min(line, ed.blockCount() - 1)).position()); ed.setTextCursor(c2)
                done += 1
            else:
                old = p.read_text(encoding="utf-8")
                new = apply_edits(old, es)
                if new != old:
                    p.write_text(new, encoding="utf-8")
                done += 1
        except (OSError, UnicodeDecodeError) as e:
            errors.append(f"{p.name}: {e}")
    return done, errors
