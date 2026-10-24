"""Anbindung an die lokale Claude-Code-CLI (`claude -p`, Stream-JSON). Nutzt die bestehende Anmeldung – kein API-Key nötig."""
import glob
import json
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

FILE_TOOLS = "Write,Edit,Read,Glob,Grep"


def find() -> str | None:
    """Pfad von Claude Code (`claude`). Ein per Starter/Menü gestartetes Programm erbt oft einen PATH ohne ~/.local/bin oder nvm – daher auch die üblichen Orte."""
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    cands = [home / ".local/bin/claude", home / ".claude/local/claude", home / ".npm-global/bin/claude", home / ".bun/bin/claude",
             Path("/usr/local/bin/claude"), Path("/usr/bin/claude"), Path("/opt/claude/bin/claude")]
    cands += [Path(p) for p in sorted(glob.glob(str(home / ".nvm/versions/node/*/bin/claude")), reverse=True)]
    return next((str(c) for c in cands if c.is_file() and os.access(c, os.X_OK)), None)


def available() -> bool:
    return find() is not None


def describe_tool(name: str, inp: dict, cwd: Path) -> str:
    """Kurzbeschreibung eines Tool-Aufrufs für die Anzeige (Pfade relativ zum Projekt)."""
    def rel(p):
        try:
            return str(Path(p).relative_to(cwd))
        except ValueError:
            return str(p)
    if "file_path" in inp:
        return f"{name} {rel(inp['file_path'])}"
    if name == "Bash":
        return "Bash: " + str(inp.get("command", ""))[:80]
    return f"{name} {inp.get('pattern', '')}".strip()


class ClaudeProcess(QObject):
    text = Signal(str)                 # fertiger Textblock des Assistenten
    tool = Signal(str)                 # z. B. "Write main.py"
    finished = Signal(bool, str, str)  # ok, Ergebnistext bzw. Fehlermeldung, session_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: QProcess | None = None
        self._buf = ""
        self._err = ""
        self._cwd = Path(".")
        self._result: tuple | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None

    def run(self, prompt: str, cwd: Path, session: str | None = None, allow_bash: bool = False,
            system: str | None = None, max_turns: int = 30):
        if self.running:
            return
        self._cwd, self._buf, self._err, self._result = Path(cwd), "", "", None
        tools = FILE_TOOLS + (",Bash" if allow_bash else "")
        args = ["-p", prompt, "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
                "--allowedTools", tools, "--max-turns", str(max_turns)]
        if session:
            args += ["--resume", session]
        if system:
            args += ["--append-system-prompt", system]
        p = QProcess(self)
        p.setWorkingDirectory(str(cwd))
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.readyReadStandardOutput.connect(self._read)
        p.readyReadStandardError.connect(lambda: setattr(self, "_err", self._err + bytes(p.readAllStandardError()).decode("utf-8", "replace")))
        p.errorOccurred.connect(self._error)
        p.finished.connect(self._done)
        self.proc = p
        p.start(find() or "claude", args)
        p.closeWriteChannel()

    def stop(self):
        if self.proc:
            self.proc.kill()

    def _error(self, e):
        if e == QProcess.FailedToStart and self.proc:
            self.proc = None
            self.finished.emit(False, "Claude Code ('claude') konnte nicht gestartet werden.", "")

    def _read(self):
        self._buf += bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        *lines, self._buf = self._buf.split("\n")
        for line in lines:
            self._handle(line.strip())

    def _handle(self, line: str):
        if not line.startswith("{"):
            return
        try:
            m = json.loads(line)
        except ValueError:
            return
        t = m.get("type")
        if t == "assistant":
            for c in m.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    self.text.emit(c["text"])
                elif c.get("type") == "tool_use":
                    self.tool.emit(describe_tool(c.get("name", "?"), c.get("input") or {}, self._cwd))
        elif t == "result":
            self._result = (not m.get("is_error", False), m.get("result") or "", m.get("session_id", ""))

    def _done(self, code, _status):
        if self._buf.strip():
            self._handle(self._buf.strip())
        self.proc = None
        if self._result:
            self.finished.emit(*self._result)
        else:
            self.finished.emit(False, (self._err.strip() or f"Claude wurde beendet (Code {code})."), "")
