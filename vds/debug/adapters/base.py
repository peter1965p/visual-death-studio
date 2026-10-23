"""Gemeinsame Basis für eingebaute Debug-Adapter, die kein DAP sprechen (Node/V8-Inspector, Java/jdb).
Sie bieten dieselbe Schnittstelle wie DapClient, damit DebugSession sie austauschbar benutzen kann."""
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class ShimAdapter(QObject):
    event = Signal(str, dict)
    reverseRequest = Signal(dict)
    stderrText = Signal(str)
    closed = Signal(int)

    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self.root = str(root) if root else None
        self.proc: QProcess | None = None
        self._closing = False

    # --- DapClient-Schnittstelle ---------------------------------------------------------------------------------
    def start(self):
        """Der eigentliche Start passiert beim launch-Request."""

    @property
    def alive(self) -> bool:
        return not self._closing

    def respond(self, req, success=True, body=None, message=""):
        pass

    def request(self, command: str, args: dict | None = None, cb=None):
        handler = getattr(self, "_do_" + command, None)
        if handler is None:
            return self._reply(cb, False, {}, f"'{command}' wird nicht unterstützt")
        handler(args or {}, cb)

    def _reply(self, cb, ok=True, body=None, message=""):
        """Antworten asynchron liefern – die Sitzung erwartet dieselbe Reihenfolge wie bei echten Adaptern."""
        if cb:
            QTimer.singleShot(0, lambda: cb(ok, body or {}, message))

    def stop(self):
        self._closing = True
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()
            self.proc.waitForFinished(500)

    def write_stdin(self, text: str) -> bool:
        if self.proc and self.proc.state() == QProcess.Running:
            self.proc.write(text.encode())
            return True
        return False

    # --- Hilfen für Unterklassen ------------------------------------------------------------------------------------
    def out(self, text: str, category: str = "stdout"):
        if text:
            self.event.emit("output", {"category": category, "output": text})

    def _do_threads(self, a, cb):
        self._reply(cb, True, {"threads": [{"id": 1, "name": "main"}]})

    def _do_setExceptionBreakpoints(self, a, cb):
        self._reply(cb, True)
