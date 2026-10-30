"""Extras → Optionen: Editor, IntelliSense, Designer, Claude (lokale CLI oder eigener API-Schlüssel), Import/Export."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton, QRadioButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import options
from ..ai import api, claude_cli, keystore
from ..ai.completion import MODELS

CATEGORIES = ["Allgemein", "Text-Editor", "IntelliSense", "Designer", "Web-Vorschau", "Claude"]
RELOAD = {"ohne-hmr": "Nur bei Seiten ohne Hot-Reload (z. B. PHP)", "immer": "Immer", "nie": "Nie"}
EFFORT_LABELS = {"": "(Standard des Modells)", "low": "low – schnell", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "max – am gründlichsten"}


def note(text: str) -> QLabel:
    lab = QLabel(text); lab.setWordWrap(True); lab.setStyleSheet("color:#8fa3c7")
    return lab


class OptionsDialog(QDialog):
    _tested = Signal(bool, str)

    def __init__(self, win=None, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("Optionen"); self.resize(780, 560)
        self.fields: dict = {}                                   # Optionsschlüssel -> (Widget, Getter, Setter)
        self.nav = QListWidget(); self.nav.setFixedWidth(170)
        self.nav.addItems(CATEGORIES)
        self.pages = QStackedWidget()
        for build in (self._page_general, self._page_editor, self._page_intellisense, self._page_designer, self._page_web, self._page_claude):
            self.pages.addWidget(build())
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        bb.button(QDialogButtonBox.Ok).clicked.connect(self._ok)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        bb.button(QDialogButtonBox.Cancel).clicked.connect(self.reject)
        bb.button(QDialogButtonBox.RestoreDefaults).setText("Auf Standard")
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        body = QHBoxLayout(); body.addWidget(self.nav); body.addWidget(self.pages, 1)
        lay = QVBoxLayout(self); lay.addLayout(body); lay.addWidget(bb)
        self._tested.connect(self._show_test)
        self.load()

    # --- Feld-Helfer ------------------------------------------------------------------------------
    def _bool(self, key, text):
        w = QCheckBox(text)
        self.fields[key] = (w, w.isChecked, w.setChecked)
        return w

    def _int(self, key, suffix=""):
        w = QSpinBox(); w.setRange(*options.LIMITS[key]); w.setSuffix(suffix)
        self.fields[key] = (w, w.value, w.setValue)
        return w

    def _text(self, key, placeholder=""):
        w = QLineEdit(); w.setPlaceholderText(placeholder)
        self.fields[key] = (w, w.text, w.setText)
        return w

    def _combo(self, key, items: dict | list, editable=False):
        w = QComboBox(); w.setEditable(editable)
        if isinstance(items, dict):
            for v, label in items.items():
                w.addItem(label, v)
            self.fields[key] = (w, lambda: w.currentData(), lambda v: w.setCurrentIndex(max(0, w.findData(v))))
        else:
            w.addItems(items)
            self.fields[key] = (w, w.currentText, w.setEditText if editable else w.setCurrentText)
        return w

    # --- Seiten --------------------------------------------------------------------------------------
    def _page_general(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(note("Alle Optionen gelten sofort für das ganze Programm. Gespeichert wird im Konfigurationsordner des Benutzers."))
        theme = self._combo("ui/theme", {"neon": "Neon (dunkel)", "hell": "Hell"})
        self.theme_note = QLabel(); self.theme_note.setWordWrap(True); self.theme_note.setStyleSheet("color:#8fa3c7")
        self.restart_btn = QPushButton("Jetzt neu starten"); self.restart_btn.setFixedWidth(180); self.restart_btn.clicked.connect(self._restart)
        tf = QFormLayout(); tf.addRow("Farbschema", theme); lay.addLayout(tf); lay.addWidget(self.theme_note); lay.addWidget(self.restart_btn)
        theme.currentIndexChanged.connect(self._theme_hint); self._theme_hint()
        lay.addWidget(self._bool("ui/start_page", "Startseite mit zuletzt geöffneten Projekten beim Start zeigen"))
        lay.addWidget(self._bool("update/check", "Beim Start nach neuen Versionen suchen (höchstens einmal am Tag)"))
        lay.addWidget(self._bool("ui/splash", "Startbild mit Fortschrittsanzeige zeigen (beim nächsten Start)"))
        for text, slot in (("Fensterlayout zurücksetzen", self._reset_layout), ("Konfigurationsordner öffnen", self._open_config),
                           ("Einstellungen exportieren …", self._export), ("Einstellungen importieren …", self._import)):
            b = QPushButton(text); b.clicked.connect(slot); b.setFixedWidth(260); lay.addWidget(b)
        lay.addWidget(note("Der Export enthält nur die Optionen – nie deinen API-Schlüssel."))
        lay.addStretch()
        return w

    def _page_editor(self):
        w = QWidget(); lay = QVBoxLayout(w)
        form = QFormLayout()
        font = QPushButton("Schriftart wählen …"); font.clicked.connect(lambda: self.win and self.win.pick_editor_font())
        form.addRow("Schrift", font)
        form.addRow("Tab-Breite", self._int("editor/tab_width", " Zeichen"))
        lay.addLayout(form)
        for key, text in (("editor/use_spaces", "Tab-Taste fügt Leerzeichen ein (aus = echte Tabulatoren)"), ("editor/word_wrap", "Zeilenumbruch am Fensterrand"),
                          ("editor/whitespace", "Leerzeichen und Tabulatoren anzeigen")):
            lay.addWidget(self._bool(key, text))
        box = QGroupBox("Automatisch speichern"); f2 = QFormLayout(box)
        f2.addRow("Alle", self._int("editor/autosave_seconds", " Sekunden (0 = aus)"))
        f2.addRow(self._bool("editor/autosave_on_focus_loss", "Beim Wechsel in ein anderes Fenster speichern"))
        lay.addWidget(box); lay.addStretch()
        return w

    def _page_intellisense(self):
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(self._bool("intellisense/auto", "Vorschläge automatisch beim Tippen anzeigen (Strg+Leertaste geht immer)"))
        form = QFormLayout()
        form.addRow("Ab Zeichen", self._int("intellisense/min_chars"))
        form.addRow("Verzögerung", self._int("intellisense/delay_ms", " ms"))
        lay.addLayout(form); lay.addStretch()
        return w

    def _page_designer(self):
        w = QWidget(); lay = QVBoxLayout(w)
        form = QFormLayout(); form.addRow("Rastergröße", self._int("designer/grid", " px")); lay.addLayout(form)
        lay.addWidget(self._bool("designer/show_grid", "Punktraster anzeigen"))
        lay.addWidget(self._bool("designer/snap", "Controls an Kanten und Mitten anderer Controls einrasten lassen (Fanglinien)"))
        lay.addStretch()
        return w

    def _page_web(self):
        from ..web.panel import DEVICES
        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(self._bool("web/auto_open", "Vorschau automatisch öffnen, sobald ein Dev-Server eine Adresse meldet (npm run dev, php -S …)"))
        form = QFormLayout()
        form.addRow("Neu laden beim Speichern", self._combo("web/auto_reload", RELOAD))
        form.addRow("Standard-Gerät", self._combo("web/device", list(DEVICES)))
        lay.addLayout(form)
        lay.addWidget(note("Ungespeicherte visuelle Änderungen in der Vorschau werden nie durch ein automatisches Neuladen verworfen."))
        lay.addStretch()
        return w

    def _page_claude(self):
        w = QWidget(); lay = QVBoxLayout(w)
        self.r_auto = QRadioButton("Automatisch (Claude Code, wenn installiert – sonst die API, falls ein Schlüssel hinterlegt ist)")
        self.r_cli = QRadioButton("Claude Code (lokale CLI, nutzt deine Anmeldung – kein API-Schlüssel nötig)")
        self.r_api = QRadioButton("Claude-API (eigener API-Schlüssel, Abrechnung pro Token über dein Anthropic-Konto)")
        self.fields["claude/provider"] = (self.r_auto, lambda: "api" if self.r_api.isChecked() else "cli" if self.r_cli.isChecked() else "auto",
                                          lambda v: {"api": self.r_api, "cli": self.r_cli}.get(v, self.r_auto).setChecked(True))
        lay.addWidget(self.r_auto); lay.addWidget(self.r_cli); lay.addWidget(self.r_api)

        self.cli_box = QGroupBox("Claude Code")
        f = QFormLayout(self.cli_box)
        exe = claude_cli.find()
        f.addRow("Status", QLabel(f"gefunden: {exe}" if exe else "nicht gefunden – siehe claude.com/claude-code"))
        f.addRow("Modell für Vervollständigung", self._combo("ai/completion_model", MODELS))
        lay.addWidget(self.cli_box)

        self.api_box = QGroupBox("Claude-API")
        f = QFormLayout(self.api_box)
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText("sk-ant-… (leer lassen = gespeicherten Schlüssel behalten)")
        show = QCheckBox("zeigen"); show.toggled.connect(lambda on: self.key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        clear = QPushButton("Schlüssel entfernen"); clear.clicked.connect(self._clear_key)
        row = QHBoxLayout(); row.addWidget(self.key, 1); row.addWidget(show); row.addWidget(clear)
        self.key_status = QLabel()
        f.addRow("API-Schlüssel", row); f.addRow("", self.key_status)
        f.addRow("Modell (Chat, Agent)", self._combo("claude/api_model", api.MODEL_PRESETS, editable=True))
        f.addRow("Modell (Vervollständigung)", self._combo("claude/api_completion_model", api.MODEL_PRESETS, editable=True))
        f.addRow("Denktiefe (effort)", self._combo("claude/api_effort", EFFORT_LABELS))
        f.addRow("Max. Ausgabe", self._int("claude/api_max_tokens", " Tokens"))
        f.addRow("Basis-URL", self._text("claude/api_base_url", "leer = https://api.anthropic.com (nur für eigene Gateways ändern)"))
        f.addRow(self._bool("claude/api_fallbacks", "Bei Ablehnung durch Sicherheitsfilter automatisch ein Ausweichmodell nutzen (nur offizielle API)"))
        self.test_btn = QPushButton("Verbindung testen"); self.test_btn.clicked.connect(self._test)
        self.test_out = QLabel(); self.test_out.setWordWrap(True)
        t = QHBoxLayout(); t.addWidget(self.test_btn); t.addWidget(self.test_out, 1)
        f.addRow(t)
        lay.addWidget(self.api_box)
        lay.addWidget(note("Datenschutz: Im API-Modus gehen deine Anfragen samt dem Code, den du mitsendest, an Anthropic. Der Schlüssel wird in einer eigenen, nur für dich "
                           "lesbaren Datei im Konfigurationsordner gespeichert (oder aus ANTHROPIC_API_KEY gelesen) – nie in den Optionen und nie im Export."))
        lay.addStretch()
        for r in (self.r_auto, self.r_cli, self.r_api):
            r.toggled.connect(self._provider_changed)
        return w

    # --- Verhalten --------------------------------------------------------------------------------------
    def _provider_changed(self, *_):
        auto = self.r_auto.isChecked()
        self.api_box.setEnabled(auto or self.r_api.isChecked()); self.cli_box.setEnabled(auto or self.r_cli.isChecked())

    def _refresh_key_status(self):
        k = keystore.load()
        self.key_status.setText(f"Aktiv: {keystore.mask(k)} ({keystore.source()})" if k else "Kein Schlüssel hinterlegt.")

    def load(self):
        for key, (_w, _get, setter) in self.fields.items():
            setter(options.get(key))
        self._provider_changed(); self._refresh_key_status()

    def apply(self):
        for key, (_w, getter, _s) in self.fields.items():
            options.set(key, getter())
        typed = self.key.text().strip()
        if typed:
            keystore.save(typed); self.key.clear()
        self._refresh_key_status()
        if self.win:
            self.win.statusBar().showMessage("Optionen übernommen.", 3000)

    def _ok(self):
        self.apply(); self.accept()

    def _defaults(self):
        if QMessageBox.question(self, "Optionen", "Alle Optionen auf Standardwerte zurücksetzen? (Der API-Schlüssel bleibt erhalten.)") == QMessageBox.Yes:
            options.reset(); self.load()

    def _clear_key(self):
        keystore.clear(); self.key.clear(); self._refresh_key_status()

    def _test(self):
        """Kleine Testanfrage mit dem eingegebenen (oder gespeicherten) Schlüssel; läuft im Thread, damit die Oberfläche nicht einfriert."""
        cfg = api.config("completion")
        cfg.key = self.key.text().strip() or keystore.load()
        cfg.model = self.fields["claude/api_completion_model"][1]().strip()
        cfg.base_url = self.fields["claude/api_base_url"][1]().strip()
        cfg.effort = "low" if cfg.supports(api.EFFORT_MODELS) else ""
        cfg.max_tokens = 64
        if not cfg.key:
            return self._show_test(False, "Kein Schlüssel eingegeben oder gespeichert.")
        self.test_btn.setEnabled(False); self.test_out.setText("Teste …")

        def work():
            try:
                api.complete_text(cfg, "Antworte mit einem Wort.", "Sag OK.", timeout=30)
                self._tested.emit(True, f"Verbindung in Ordnung – {cfg.model} antwortet.")
            except Exception as e:
                self._tested.emit(False, api.describe_error(e))
        threading.Thread(target=work, daemon=True).start()

    def _show_test(self, ok, msg):
        self.test_btn.setEnabled(True)
        self.test_out.setText(("✔ " if ok else "✘ ") + msg)
        self.test_out.setStyleSheet("color:#3dffa1" if ok else "color:#ff7a93")

    def _theme_hint(self, *_):
        from .. import theme as th
        chosen = self.fields["ui/theme"][1]()
        differs = chosen != th.current
        self.theme_note.setText("Das neue Farbschema wird nach einem Neustart vollständig angewendet." if differs else "")
        self.restart_btn.setVisible(differs)

    def _restart(self):
        self.apply()
        import sys
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QApplication
        if QProcess.startDetached(sys.executable, sys.argv):
            QApplication.quit()

    def _reset_layout(self):
        if self.win:
            self.win.reset_layout()

    def _open_config(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(keystore.key_file().parent)))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Einstellungen exportieren", "visual-death-studio-optionen.json", "JSON (*.json)")
        if path:
            self.apply()
            Path(path).write_text(json.dumps(options.export_all(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Einstellungen importieren", "", "JSON (*.json)")
        if not path:
            return
        try:
            n = options.import_all(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError, AttributeError):
            return QMessageBox.warning(self, "Optionen", "Die Datei ließ sich nicht lesen.")
        self.load()
        QMessageBox.information(self, "Optionen", f"{n} Einstellung(en) übernommen.")
