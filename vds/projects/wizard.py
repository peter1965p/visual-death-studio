"""Assistent „Neues Projekt erstellen“ im Stil von Visual Studio 2022 (4 Seiten; Vorlagen mit Scaffold-Befehl wie Laravel laufen im Hintergrund)."""
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QStackedWidget, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from ..ai import backend
from ..theme import t as tc
from ..branding import SETTINGS_APP, SETTINGS_ORG
from ..ai.prompts import LANG_HINTS, SYSTEM_APP, SYSTEM_PROJECT, parse_main, project_prompt
from ..docks.explorer import LANG_COLOR
from . import apps
from .templates import BY_ID, TEMPLATES, Template, create_project, finish_project, scaffold_command, scaffold_failed

COLORS = {**LANG_COLOR, "claude": "#d97757"}
ABBR = {"claude": "✦", "typescript": "TS", "vue": "Vu", "php": "PHP", "python": "Py", "c": "C", "cpp": "C++", "csharp": "C#", "rust": "Rs", "go": "Go", "javascript": "JS", "java": "Jv", "shell": "sh", "": "＋"}
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
OPTION_LABELS = {"essentials": "Linux-Essentials einbinden (Zwischenablage, Geräteinfo, Einstellungen …)", "git": "Git-Repository initialisieren (inkl. .gitignore)", "readme": "README.md erstellen",
                 "venv": "Virtuelle Python-Umgebung (.venv) anlegen"}
CSS = tc("""
QLabel#title { font-size: 22px; font-weight: 300; }
QLabel#sub { color: #8fa3c7; }
QLabel#err { color: #ff7a93; }
QListWidget { background: rgba(255,255,255,0.035); border: 1px solid rgba(0,229,255,0.22); border-radius: 12px; }
QListWidget::item { border-bottom: 1px solid rgba(0,229,255,0.10); border-radius: 0; margin: 0; }
QListWidget::item:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,229,255,0.30), stop:1 rgba(180,76,255,0.26)); }
QListWidget::item:hover:!selected { background: rgba(0,229,255,0.08); }
QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00e5ff, stop:1 #b44cff); border: none; color: #05060f; font-weight: 600; min-width: 90px; }
QPushButton#primary:disabled { background: #3a3d41; border-color: #3a3d41; color: #888; }
""")


def badge(lang_id: str, size=40) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(COLORS.get(lang_id, "#6d6d6d")).darker(160))
    p.setPen(QColor(COLORS.get(lang_id, "#6d6d6d")))
    p.drawRoundedRect(1, 1, size - 2, size - 2, 6, 6)
    f = QFont(); f.setBold(True); f.setPixelSize(size // 2 - 1); p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, ABBR.get(lang_id, "?"))
    p.end()
    return pm


_PHP_MODULES: set | None = None


def _php_has(ext: str) -> bool:
    """Ist die PHP-Erweiterung geladen? (php -m, einmal pro Sitzung)"""
    global _PHP_MODULES
    if _PHP_MODULES is None:
        import subprocess
        try:
            out = subprocess.run(["php", "-m"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        _PHP_MODULES = {l.strip().lower() for l in out.splitlines()}
    return ext.lower() in _PHP_MODULES


class TemplateDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 72)

    def paint(self, p, option, index):
        t: Template = index.data(Qt.UserRole)
        self.initStyleOption(option, index)
        option.text = ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, p, option.widget)
        r = option.rect
        p.drawPixmap(r.x() + 12, r.y() + 16, badge(t.lang_id))
        f = QFont(option.font); f.setPointSize(11); f.setBold(True)
        p.setFont(f); p.setPen(QColor(tc("#f1f1f1")))
        p.drawText(QRect(r.x() + 66, r.y() + 8, r.width() - 80, 20), Qt.AlignVCenter, t.name)
        f.setBold(False); f.setPointSize(9); p.setFont(f); p.setPen(QColor(tc("#9d9d9d")))
        p.drawText(QRect(r.x() + 66, r.y() + 29, r.width() - 80, 18), Qt.AlignVCenter, t.description)
        x = r.x() + 66
        for tag in (t.lang, t.kind):
            w = p.fontMetrics().horizontalAdvance(tag) + 14
            p.setPen(QColor(tc("#5a5a5e"))); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(x, r.y() + 49, w, 16, 3, 3)
            p.setPen(QColor(tc("#c5c5c5"))); p.drawText(QRect(x, r.y() + 49, w, 16), Qt.AlignCenter, tag)
            x += w + 6


class NewProjectDialog(QDialog):
    def __init__(self, parent=None, default_location: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Neues Projekt erstellen")
        self.resize(900, 640)
        self.setStyleSheet(CSS)
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.tpl: Template | None = None
        self.result_data = None          # (Projektordner, Hauptdatei, Protokoll)
        loc = self.settings.value("new_project_location") or str(default_location or Path.home())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_choose())
        self.stack.addWidget(self._page_configure(loc))
        self.stack.addWidget(self._page_options())
        self.stack.addWidget(self._page_progress())
        self.claude = backend.make_agent(self)
        self.claude.text.connect(lambda t: self.ai_log.appendPlainText("\n".join(l for l in t.strip().splitlines() if not l.startswith("MAIN:")).strip() + "\n"))
        self.claude.tool.connect(lambda t: self.ai_log.appendPlainText("⚙ " + t))
        self.claude.finished.connect(self._ai_finished)
        self._base = None
        self.proc: QProcess | None = None            # laufender Scaffold-Befehl (z. B. composer create-project)
        self.pip: QProcess | None = None             # pip install -r requirements.txt im neuen .venv
        self._opts: dict = {}
        self._scaffold = None                        # (Zielordner, existierte vorher, Optionen, Beschreibung)
        self.back = QPushButton("Zurück"); self.next = QPushButton("Weiter"); self.next.setObjectName("primary")
        cancel = QPushButton("Abbrechen")
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next.clicked.connect(self._next)
        cancel.clicked.connect(self._cancel)
        self.cancel = cancel
        bar = QHBoxLayout(); bar.addStretch(); [bar.addWidget(b) for b in (self.back, self.next, cancel)]
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 20, 24, 16); lay.addWidget(self.stack); lay.addLayout(bar)
        self._filter()
        self._go(0)

    # --- Seite 1: Vorlage wählen -------------------------------------------------------
    def _page_choose(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Neues Projekt erstellen"); t.setObjectName("title"); lay.addWidget(t)
        row = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Nach Vorlagen suchen (Alt+S)")
        self.f_lang, self.f_kind = QComboBox(), QComboBox()
        self.f_lang.addItem("Alle Sprachen"); self.f_kind.addItem("Alle Projekttypen")
        self.f_lang.addItems(sorted({t.lang for t in TEMPLATES})); self.f_kind.addItems(sorted({t.kind for t in TEMPLATES}))
        row.addWidget(self.search, 3); row.addWidget(self.f_lang, 1); row.addWidget(self.f_kind, 1)
        lay.addLayout(row)
        self.list = QListWidget(); self.list.setItemDelegate(TemplateDelegate(self.list)); self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        lay.addWidget(self.list, 1)
        self.search.textChanged.connect(self._filter); self.f_lang.currentIndexChanged.connect(self._filter); self.f_kind.currentIndexChanged.connect(self._filter)
        self.list.currentItemChanged.connect(lambda cur, _p: self._select(cur))
        self.list.itemDoubleClicked.connect(lambda _i: self._next())
        return w

    def _filter(self):
        q = self.search.text().lower()
        lang = self.f_lang.currentText() if self.f_lang.currentIndex() else None
        kind = self.f_kind.currentText() if self.f_kind.currentIndex() else None
        self.list.clear()
        for t in TEMPLATES:
            if (lang and t.lang != lang) or (kind and t.kind != kind) or q not in f"{t.name} {t.description} {t.lang} {t.kind}".lower():
                continue
            it = QListWidgetItem(); it.setData(Qt.UserRole, t); self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._select(None)

    def _select(self, item):
        self.tpl = item.data(Qt.UserRole) if item else None
        self.next.setEnabled(self.tpl is not None and self.stack.currentIndex() == 0)

    # --- Seite 2: konfigurieren -----------------------------------------------------------
    def _page_configure(self, loc):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Neues Projekt konfigurieren"); t.setObjectName("title"); lay.addWidget(t)
        self.cfg_tpl = QLabel(); self.cfg_tpl.setObjectName("sub"); lay.addWidget(self.cfg_tpl)
        lay.addSpacing(16)
        form = QFormLayout(); form.setLabelAlignment(Qt.AlignRight); form.setVerticalSpacing(12)
        self.name = QLineEdit("Projekt1")
        self.location = QLineEdit(loc)
        browse = QPushButton("…"); browse.setFixedWidth(32); browse.clicked.connect(self._browse)
        loc_row = QHBoxLayout(); loc_row.addWidget(self.location); loc_row.addWidget(browse)
        form.addRow("Projektname", self.name); form.addRow("Speicherort", loc_row)
        lay.addLayout(form)
        self.preview = QLabel(); self.preview.setObjectName("sub"); self.preview.setWordWrap(True)
        self.err = QLabel(); self.err.setObjectName("err"); self.err.setWordWrap(True)
        lay.addSpacing(8); lay.addWidget(self.preview); lay.addWidget(self.err); lay.addStretch()
        self.name.textChanged.connect(self._validate); self.location.textChanged.connect(self._validate)
        return w

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Speicherort wählen", self.location.text())
        if d:
            self.location.setText(d)

    def _validate(self):
        name, loc = self.name.text().strip(), Path(self.location.text().strip() or ".").expanduser()
        target = loc / name
        err = ""
        if not NAME_RE.match(name):
            err = "Der Projektname darf nur Buchstaben, Ziffern, _ . - enthalten und nicht mit einer Ziffer beginnen."
        elif not loc.is_dir():
            err = "Der Speicherort existiert nicht."
        elif target.exists() and any(target.iterdir()):
            err = f"'{target}' existiert bereits und ist nicht leer."
        self.err.setText(err)
        self.preview.setText(f"Das Projekt wird erstellt in: {target}")
        if self.stack.currentIndex() == 1:
            self.next.setEnabled(not err)

    # --- Seite 3: Zusatzinformationen -------------------------------------------------------
    def _page_options(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Zusätzliche Informationen"); t.setObjectName("title"); lay.addWidget(t)
        self.opt_tpl = QLabel(); self.opt_tpl.setObjectName("sub"); lay.addWidget(self.opt_tpl)
        lay.addSpacing(16)
        self.app_box = QWidget(); af = QFormLayout(self.app_box); af.setContentsMargins(0, 0, 0, 0); af.setLabelAlignment(Qt.AlignRight)
        self.app = QComboBox(); self.tech = QComboBox()
        self.app_info = QLabel(); self.app_info.setObjectName("sub")
        af.addRow("Anwendung", self.app); af.addRow("Technik", self.tech); af.addRow("", self.app_info)
        lay.addWidget(self.app_box)
        self.app.currentIndexChanged.connect(self._app_changed); self.tech.currentIndexChanged.connect(self._tech_changed)
        self._auto_desc = ""
        self.checks = {k: QCheckBox(v) for k, v in OPTION_LABELS.items()}
        for c in self.checks.values():
            lay.addWidget(c)
        lay.addSpacing(8)
        self.desc_label = QLabel(); lay.addWidget(self.desc_label)
        self.lang_combo = QComboBox(); self.lang_combo.addItems(list(LANG_HINTS))
        lay.addWidget(self.lang_combo)
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText("z. B. „Ein Aufgabenlisten-Programm mit Fenster, in dem man Aufgaben hinzufügen, abhaken und löschen kann. "
                                     "Die Aufgaben sollen in einer JSON-Datei gespeichert werden.“")
        lay.addWidget(self.desc, 1)
        self.ai_hint = QLabel(); self.ai_hint.setObjectName("sub"); self.ai_hint.setWordWrap(True); lay.addWidget(self.ai_hint)
        self.tools = QLabel(); self.tools.setObjectName("sub"); self.tools.setWordWrap(True)
        lay.addWidget(self.tools)
        self.desc.textChanged.connect(self._check_desc)
        return w

    def _is_ai(self):
        return self.tpl is not None and self.tpl.id == "claude"

    def _is_app(self):
        return self.tpl is not None and self.tpl.id == "app"

    @property
    def eff(self) -> Template:
        """Vorlage, die tatsächlich angelegt wird: bei „Fertige Anwendung“ das Grundgerüst der gewählten Technik."""
        if self._is_app() and self.tech.currentData():
            return BY_ID[self.tech.currentData()]
        return self.tpl

    def _app_changed(self, *_):
        a = apps.BY_ID.get(self.app.currentData() or "")
        if not a:
            return
        prev = self.tech.currentData()
        self.tech.blockSignals(True); self.tech.clear()
        for tid in a.techs:
            self.tech.addItem(apps.TECH_LABEL[tid], tid)
        self.tech.setCurrentIndex(max(0, self.tech.findData(prev)))
        self.tech.blockSignals(False)
        self.app_info.setText(a.blurb)
        self._tech_changed()

    def _tech_changed(self, *_):
        if not (self._is_app() and self.app.currentData() and self.tech.currentData()):
            return
        eff = self.eff
        for k, c in self.checks.items():
            c.setVisible(k in eff.options)
        self.opt_tpl.setText(f"{self.tpl.name}   ·   {eff.name}")
        self.tools.setText(self._tool_hint())
        text = apps.prompt(self.app.currentData(), self.tech.currentData())
        if self.desc.toPlainText().strip() in ("", self._auto_desc):          # selbst geänderten Auftrag nicht überschreiben
            self.desc.setPlainText(text)
        self._auto_desc = text.strip()

    def _check_desc(self):
        if self.stack.currentIndex() == 2:
            need = self._is_ai() or self._is_app()
            self.next.setEnabled(not need or (backend.available() and len(self.desc.toPlainText().strip()) >= 10))

    # --- Seite 4: Claude arbeitet -------------------------------------------------------------
    def _page_progress(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0)
        t = self.prog_title = QLabel("Claude erstellt dein Projekt …"); t.setObjectName("title"); lay.addWidget(t)
        self.prog_sub = QLabel("Das kann je nach Umfang eine Minute dauern."); self.prog_sub.setObjectName("sub"); lay.addWidget(self.prog_sub)
        self.bar = QProgressBar(); self.bar.setRange(0, 0); self.bar.setTextVisible(False); self.bar.setFixedHeight(6); lay.addWidget(self.bar)
        self.ai_log = QPlainTextEdit(readOnly=True); lay.addWidget(self.ai_log, 1)
        return w

    # --- Navigation ----------------------------------------------------------------------------
    def _go(self, i):
        i = max(0, min(3, i))
        self.stack.setCurrentIndex(i)
        self.back.setVisible(0 < i < 3)
        self.next.setText("Fertig" if i == 3 else "Erstellen" if i == 2 else "Weiter")
        if i == 1:
            self.cfg_tpl.setText(f"{self.tpl.name}   ·   {self.tpl.lang}   ·   {self.tpl.kind}")
            self._validate()
        elif i == 2:
            self.opt_tpl.setText(f"{self.tpl.name}   ·   {self.tpl.lang}")
            app = self._is_app()
            self.app_box.setVisible(app)
            if not app and self._auto_desc and self.desc.toPlainText().strip() == self._auto_desc:
                self.desc.clear()                                       # vorbelegter Auftrag einer anderen Vorlage gehört nicht hierher
                self._auto_desc = ""
            if app and not self.app.count():
                for a in apps.APPS:
                    self.app.addItem(a.name, a.id)                      # löst _app_changed aus und füllt Technik und Beschreibung
            for k, c in self.checks.items():
                c.setVisible(k in self.eff.options); c.setChecked(k in ("git", "readme", "essentials"))
            if app:
                self._tech_changed()
            self.tools.setText(self._tool_hint())
            ai, have = self._is_ai(), backend.available()
            self.lang_combo.setVisible(ai); self.lang_combo.setCurrentIndex(0)
            self.desc_label.setText("Beschreibe dein Projekt:" if ai else "Auftrag an Claude (vorbelegt – du kannst ihn anpassen):" if app
                                    else "Claude passt das Projekt nach deiner Beschreibung an (optional):")
            self.desc.setEnabled(have)
            self.ai_hint.setText(
                "Claude legt Dateien nur in diesem Projektordner an und hat keine Shell. Deine Beschreibung geht über "
                + ("deinen API-Schlüssel" if backend.provider() == "api" else "deine Claude-Code-Anmeldung") + " an Anthropic; die Nutzung wird abgerechnet bzw. zählt wie normale Claude-Nutzung."
                if have else backend.unavailable_message().replace("**", "") + " (Projekt-Assistent: Extras → Optionen ist auch ohne Projekt erreichbar.)")
            self._check_desc()
            if not (ai or app):
                self.next.setEnabled(True)
        else:
            self.next.setEnabled(self.tpl is not None)

    def _tool_hint(self):
        tpl = self.eff
        if tpl.scaffold:
            missing = [x for x in (tpl.scaffold[0], "php") if not shutil.which(x)]
            if missing:
                return f"Hinweis: {', '.join(missing)} ist nicht installiert – das Projekt kann so nicht angelegt werden."
            sqlite = "" if _php_has("pdo_sqlite") else (" Hinweis: Laravel nutzt standardmäßig SQLite – dafür fehlt PHP die Erweiterung pdo_sqlite "
                                                         "(Arch: php-sqlite installieren und in php.ini aktivieren); Seiten ohne Datenbank laufen auch so.")
            return "Das Projekt wird mit „composer create-project“ aus dem Netz geladen." + sqlite
        need = {"python": "python3", "c": "gcc", "cpp": "g++", "csharp": "dotnet", "rust": "rustc", "go": "go", "javascript": "node",
                "java": "java", "shell": "bash"}.get(tpl.lang_id)
        if need and not shutil.which(need):
            return f"Hinweis: '{need}' ist auf diesem System nicht installiert – das Projekt wird erstellt, lässt sich aber erst nach der Installation ausführen."
        if tpl.id == "cs-maui-gtk":
            return ("Hinweis: Das GTK4-Backend ist eine frühe Vorschau (dotnet/maui-labs, MIT). Benötigt gtk4 und libadwaita auf dem System; "
                    "die NuGet-Pakete werden beim ersten Start geladen.")
        if tpl.id == "cs-maui":
            return ("Hinweis: MAUI braucht 'dotnet workload install maui-android' (und für Android das Android-SDK). Auf dem Linux-Desktop gibt es nur ein experimentelles GTK4-Backend (Vorschau) – "
                    "Ziele sind Android, iOS, Windows und macOS. Das Projekt wird trotzdem angelegt.")
        return ""

    def _next(self):
        i = self.stack.currentIndex()
        if i == 0 and self.tpl:
            return self._go(1)
        if i == 1 and not self.err.text():
            return self._go(2)
        if i == 2:
            self._create()
        elif i == 3:
            self.accept()

    def _create(self):
        tpl = self.eff
        opts = self._opts = {k: c.isChecked() for k, c in self.checks.items() if k in tpl.options}
        loc = Path(self.location.text().strip()).expanduser()
        if tpl.scaffold:
            return self._start_scaffold(loc, opts)
        self.setCursor(Qt.WaitCursor)
        try:
            self.result_data = create_project(tpl, self.name.text().strip(), loc, opts)
        except Exception as e:  # Dateisystem-/Prozessfehler dem Nutzer zeigen
            self.setCursor(Qt.ArrowCursor)
            self.err.setText(str(e)); self._go(1)
            return
        self.setCursor(Qt.ArrowCursor)
        self.settings.setValue("new_project_location", str(loc))
        desc = self.desc.toPlainText().strip()
        if desc and backend.available():
            return self._start_ai(desc)
        if self._wants_install():
            return self._start_install()
        self.accept()

    # --- Python-Pakete ins neue .venv ----------------------------------------------------------------
    def _wants_install(self) -> bool:
        """Soll nach dem Anlegen (und nach Claudes Arbeit) die requirements.txt ins neue .venv installiert werden?"""
        if not self._opts.get("venv") or not self.result_data:
            return False
        root = self.result_data[0]
        req = root / "requirements.txt"
        try:
            has = any(l.strip() and not l.lstrip().startswith("#") for l in req.read_text(encoding="utf-8").splitlines())
        except OSError:
            return False
        return has and (root / ".venv/bin/python").is_file()

    def _start_install(self):
        root, _main, log = self.result_data
        self._go(3)
        self.prog_title.setText("Python-Pakete werden installiert …")
        self.prog_sub.setText("pip install -r requirements.txt – bei Qt (PySide6) sind das einige hundert MB, das dauert eine Weile.")
        self.next.setEnabled(False); self.cancel.setText("Überspringen")
        self.ai_log.appendPlainText("\n$ pip install -r requirements.txt")
        self.bar.setRange(0, 0)
        p = self.pip = QProcess(self)
        p.setWorkingDirectory(str(root))
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(lambda: self.ai_log.appendPlainText(bytes(p.readAll()).decode("utf-8", "replace").rstrip()))
        p.finished.connect(self._install_done)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self._install_done(-1, QProcess.CrashExit))
        p.start(str(root / ".venv/bin/python"), ["-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"])

    def _install_done(self, code, status):
        p, self.pip = self.pip, None
        if p is None:
            return
        root, main, log = self.result_data
        ok = code == 0 and status == QProcess.NormalExit
        log.append("  Python-Pakete aus requirements.txt installiert." if ok else
                   "  Pakete konnten nicht installiert werden – im Paket-Manager oder mit 'pip install -r requirements.txt' im .venv nachholen.")
        self.bar.setRange(0, 1); self.bar.setValue(1 if ok else 0)
        self.prog_title.setText("Projekt erstellt" if ok else "Projekt erstellt – Pakete fehlen noch")
        self.prog_sub.setText("Fertig – mit F5 startest du die Anwendung." if ok else "Die Installation ist fehlgeschlagen (Meldung unten). Das Projekt lässt sich trotzdem öffnen.")
        self.next.setEnabled(True); self.cancel.setText("Schließen")

    # --- Projekte, die ein Werkzeug anlegt (composer create-project …) ---------------------------------
    def _start_scaffold(self, loc: Path, opts: dict):
        name = self.name.text().strip()
        cmd = scaffold_command(self.eff, name)
        if not shutil.which(cmd[0]):
            self._go(1)
            return self.err.setText(f"'{cmd[0]}' ist nicht installiert – das Projekt kann nicht angelegt werden.")
        root = loc / name
        self._scaffold = (root, root.exists(), opts, self.desc.toPlainText().strip())
        self._go(3)
        self.prog_title.setText(f"{self.eff.name} wird angelegt …")
        self.prog_sub.setText(f"{' '.join(cmd[:3])} – das dauert je nach Netzwerk ein bis zwei Minuten.")
        self.next.setEnabled(False); self.cancel.setText("Abbrechen")
        self.ai_log.clear(); self.bar.setRange(0, 0)
        p = self.proc = QProcess(self)
        p.setWorkingDirectory(str(loc))
        env = QProcessEnvironment.systemEnvironment(); env.insert("COMPOSER_NO_INTERACTION", "1")
        p.setProcessEnvironment(env)
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyRead.connect(lambda: self.ai_log.appendPlainText(bytes(p.readAll()).decode("utf-8", "replace").rstrip()))
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self._scaffold_done(-1, QProcess.CrashExit))
        p.finished.connect(self._scaffold_done)
        p.start(cmd[0], cmd[1:])

    def _scaffold_done(self, code, status):
        p, self.proc = self.proc, None
        if p is None:
            return
        root, existed, opts, desc = self._scaffold
        name = self.name.text().strip()
        if code != 0 or status != QProcess.NormalExit:
            scaffold_failed(root, existed)
            self.bar.setRange(0, 1); self.bar.setValue(0)
            self.prog_title.setText("Das Projekt konnte nicht angelegt werden")
            self.prog_sub.setText("Die Meldung steht unten. Mit „Zurück“ lässt sich der Name oder Ort ändern.")
            self.back.setVisible(True); self.cancel.setText("Schließen")
            return
        log = [f"Projekt '{name}' ({self.eff.name}) wurde in {root} erstellt…", "  " + " ".join(scaffold_command(self.eff, name)) + " ✓"]
        self.result_data = finish_project(self.eff, name, root, opts, log)
        self.settings.setValue("new_project_location", str(root.parent))
        if desc and backend.available():
            return self._start_ai(desc)
        self.bar.setRange(0, 1); self.bar.setValue(1)
        self.prog_title.setText("Projekt erstellt")
        self.prog_sub.setText("Fertig – mit F5 startest du die Anwendung.")
        self.next.setEnabled(True); self.cancel.setText("Schließen")

    def _start_ai(self, desc):
        root, main, log = self.result_data
        name = self.name.text().strip()
        skip = {".git", "vendor", "node_modules", "storage", "target", "venv", ".venv", "__pycache__"}
        existing = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not skip & set(p.relative_to(root).parts))[:300]
        if self._is_ai():
            prompt = project_prompt(name, desc, LANG_HINTS[self.lang_combo.currentText()])
        else:
            prompt = project_prompt(name, desc, template=self.eff.name, files=existing)
        self._go(3)
        self.prog_title.setText("Claude erstellt dein Projekt …")
        self.prog_sub.setText("Das kann je nach Umfang eine Minute dauern.")
        self.next.setEnabled(False); self.cancel.setText("Abbrechen")
        self.ai_log.clear(); self.bar.setRange(0, 0)
        self.claude.run(prompt, root, system=SYSTEM_APP if self._is_app() else SYSTEM_PROJECT, max_turns=100 if self._is_app() else 40)

    def _ai_finished(self, ok, result, _session):
        root, main, log = self.result_data
        self.bar.setRange(0, 1); self.bar.setValue(1 if ok else 0)
        new_main = parse_main(result, root) or main
        if ok:
            self.prog_sub.setText("Fertig – das Projekt wurde nach deiner Beschreibung erstellt.")
            log += ["Claude hat das Projekt nach der Beschreibung erstellt."]
        else:
            self.prog_sub.setText("Claude konnte nicht fertig werden – das Projekt kann trotzdem geöffnet werden.")
            self.ai_log.appendPlainText("\n⚠ " + result)
            log += [f"Claude-Fehler: {result}"]
        self.result_data = (root, new_main, log)
        if self._wants_install():
            return self._start_install()
        self.next.setEnabled(True); self.cancel.setText("Schließen")

    def _stop_scaffold(self):
        p, self.proc = self.proc, None
        if p is not None:
            p.kill(); p.waitForFinished(3000)
            root, existed, _o, _d = self._scaffold
            scaffold_failed(root, existed)
            return True
        return False

    def _stop_install(self) -> bool:
        p, self.pip = self.pip, None
        if p is None:
            return False
        p.kill(); p.waitForFinished(3000)
        self.result_data[2].append("  Paketinstallation übersprungen – später im Paket-Manager nachholen.")
        return True

    def _cancel(self):
        if self._stop_install():
            self.bar.setRange(0, 1); self.bar.setValue(0)
            self.prog_title.setText("Projekt erstellt – Pakete fehlen noch")
            self.prog_sub.setText("Die Installation wurde übersprungen. Du kannst sie später im Paket-Manager nachholen.")
            self.next.setEnabled(True); self.cancel.setText("Schließen")
            return
        if self._stop_scaffold():
            self.bar.setRange(0, 1); self.bar.setValue(0)
            self.prog_title.setText("Abgebrochen"); self.prog_sub.setText("Das angefangene Projekt wurde entfernt.")
            self.back.setVisible(True); self.cancel.setText("Schließen")
            return
        if self.claude.running:
            self.claude.stop()
            return
        self.reject()

    def reject(self):
        self._stop_install()
        self._stop_scaffold()
        self.claude.stop()
        super().reject()
