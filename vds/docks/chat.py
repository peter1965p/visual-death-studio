"""Claude-Chat-Panel: spricht über das lokale Claude Code mit dem geöffneten Projekt."""
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout,
                               QWidget)

from ..ai import backend
from ..ai.prompts import SYSTEM_CHAT


class _Input(QPlainTextEdit):
    submitted = Signal()
    imagePasted = Signal(QImage)

    def canInsertFromMimeData(self, source):
        return source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self.imagePasted.emit(img)
                return
        super().insertFromMimeData(source)

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
        self.claude = None
        self.images: list[Path] = []                 # eingefügte Bilder, die mit der nächsten Nachricht gehen
        self._tmp = tempfile.TemporaryDirectory(prefix="vds-chat-")
        self._attach_agent()

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.input = _Input()
        self.input.setPlaceholderText("Claude fragen … (Enter sendet, Umschalt+Enter = neue Zeile)")
        self.input.setFixedHeight(72)
        self.input.submitted.connect(self.send)
        self.input.imagePasted.connect(self.add_image)
        self.attach = QPushButton(); self.attach.setToolTip("Angehängte Bilder entfernen"); self.attach.clicked.connect(self.clear_images); self.attach.hide()
        self.ctx = QCheckBox("Aktive Datei mitsenden"); self.ctx.setChecked(True)
        self.bash = QCheckBox("Befehle erlauben")
        self.bash.setToolTip("Erlaubt Claude, Shell-Befehle in deinem Projekt auszuführen (z. B. Tests, pip install). "
                             "Standardmäßig hat Claude nur Dateiwerkzeuge.")
        self.send_btn = QPushButton("Senden"); self.send_btn.clicked.connect(self.send)
        self.stop_btn = QPushButton("Stopp"); self.stop_btn.clicked.connect(lambda: self.claude.stop()); self.stop_btn.hide()
        new_btn = QPushButton("Neue Unterhaltung"); new_btn.clicked.connect(self.reset)
        self.status = QLabel(); self.status.setObjectName("sub")
        opts = QHBoxLayout(); opts.addWidget(self.ctx); opts.addWidget(self.bash); opts.addStretch()
        btns = QHBoxLayout(); btns.addWidget(new_btn); btns.addStretch(); btns.addWidget(self.status); btns.addWidget(self.stop_btn); btns.addWidget(self.send_btn)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(6)
        for x in (self.view, self.input, self.attach):
            lay.addWidget(x)
        lay.addLayout(opts); lay.addLayout(btns)
        self.reset()

    # --- Zustand ---------------------------------------------------------------------------
    def _attach_agent(self):
        """Agent des gewählten Anbieters (Claude Code oder API) anlegen und verdrahten."""
        self.claude = backend.make_agent(self)
        self.claude.text.connect(lambda t: self._add(t.strip()))
        self.claude.tool.connect(lambda t: self._add(f"*⚙ {t}*"))
        self.claude.finished.connect(self._finished)
        self._provider = backend.provider()
        self._available = backend.available()

    def refresh_backend(self):
        """Nach einer Änderung der Optionen: bei Anbieterwechsel neuen Agenten nehmen (nie während eines Laufs)."""
        if self.claude.running:
            return
        changed = backend.provider() != self._provider
        if changed:
            self._attach_agent()
        if changed or backend.available() != self._available:
            self.reset()

    def set_root(self, root: Path):
        self.root = Path(root)
        self.reset()

    def reset(self):
        if self.claude.running:
            return
        self.session = None
        self.md = ""
        if not backend.available():
            self._add(backend.unavailable_message())
        else:
            self._add("Hallo! Ich kann in diesem Projekt Code schreiben, ändern und erklären. Was möchtest du tun?"
                      + (f"\n\n*Verbunden über {backend.label()}.*" if backend.provider() == "api" else ""))

    def _add(self, md: str):
        self.md += md + "\n\n"
        self.view.setMarkdown(self.md)
        sb = self.view.verticalScrollBar(); sb.setValue(sb.maximum())

    # --- Bilder ------------------------------------------------------------------------------
    def add_image(self, img: QImage):
        path = Path(self._tmp.name) / f"bild-{time.time_ns()}.png"
        if img.save(str(path), "PNG"):
            self.images.append(path); self._show_images()

    def clear_images(self):
        self.images.clear(); self._show_images()

    def _show_images(self):
        n = len(self.images)
        self.attach.setVisible(bool(n))
        self.attach.setText(f"🖼 {n} Bild{'er' if n > 1 else ''} angehängt   ✕")

    # --- Senden ------------------------------------------------------------------------------
    def send(self):
        text = self.input.toPlainText().strip()
        if not (text or self.images) or self.claude.running or not backend.available():
            return
        images = list(self.images)
        text = text or "Sieh dir das angehängte Bild an."
        self.input.clear(); self.clear_images()
        self._add("> **Du:** " + text.replace("\n", "\n> ") + (f"\n>\n> *🖼 {len(images)} Bild{'er' if len(images) > 1 else ''} angehängt*" if images else ""))
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
        self.claude.run(prompt, self.root, session=self.session, allow_bash=self.bash.isChecked(), system=SYSTEM_CHAT, max_turns=40, images=images)

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
