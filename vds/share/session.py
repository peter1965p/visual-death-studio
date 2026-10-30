"""Live Share: gemeinsames Bearbeiten eines Projekts über TCP (Zeilen-JSON). Der Host teilt seinen Ordner, Gäste verbinden sich mit einem Code.

Die Verbindung ist **nicht verschlüsselt** – gedacht für das lokale Netz oder ein VPN. Zugang hat nur, wer den Code (Token) kennt.
Synchronisiert wird der Text der bearbeiteten Dateien (letzter Schreiber gewinnt); neue/gelöschte Dateien werden nicht übertragen."""
import json
import secrets
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QNetworkInterface, QTcpServer, QTcpSocket

from ..ui.palette import list_files

MAX_FILE = 500_000
MAX_FILES = 400
MAX_LINE = 4_000_000


def safe_rel(root: Path, rel: str) -> Path | None:
    """Pfad innerhalb von root oder None (absolute Pfade und `..` werden abgelehnt)."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or ":" in rel.split("/")[0]:
        return None
    p = (Path(root) / rel).resolve()
    try:
        p.relative_to(Path(root).resolve())
    except ValueError:
        return None
    return p


def collect_files(root: Path) -> list:
    out = []
    for rel in list_files(root):
        p = Path(root) / rel
        try:
            if p.stat().st_size > MAX_FILE:
                continue
            data = p.read_bytes()
            if b"\0" in data[:4096]:
                continue
            out.append({"path": rel, "text": data.decode("utf-8")})
        except (OSError, UnicodeDecodeError):
            continue
        if len(out) >= MAX_FILES:
            break
    return out


def write_files(root: Path, files: list) -> int:
    n = 0
    for f in files:
        p = safe_rel(root, f.get("path"))
        if p is None or not isinstance(f.get("text"), str):
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["text"], encoding="utf-8")
        n += 1
    return n


def local_addresses() -> list:
    out = [a.toString() for a in QNetworkInterface.allAddresses()
           if a.protocol() == QAbstractSocket.IPv4Protocol and not a.isLoopback()]
    return out or ["127.0.0.1"]


def _send(sock: QTcpSocket, msg: dict):
    sock.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))


class ShareSession(QObject):
    peersChanged = Signal(list)           # Namen der verbundenen Gäste (Host)
    remoteEdit = Signal(str, str, str)    # relativer Pfad, Text, Name des Schreibers
    welcome = Signal(str, list)           # Gast: Projektname, Dateien
    status = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.role = ""
        self.root = Path(".")
        self.token = ""
        self.read_only = False
        self.name = "Gast"
        self.server: QTcpServer | None = None
        self.sock: QTcpSocket | None = None
        self.peers: dict = {}             # Socket -> Name (nur angemeldete)
        self._bufs: dict = {}

    @property
    def active(self) -> bool:
        return bool(self.role)

    # --- Host ---------------------------------------------------------------------------
    def host(self, root: Path, port: int = 0, read_only: bool = False, name: str = "Host") -> tuple:
        """(Port, Code) – der Code ist `Adresse:Port/Token` und wird dem Gast mitgeteilt."""
        self.stop()
        self.role, self.root, self.read_only, self.name = "host", Path(root), read_only, name
        self.token = secrets.token_urlsafe(9)
        self.server = QTcpServer(self)
        if not self.server.listen(QHostAddress.AnyIPv4, port):
            self.role = ""
            raise OSError(self.server.errorString())
        self.server.newConnection.connect(self._incoming)
        self.status.emit(f"Sitzung läuft auf Port {self.server.serverPort()}")
        return self.server.serverPort(), self.token

    def join_code(self, address: str | None = None) -> str:
        return f"{address or local_addresses()[0]}:{self.server.serverPort()}/{self.token}"

    def _incoming(self):
        while self.server and self.server.hasPendingConnections():
            s = self.server.nextPendingConnection()
            self._bufs[s] = b""
            s.readyRead.connect(lambda s=s: self._read(s))
            s.disconnected.connect(lambda s=s: self._gone(s))

    def _gone(self, s):
        self._bufs.pop(s, None)
        if self.peers.pop(s, None) is not None:
            self.peersChanged.emit(list(self.peers.values()))

    # --- Gast ---------------------------------------------------------------------------
    def join(self, code: str, name: str = "Gast", root: Path = Path(".")):
        self.stop()
        try:
            addr, rest = code.strip().rsplit("/", 1)[0], code.strip().rsplit("/", 1)[1]
            host, port = addr.rsplit(":", 1)
            port = int(port)
        except (ValueError, IndexError):
            raise ValueError("Der Code muss die Form Adresse:Port/Token haben.")
        self.role, self.root, self.name, self.token = "guest", Path(root), name, rest
        self.sock = QTcpSocket(self)
        self._bufs[self.sock] = b""
        self.sock.connected.connect(lambda: _send(self.sock, {"t": "hello", "token": self.token, "name": self.name}))
        self.sock.readyRead.connect(lambda: self._read(self.sock))
        self.sock.errorOccurred.connect(lambda _e: self.status.emit("Verbindung fehlgeschlagen: " + self.sock.errorString()))
        self.sock.disconnected.connect(self._lost)
        self.sock.connectToHost(host, port)

    def _lost(self):
        if self.role == "guest":
            self.status.emit("Verbindung zum Host getrennt.")
            self.stop()

    # --- gemeinsam ----------------------------------------------------------------------
    def send_edit(self, rel: str, text: str):
        if self.role == "host":
            for s in self.peers:
                _send(s, {"t": "edit", "path": rel, "text": text, "who": self.name})
        elif self.role == "guest" and self.sock and self.sock.state() == QAbstractSocket.ConnectedState:
            _send(self.sock, {"t": "edit", "path": rel, "text": text})

    def _read(self, s):
        self._bufs[s] = self._bufs.get(s, b"") + bytes(s.readAll())
        if len(self._bufs[s]) > MAX_LINE * 3:
            return s.disconnectFromHost()
        while s in self._bufs and b"\n" in self._bufs[s]:
            line, self._bufs[s] = self._bufs[s].split(b"\n", 1)
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(msg, dict):
                self._handle(s, msg)

    def _handle(self, s, msg):
        t = msg.get("t")
        if self.role == "host":
            if t == "hello":
                if not secrets.compare_digest(str(msg.get("token", "")), self.token):
                    _send(s, {"t": "deny"})
                    return s.disconnectFromHost()
                self.peers[s] = str(msg.get("name") or "Gast")[:40]
                _send(s, {"t": "welcome", "project": self.root.name, "files": collect_files(self.root), "read_only": self.read_only})
                self.peersChanged.emit(list(self.peers.values()))
            elif t == "edit" and s in self.peers and not self.read_only:
                p = safe_rel(self.root, msg.get("path"))
                if p is None or not isinstance(msg.get("text"), str) or not p.is_file():
                    return
                who = self.peers[s]
                for other in self.peers:
                    if other is not s:
                        _send(other, {"t": "edit", "path": msg["path"], "text": msg["text"], "who": who})
                self.remoteEdit.emit(msg["path"], msg["text"], who)
        elif self.role == "guest":
            if t == "welcome":
                self.read_only = bool(msg.get("read_only"))
                self.welcome.emit(str(msg.get("project", "")), msg.get("files", []))
            elif t == "deny":
                self.status.emit("Der Code wurde abgelehnt.")
                self.stop()
            elif t == "edit":
                if safe_rel(self.root, msg.get("path")) is not None and isinstance(msg.get("text"), str):
                    self.remoteEdit.emit(msg["path"], msg["text"], str(msg.get("who", "Host")))

    def stop(self):
        was = self.role
        self.role = ""
        for s in list(self._bufs):
            try:
                s.blockSignals(True)           # keine Rückrufe mehr in eine halb abgebaute Sitzung
                s.abort()
            except RuntimeError:
                pass
        self._bufs.clear(); self.peers.clear()
        if self.server:
            self.server.close(); self.server = None
        self.sock = None
        if was:
            self.closed.emit()
