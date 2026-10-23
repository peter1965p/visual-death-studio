"""Minimaler Debug-Adapter-Protocol-Client (DAP) über stdio eines Adapter-Prozesses (Content-Length-Rahmen, JSON)."""
import json
import re

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtNetwork import QAbstractSocket, QTcpSocket


class DapClient(QObject):
    event = Signal(str, dict)            # Ereignisname, Body
    reverseRequest = Signal(dict)        # Anfrage des Adapters (z. B. runInTerminal); Antwort per respond()
    stderrText = Signal(str)
    closed = Signal(int)

    def __init__(self, cmd: list, cwd: str | None = None, parent=None):
        super().__init__(parent)
        self.cmd, self.cwd = cmd, cwd
        self.proc: QProcess | None = None
        self.seq = 0
        self.pending: dict = {}
        self.buf = b""
        self._closing = False

    def start(self):
        p = QProcess(self)
        if self.cwd:
            p.setWorkingDirectory(self.cwd)
        p.readyReadStandardOutput.connect(self._read)
        p.readyReadStandardError.connect(lambda: self.stderrText.emit(bytes(p.readAllStandardError()).decode("utf-8", "replace")))
        p.finished.connect(self._proc_finished)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self.closed.emit(127))
        self.proc = p
        p.start(self.cmd[0], self.cmd[1:])

    def _proc_finished(self, code, _status):
        if not self._closing:
            self.closed.emit(code)

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def stop(self):
        self._closing = True
        if self.proc and self.alive:
            self.proc.kill()
            self.proc.waitForFinished(800)

    # --- Senden ----------------------------------------------------------------------------------------------
    def _send(self, msg: dict):
        if not self.alive:
            return
        data = json.dumps(msg).encode("utf-8")
        self._write(b"Content-Length: %d\r\n\r\n" % len(data) + data)

    def _write(self, data: bytes):
        self.proc.write(data)

    def request(self, command: str, args: dict | None = None, cb=None) -> int:
        """cb(success: bool, body: dict, message: str) wird bei der Antwort aufgerufen."""
        self.seq += 1
        if cb:
            self.pending[self.seq] = cb
        self._send({"seq": self.seq, "type": "request", "command": command, "arguments": args or {}})
        return self.seq

    def respond(self, req: dict, success: bool = True, body: dict | None = None, message: str = ""):
        self.seq += 1
        self._send({"seq": self.seq, "type": "response", "request_seq": req["seq"], "command": req["command"],
                    "success": success, "body": body or {}, **({"message": message} if message else {})})

    # --- Empfangen ----------------------------------------------------------------------------------------------
    def _read(self):
        self._feed(bytes(self.proc.readAllStandardOutput()))

    def _feed(self, data: bytes):
        self.buf += data
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
        t = m.get("type")
        if t == "response":
            cb = self.pending.pop(m.get("request_seq"), None)
            if cb:
                cb(bool(m.get("success")), m.get("body") or {}, m.get("message", ""))
        elif t == "event":
            self.event.emit(m.get("event", ""), m.get("body") or {})
        elif t == "request":
            self.reverseRequest.emit(m)


class TcpDapClient(DapClient):
    """DAP über TCP: Der Adapter-Prozess (z. B. `dlv dap --listen=127.0.0.1:0`) meldet seinen Port auf stdout."""

    def __init__(self, cmd, cwd=None, parent=None):
        super().__init__(cmd, cwd, parent)
        self.sock: QTcpSocket | None = None
        self._queue: list = []
        self._line_buf = ""

    def start(self):
        p = QProcess(self)
        if self.cwd:
            p.setWorkingDirectory(self.cwd)
        p.readyReadStandardOutput.connect(self._stdout)
        p.readyReadStandardError.connect(lambda: self.stderrText.emit(bytes(p.readAllStandardError()).decode("utf-8", "replace")))
        p.finished.connect(self._proc_finished)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self.closed.emit(127))
        self.proc = p
        p.start(self.cmd[0], self.cmd[1:])

    def _stdout(self):
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        if self.sock:
            return self.stderrText.emit(text)
        self._line_buf += text
        m = re.search(r"listening at:?\s*(?:\[?[\w.:]*?\]?:)?(\d+)\s*$|listening at:?\s*([\w.\[\]:]+):(\d+)", self._line_buf, re.M)
        if m:
            port = int(m.group(1) or m.group(3))
            self.sock = QTcpSocket(self)
            self.sock.connected.connect(self._flush)
            self.sock.readyRead.connect(lambda: self._feed(bytes(self.sock.readAll())))
            self.sock.disconnected.connect(lambda: None if self._closing else self.closed.emit(0))
            self.sock.connectToHost("127.0.0.1", port)

    def _write(self, data: bytes):
        if self.sock and self.sock.state() == QAbstractSocket.ConnectedState:
            self.sock.write(data)
        else:
            self._queue.append(data)

    def _flush(self):
        for d in self._queue:
            self.sock.write(d)
        self._queue.clear()

    def stop(self):
        self._closing = True
        if self.sock:
            self.sock.close()
        super().stop()
