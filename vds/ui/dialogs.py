"""Dialoge hinter den Menüs Projekt und Hilfe: Projekteigenschaften, Tastenkürzel, Werkzeug-Check, Erste Schritte, Lizenz."""
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from ..build import projects
from ..debug import tools as dbg_tools
from ..project import ProjectSettings

SKIP_DIRS = {".git", ".vds", ".venv", "venv", "node_modules", "__pycache__", "target", "build", "bin", "obj", ".idea", ".vscode"}


def project_files(root: Path, limit: int = 400) -> list:
    """Dateien des Projekts (relativ) als Auswahl für die Startdatei, ohne Build- und Abhängigkeitsordner."""
    out = []
    for p in sorted(Path(root).rglob("*")):
        if len(out) >= limit:
            break
        rel = p.relative_to(root)
        if p.is_file() and not any(part in SKIP_DIRS for part in rel.parts):
            out.append(rel.as_posix())
    return out


def _browse(edit: QLineEdit, parent, title, directory=False, start=""):
    path = QFileDialog.getExistingDirectory(parent, title, start) if directory else QFileDialog.getOpenFileName(parent, title, start)[0]
    if path:
        edit.setText(path)


class ProjectPropertiesDialog(QDialog):
    """Projekteigenschaften (.vds/project.json): Startdatei, Argumente, Arbeitsordner, Umgebung, Interpreter, Build-Befehle."""

    def __init__(self, root: Path, settings: ProjectSettings, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.setWindowTitle(f"Projekteigenschaften – {self.root.name}")
        self.resize(640, 560)
        s = settings
        self.startup = QComboBox(); self.startup.setEditable(True)
        self.startup.addItem("")
        self.startup.addItems(project_files(self.root))
        self.startup.setCurrentText(s.startup)
        self.args = QLineEdit(s.args); self.args.setPlaceholderText("z. B. --verbose eingabe.txt")
        self.cwd = QLineEdit(s.cwd); self.cwd.setPlaceholderText("leer = Ordner der Startdatei")
        self.python = QLineEdit(s.python); self.python.setPlaceholderText("leer = .venv des Projekts bzw. System-Python")
        self.env = QPlainTextEdit("\n".join(f"{k}={v}" for k, v in s.env.items())); self.env.setPlaceholderText("NAME=Wert (eine Variable pro Zeile)")
        self.env.setFixedHeight(90)
        self.build = QLineEdit(s.build_cmd); self.build.setPlaceholderText(self._auto_hint())
        self.clean = QLineEdit(s.clean_cmd); self.clean.setPlaceholderText("leer = automatisch bzw. Build-Ordner löschen")
        form = QFormLayout()
        form.addRow("Startdatei", self.startup)
        form.addRow("Argumente", self.args)
        form.addRow("Arbeitsordner", self._with_browse(self.cwd, "Arbeitsordner wählen", True))
        form.addRow("Python-Interpreter", self._with_browse(self.python, "Interpreter wählen", False))
        form.addRow("Umgebungsvariablen", self.env)
        form.addRow("Build-Befehl", self.build)
        form.addRow("Clean-Befehl", self.clean)
        note = QLabel("Der Build-Befehl läuft in einer Shell im Projektordner (&& und Variablen sind möglich). Ohne Eintrag erkennt Visual Death Studio "
                      "CMake, Make, Cargo, Go, .NET, Maven, Gradle und npm automatisch.")
        note.setWordWrap(True); note.setStyleSheet("color:#8fa3c7")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(note); lay.addStretch(); lay.addWidget(bb)

    def _auto_hint(self) -> str:
        bs = projects.detect(self.root)
        return f"leer = automatisch ({bs.name})" if bs else "leer = einzelne Datei kompilieren"

    def _with_browse(self, edit, title, directory):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        b = QPushButton("…"); b.setFixedWidth(34)
        b.clicked.connect(lambda: _browse(edit, self, title, directory, str(self.root)))
        h.addWidget(edit); h.addWidget(b)
        return w

    def result_settings(self, base: ProjectSettings) -> ProjectSettings:
        env = {}
        for line in self.env.toPlainText().splitlines():
            if "=" in line and line.split("=", 1)[0].strip():
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        return ProjectSettings(startup=self.startup.currentText().strip(), args=self.args.text().strip(), cwd=self.cwd.text().strip(), env=env,
                               python=self.python.text().strip(), build_cmd=self.build.text().strip(), clean_cmd=self.clean.text().strip(),
                               test_cmd=base.test_cmd)


class ShortcutsDialog(QDialog):
    """Alle Befehle mit Tastenkürzel, direkt aus den Menüaktionen gelesen (daher immer aktuell); durchsuchbar."""

    def __init__(self, menu_bar, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tastenkürzel"); self.resize(560, 620)
        rows = []
        for top in menu_bar.actions():
            if top.menu():
                self._collect(top.menu(), top.text().replace("&", ""), rows)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Menü", "Befehl", "Tastenkürzel"])
        self.table.verticalHeader().hide(); self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True); self.table.setColumnWidth(0, 100); self.table.setColumnWidth(1, 270)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        for menu, name, keys in sorted(rows, key=lambda r: (r[2] == "", r[0])):
            r = self.table.rowCount(); self.table.insertRow(r)
            for c, t in enumerate((menu, name, keys)):
                self.table.setItem(r, c, QTableWidgetItem(t))
        self.search = QLineEdit(); self.search.setPlaceholderText("Befehl oder Kürzel suchen …"); self.search.textChanged.connect(self._filter)
        lay = QVBoxLayout(self); lay.addWidget(self.search); lay.addWidget(self.table)

    def _collect(self, menu, title, rows):
        for a in menu.actions():
            if a.menu():
                self._collect(a.menu(), title, rows)
            elif not a.isSeparator() and a.text() and not a.isCheckable():
                rows.append((title, a.text().replace("&", ""), a.shortcut().toString(QKeySequence.NativeText)))

    def _filter(self, text):
        t = text.lower()
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, bool(t) and not any(t in (self.table.item(r, c).text().lower()) for c in range(3)))


# Programm, Zweck, Installationshinweis (Arch/CachyOS)
TOOLS = [
    ("python3", "Python ausführen", "sudo pacman -S python"), ("pylsp", "IntelliSense für Python", "pip install -r requirements.txt"),
    ("gcc", "C kompilieren", "sudo pacman -S gcc"), ("g++", "C++ kompilieren", "sudo pacman -S gcc"), ("gdb", "Debugger für C/C++", dbg_tools.HINTS["gdb"]),
    ("clangd", "IntelliSense für C/C++", "sudo pacman -S clang"), ("cmake", "CMake-Projekte", "sudo pacman -S cmake"), ("make", "Make-Projekte", "sudo pacman -S make"),
    ("node", "JavaScript/TypeScript ausführen und debuggen", dbg_tools.HINTS["node"]), ("npm", "npm-Projekte, Pakete", "sudo pacman -S npm"),
    ("typescript-language-server", "IntelliSense für JS/TS", "npm i -g typescript typescript-language-server"),
    ("go", "Go bauen", dbg_tools.HINTS["go"]), ("dlv", "Debugger für Go", dbg_tools.HINTS["dlv"]),
    ("rustc", "Rust kompilieren", "sudo pacman -S rust"), ("cargo", "Rust-Projekte", "sudo pacman -S rust"),
    ("dotnet", "C# bauen und ausführen", dbg_tools.HINTS["dotnet"]), ("netcoredbg", "Debugger für C#", dbg_tools.HINTS["netcoredbg"]),
    ("javac", "Java kompilieren", dbg_tools.HINTS["javac"]), ("java", "Java ausführen", dbg_tools.HINTS["javac"]), ("jdb", "Debugger für Java", dbg_tools.HINTS["jdb"]),
    ("mvn", "Maven-Projekte", "sudo pacman -S maven"), ("gradle", "Gradle-Projekte", "sudo pacman -S gradle"),
    ("git", "Versionsverwaltung, Änderungen-Ansicht", "sudo pacman -S git"), ("claude", "Claude-Chat und -Vervollständigung", "siehe claude.com/claude-code"),
]


def tool_report() -> list:
    """[(Programm, Zweck, Pfad|None, Hinweis)] – gefunden wird auch in ~/go/bin, ~/.local/bin und der venv dieser IDE."""
    venv_bin = Path(sys.executable).parent
    out = []
    for name, purpose, hint in TOOLS:
        path = dbg_tools.find(name) or (str(venv_bin / name) if (venv_bin / name).exists() else None)
        out.append((name, purpose, path, hint))
    return out


class ToolCheckDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installierte Werkzeuge"); self.resize(900, 620)
        rep = tool_report()
        self.table = QTableWidget(len(rep), 4)
        self.table.setHorizontalHeaderLabels(["", "Programm", "Wofür", "Pfad / Installation"])
        self.table.verticalHeader().hide(); self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for c, w in enumerate((28, 200, 290)):
            self.table.setColumnWidth(c, w)
        for r, (name, purpose, path, hint) in enumerate(rep):
            mark = QTableWidgetItem("✔" if path else "✘"); mark.setForeground(Qt.green if path else Qt.red); mark.setTextAlignment(Qt.AlignCenter)
            for c, it in enumerate((mark, QTableWidgetItem(name), QTableWidgetItem(purpose), QTableWidgetItem(path or hint))):
                self.table.setItem(r, c, it)
        found = sum(1 for x in rep if x[2])
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"{found} von {len(rep)} Werkzeugen gefunden. Fehlende sind nur nötig, wenn du die jeweilige Sprache oder Funktion nutzt."))
        lay.addWidget(self.table)


GETTING_STARTED = """
<h2>Erste Schritte</h2>
<ol>
<li><b>Projekt anlegen:</b> Datei → Neu → Projekt… (<code>Strg+Umschalt+N</code>). Der Assistent bietet Vorlagen für viele Sprachen;
&bdquo;Mit Claude erstellen&ldquo; baut ein Projekt aus deiner Beschreibung. Vorhandene Ordner öffnest du mit <i>Datei → Ordner öffnen</i>.</li>
<li><b>Programmieren:</b> IntelliSense (<code>Strg+Leertaste</code>), Definition (<code>F12</code>), Umbenennen (<code>F2</code>), Schnelle Aktionen (<code>Strg+.</code>).
Mit <code>Strg+Enter</code> vervollständigt Claude an der Cursorposition.</li>
<li><b>Formulare:</b> Datei → Neu → Formular… öffnet den Designer. Steuerelemente aus der Toolbox ins Formular ziehen, in GroupBox, Panel oder
TabWidget verschachteln und dort Layouts (vertikal, horizontal, Raster) einstellen. <code>F7</code> zeigt den Code, <code>Umschalt+F7</code> wieder den Designer.</li>
<li><b>Starten und Debuggen:</b> <code>F5</code> startet mit Debugger, <code>Strg+F5</code> ohne. Haltepunkte setzt du mit <code>F9</code> oder per Klick in den Rand.
Einzelschritte: <code>F10</code> / <code>F11</code> / <code>Umschalt+F11</code>.</li>
<li><b>Erstellen:</b> <i>Erstellen → Projekt erstellen</i> erkennt CMake, Make, Cargo, Go, .NET, Maven, Gradle und npm. Eigene Befehle trägst du unter
<i>Projekt → Eigenschaften</i> ein.</li>
<li><b>Testen:</b> Der Test-Explorer findet pytest-, unittest-, node-, Go-, Cargo- und dotnet-Tests.</li>
<li><b>Fehlt etwas?</b> <i>Hilfe → Installierte Werkzeuge prüfen</i> zeigt, welche Compiler, Debugger und Sprachserver gefunden wurden, und wie du fehlende installierst.</li>
</ol>
"""


class GettingStartedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Erste Schritte"); self.resize(640, 560)
        view = QTextBrowser(); view.setHtml(GETTING_STARTED)
        lay = QVBoxLayout(self); lay.addWidget(view)


class TextDialog(QDialog):
    """Einfache, schreibgeschützte Textansicht (Lizenz u. Ä.)."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(620, 480)
        view = QPlainTextEdit(text); view.setReadOnly(True)
        lay = QVBoxLayout(self); lay.addWidget(view)


def suggest_target(root: Path) -> str:
    """Passendes Designer-Ziel zum Projektordner: Vue/React aus package.json, sonst Java bei .java-Dateien, sonst Python/Qt."""
    import json as _json
    root = Path(root)
    try:
        pkg = _json.loads((root / "package.json").read_text(encoding="utf-8"))
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "vue" in deps or "nuxt" in deps:
            return "vue"
        if "react" in deps or "next" in deps:
            return "react"
    except (OSError, ValueError):
        pass
    if any(root.glob("*.java")) or (root / "src").is_dir() and any((root / "src").rglob("*.java")):
        return "java-swing"
    return "python-qt"


class NewFormDialog(QDialog):
    """Neues Formular: Name und Ausgabeziel (Python/Qt, Java Swing, React, Vue)."""

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        from ..designer import targets
        self.setWindowTitle("Neues Formular"); self.resize(440, 160)
        self.name = QLineEdit("Form1")
        self.target = QComboBox()
        for tid, label in targets.LABELS.items():
            self.target.addItem(label, tid)
        self.target.setCurrentIndex(max(0, self.target.findData(suggest_target(root))))
        form = QFormLayout()
        form.addRow("Name", self.name); form.addRow("Zielplattform", self.target)
        hint = QLabel("Der Designer ist für alle Ziele gleich; erzeugt wird Code für die gewählte Plattform. Das Ziel lässt sich später in den Formular-Eigenschaften ändern.")
        hint.setWordWrap(True); hint.setStyleSheet("color:#8fa3c7")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(hint); lay.addWidget(bb)

    def values(self) -> tuple:
        return self.name.text().strip(), self.target.currentData()
