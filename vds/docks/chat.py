"""Claude-Chat-Panel: spricht über die lokale Claude-CLI mit dem geöffneten Projekt."""
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..ai import claude_cli
from ..ai.prompts import SYSTEM_CHAT


class _Input(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
        else:
            super().keyPressEvent(e)


class ChatPanel(QWidget):
    busyChanged = Signal(bool)
    filesChanged = Signal()           # Claude hat (möglicherweise) Dateien geändert
    runStarting = Signal()            # direkt vor dem Start eines Claude-Laufs (für Snapshots)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.session: str | None = None
        self.active_file = lambda: (None, "")        # -> (Pfad|None, Auswahltext)
        self.md = ""
        self.claude = claude_cli.ClaudeProcess(self)
        self.claude.text.connect(lambda t: self._add(t.strip()))
        self.claude.tool.connect(lambda t: self._add(f"*⚙ {t}*"))
        self.claude.finished.connect(self._finished)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.input = _Input()
        self.input.setPlaceholderText("Claude fragen … (Enter sendet, Umschalt+Enter = neue Zeile)")
        self.input.setFixedHeight(72)
        self.input.submitted.connect(self.send)
        self.ctx = QCheckBox("Aktive Datei mitsenden"); self.ctx.setChecked(True)
        self.bash = QCheckBox("Befehle erlauben")
        self.bash.setToolTip("Erlaubt Claude, Shell-Befehle in deinem Projekt auszuführen (z. B. Tests, pip install). "
                             "Standardmäßig hat Claude nur Dateiwerkzeuge.")
        self.send_btn = QPushButton("Senden"); self.send_btn.clicked.connect(self.send)
        self.stop_btn = QPushButton("Stopp"); self.stop_btn.clicked.connect(self.claude.stop); self.stop_btn.hide()
        new_btn = QPushButton("Neue Unterhaltung"); new_btn.clicked.connect(self.reset)
        self.status = QLabel(); self.status.setObjectName("sub")
        opts = QHBoxLayout(); opts.addWidget(self.ctx); opts.addWidget(self.bash); opts.addStretch()
        btns = QHBoxLayout(); btns.addWidget(new_btn); btns.addStretch(); btns.addWidget(self.status); btns.addWidget(self.stop_btn); btns.addWidget(self.send_btn)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(6)
        for x in (self.view, self.input):
            lay.addWidget(x)
        lay.addLayout(opts); lay.addLayout(btns)
        self.reset()

    # --- Zustand ---------------------------------------------------------------------------
    def set_root(self, root: Path):
        self.root = Path(root)
        self.reset()

    def reset(self):
        if self.claude.running:
            return
        self.session = None
        self.md = ""
        if not claude_cli.available():
            self._add("**Claude-CLI nicht gefunden.** Installiere Claude Code und melde dich an, damit der Chat funktioniert.")
        else:
            self._add("Hallo! Ich kann in diesem Projekt Code schreiben, ändern und erklären. Was möchtest du tun?")

    def _add(self, md: str):
        self.md += md + "\n\n"
        self.view.setMarkdown(self.md)
        sb = self.view.verticalScrollBar(); sb.setValue(sb.maximum())

    # --- Senden ------------------------------------------------------------------------------
    def send(self):
        text = self.input.toPlainText().strip()
        if not text or self.claude.running or not claude_cli.available():
            return
        self.input.clear()
        self._add("> **Du:** " + text.replace("\n", "\n> "))
        prompt = text
        path, sel = self.active_file()
        if self.ctx.isChecked() and path:
            try:
                rel = Path(path).relative_to(self.root)
            except ValueError:
                rel = Path(path)
            prompt = f"[Aktive Datei im Editor: {rel}]\n" + (f"[Markierter Text:\n{sel[:4000]}\n]\n" if sel else "") + "\n" + text
        self._busy(True)
        self.runStarting.emit()
        self.claude.run(prompt, self.root, session=self.session, allow_bash=self.bash.isChecked(), system=SYSTEM_CHAT, max_turns=40)

    def _finished(self, ok, result, session):
        if session:
            self.session = session
        if not ok:
            self._add(f"**Fehler:** {result}")
            self.session = self.session if session else None
        self._busy(False)
        self.filesChanged.emit()

    def _busy(self, busy):
        self.send_btn.setVisible(not busy); self.stop_btn.setVisible(busy)
        self.input.setEnabled(not busy)
        self.status.setText("Claude arbeitet …" if busy else "")
        self.busyChanged.emit(busy)
        if not busy:
            self.input.setFocus()

    def ask(self, text: str):
        """Von außen (z. B. Menü) eine Frage einsetzen und den Fokus in die Eingabe legen."""
        self.input.setPlainText(text)
        self.input.setFocus()
