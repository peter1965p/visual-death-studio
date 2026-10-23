"""Claude-Vervollständigung: schlanker `claude -p`-Aufruf ohne Werkzeuge/MCP, der Code für die Cursorposition liefert."""
import re
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QSettings, QTimer, Signal
from PySide6.QtWidgets import QMessageBox

from ..branding import SETTINGS_APP, SETTINGS_ORG
from . import claude_cli

MODELS = {"haiku": "Haiku – schnell und günstig (Standard)", "sonnet": "Sonnet – ausgewogen", "opus": "Opus – am gründlichsten"}
MAX_BEFORE, MAX_AFTER = 6000, 2000
TIMEOUT_MS = 60_000

SYSTEM = (
    "You are the code completion engine of an IDE. You receive the code before and after the cursor and output ONLY the code that must be "
    "inserted at the cursor. Rules: no explanations, no markdown fences, never repeat the existing code before or after the cursor. "
    "Match the file's style, naming and indentation exactly: the first line you output continues the cursor line, every further line must "
    "carry its full indentation. If the cursor line or the line above is a comment that describes a task, implement exactly that task. "
    "Prefer one complete, correct unit (a function, a block, the rest of a statement) over a long essay; keep it short unless the task needs more. "
    "If an extra instruction is given, follow it. Write comments in the language the file already uses. "
    "Output real line breaks, never the two characters backslash and n. If the cursor sits on an empty line, start directly with code, without a blank first line."
)


def build_prompt(filename: str, lang: str, before: str, after: str, instruction: str = "", avoid: str = "") -> str:
    if len(before) > MAX_BEFORE:
        before = before[:1500] + "\n# … (gekürzt) …\n" + before[-(MAX_BEFORE - 1500):]
    after = after[:MAX_AFTER]
    parts = [f"File: {filename} ({lang})"]
    if instruction.strip():
        parts.append(f"Instruction from the user: {instruction.strip()}")
    parts += [f"<before_cursor>\n{before}</before_cursor>", f"<after_cursor>\n{after}</after_cursor>"]
    if avoid.strip():
        parts.append("The user rejected this earlier suggestion; give a clearly different variant:\n<rejected>\n" + avoid + "\n</rejected>")
    parts.append("Output only the text to insert at the cursor.")
    return "\n".join(parts)


def clean_output(text: str) -> str:
    """Markdown-Zäune entfernen, falls das Modell trotz Anweisung welche liefert."""
    t = text.strip("\r")
    t = re.sub(r"^(?:\\n)+", "", t)                       # Modell hat den Zeilenumbruch als Text „\n“ geschrieben
    m = re.match(r"^\s*```[\w+-]*\n(.*?)\n?```\s*$", t, re.S)
    if m:
        t = re.sub(r"^(?:\\n)+", "", m.group(1))
    return t.rstrip()


class AiCompletion(QObject):
    """Verwaltet Modell-Einstellung, Einwilligung und den laufenden Aufruf (höchstens einer gleichzeitig)."""
    busyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.root = Path(".")
        self.proc: QProcess | None = None
        self._timer = QTimer(self, singleShot=True, interval=TIMEOUT_MS)
        self._timer.timeout.connect(self.cancel)

    @property
    def model(self) -> str:
        m = str(self.settings.value("ai/completion_model", "haiku"))
        return m if m in MODELS else "haiku"

    def set_model(self, m: str):
        self.settings.setValue("ai/completion_model", m)

    @property
    def busy(self) -> bool:
        return self.proc is not None

    def consent(self, parent) -> bool:
        if self.settings.value("ai/ack") in (True, "true", "1", 1):
            return True
        ok = QMessageBox.question(parent, "Claude-Vervollständigung",
                                  "Für den Vorschlag sendet die IDE den Code rund um den Cursor über deine Claude-Code-Anmeldung an Anthropic. "
                                  "Jeder Aufruf zählt wie normale Claude-Nutzung.\n\nFortfahren?") == QMessageBox.Yes
        if ok:
            self.settings.setValue("ai/ack", True)
        return ok

    def run(self, prompt: str, cb, parent=None):
        """cb(ok, text_oder_fehler). Ein neuer Aufruf bricht einen laufenden ab."""
        if not claude_cli.available():
            return cb(False, "Die Claude-CLI ('claude') wurde nicht gefunden.")
        if not self.consent(parent):
            return cb(False, "Abgebrochen.")
        self.cancel()
        p = QProcess(self)
        p.setWorkingDirectory(str(self.root))
        out, err = [], []
        p.readyReadStandardOutput.connect(lambda: out.append(bytes(p.readAllStandardOutput()).decode("utf-8", "replace")))
        p.readyReadStandardError.connect(lambda: err.append(bytes(p.readAllStandardError()).decode("utf-8", "replace")))

        def done(code, status):
            if self.proc is not p:
                return                                   # abgebrochen/ersetzt
            self.proc = None
            self._timer.stop(); self.busyChanged.emit(False)
            text = clean_output("".join(out))
            if code == 0 and text.strip():
                cb(True, text)
            else:
                cb(False, ("".join(err).strip() or "Claude hat nichts geliefert.")[:300])
        p.finished.connect(done)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and (setattr(self, "proc", None), self.busyChanged.emit(False), cb(False, "Claude konnte nicht gestartet werden.")))
        self.proc = p
        self._timer.start()
        self.busyChanged.emit(True)
        p.start("claude", ["-p", prompt, "--output-format", "text", "--tools", "", "--model", self.model, "--no-session-persistence",
                           "--strict-mcp-config", "--setting-sources", "", "--system-prompt", SYSTEM])
        p.closeWriteChannel()

    def cancel(self):
        if self.proc:
            p, self.proc = self.proc, None
            self._timer.stop()
            p.kill()
            self.busyChanged.emit(False)
