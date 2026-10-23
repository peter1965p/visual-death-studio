"""LSP-Client über stdio (JSON-RPC mit Content-Length-Rahmen)."""
import json

from PySide6.QtCore import QObject, QProcess, Signal


class LspClient(QObject):
    notification = Signal(str, object)     # Methode, Parameter
    serverRequest = Signal(str, object, int)   # Methode, Parameter, Anfrage-ID (Antwort per reply())
    closed = Signal(int)

    def __init__(self, cmd: list, cwd: str | None = None, parent=None):
        super().__init__(parent)
        self.cmd, self.cwd = cmd, cwd
        self.proc: QProcess | None = None
        self.id = 0
        self.pending: dict = {}
        self.buf = b""
        self._closing = False

    def start(self):
        p = QProcess(self)
        if self.cwd:
            p.setWorkingDirectory(self.cwd)
        p.readyReadStandardOutput.connect(self._read)
        p.readyReadStandardError.connect(lambda: p.readAllStandardError())     # Server-Log verwerfen
        p.finished.connect(self._finished)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self.closed.emit(127))
        self.proc = p
        p.start(self.cmd[0], self.cmd[1:])

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def stop(self):
        self._closing = True
        if self.alive:
            self.notify("exit", None)
            self.proc.kill()
            self.proc.waitForFinished(500)

    def _finished(self, code, _status):
        if not self._closing:
            self.closed.emit(code)

    # --- Senden ----------------------------------------------------------------------------------------------
    def _send(self, msg: dict):
        if not self.alive:
            return
        data = json.dumps({"jsonrpc": "2.0", **msg}).encode("utf-8")
        self.proc.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)

    def request(self, method: str, params, cb=None):
        """cb(result, error) – error ist None bei Erfolg."""
        self.id += 1
        if cb:
            self.pending[self.id] = cb
        self._send({"id": self.id, "method": method, "params": params})
        return self.id

    def reply(self, req_id: int, result):
        self._send({"id": req_id, "result": result})

    def notify(self, method: str, params):
        self._send({"method": method, "params": params})

    # --- Empfangen -----------------------------------------------------------------------------------------------
    def _read(self):
        self.buf += bytes(self.proc.readAllStandardOutput())
        while True:
            head, sep, rest = self.buf.partition(b"\r\n\r\n")
            if not sep:
                return
            length = next((int(h.split(b":")[1]) for h in head.split(b"\r\n") if h.lower().startswith(b"content-length")), None)
            if length is None or len(rest) < length:
                return
            body, self.buf = rest[:length], rest[length:]
            try:
                self._handle(json.loads(body))
            except ValueError:
                pass

    def _handle(self, m: dict):
        if "method" in m and "id" in m:                     # Anfrage des Servers
            if m["method"] == "workspace/applyEdit":
                return self.serverRequest.emit(m["method"], m.get("params"), m["id"])
            result = [None] * len((m.get("params") or {}).get("items", [])) if m["method"] == "workspace/configuration" else None
            self._send({"id": m["id"], "result": result})
        elif "method" in m:
            self.notification.emit(m["method"], m.get("params"))
        elif "id" in m:
            cb = self.pending.pop(m["id"], None)
            if cb:
                cb(m.get("result"), m.get("error"))
