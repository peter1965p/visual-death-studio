"""Debug-Sitzung: kapselt DAP-Client und Zustand (angehalten/läuft), Aufrufliste, Variablen, Ausdrücke, Programmausgabe."""
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .dap import DapClient, TcpDapClient


@dataclass
class Frame:
    id: int
    name: str
    path: str | None
    line: int
    column: int = 1


@dataclass
class Bp:
    line: int
    condition: str = ""


def python_spec(file: Path, interp: str):
    """Adapter-Kommando + Launch-Argumente für Python (debugpy mit mitgeliefertem Adapter – braucht kein debugpy im Projekt)."""
    return ("python", lambda root: DapClient([sys.executable, "-m", "debugpy.adapter"], str(root)),
            {"type": "python", "request": "launch", "name": "Visual Death Studio", "program": str(file), "cwd": str(file.parent),
             "python": [interp], "console": "integratedTerminal", "justMyCode": True, "args": []})


def python_module_spec(module: str, args: list, cwd: Path, interp: str):
    """Python-Modul im Debugger starten, z. B. `python -m pytest <test-id>` – zum Debuggen einzelner Tests."""
    return ("python", lambda root: DapClient([sys.executable, "-m", "debugpy.adapter"], str(root)),
            {"type": "python", "request": "launch", "name": "Visual Death Studio", "module": module, "args": list(args), "cwd": str(cwd),
             "python": [interp], "console": "integratedTerminal", "justMyCode": True})


def node_spec(file: Path, cwd: Path, typescript: bool = False):
    """Node.js (und TypeScript über --experimental-strip-types) über den eingebauten V8-Inspector-Adapter."""
    from .adapters.node_cdp import NodeAdapter
    return ("node", lambda root: NodeAdapter(root), {"program": str(file), "cwd": str(cwd), "args": [],
                                                       "runtimeArgs": ["--experimental-strip-types"] if typescript else []})


def java_spec(main_class: str, classpath: Path, sourcepath: Path, cwd: Path):
    """Java über JDWP + jdb (-attach). Das Programm muss mit -g kompiliert sein."""
    from .adapters.java_jdb import JavaAdapter
    return ("java", lambda root: JavaAdapter(root), {"mainClass": main_class, "classpath": str(classpath), "sourcepath": str(sourcepath),
                                                       "cwd": str(cwd), "args": []})


def go_spec(program: Path, cwd: Path, dlv: str = "dlv"):
    """Go über Delve (`dlv dap`, DAP über TCP). Delve baut das Programm selbst und braucht dafür die Go-Toolchain."""
    return ("go", lambda root: TcpDapClient([dlv, "dap", "--listen=127.0.0.1:0"], str(root)),
            {"request": "launch", "mode": "debug", "program": str(program), "cwd": str(cwd), "args": []})


def csharp_spec(dll: Path, cwd: Path, netcoredbg: str = "netcoredbg"):
    """C# über netcoredbg (DAP über stdio); das Projekt muss vorher mit `dotnet build` gebaut sein."""
    return ("csharp", lambda root: DapClient([netcoredbg, "--interpreter=vscode"], str(root)),
            {"request": "launch", "program": "dotnet", "args": [str(dll)], "cwd": str(cwd), "stopAtEntry": False})


def native_spec(binary: Path, cwd: Path):
    """C/C++/Rust über gdbs DAP-Modus (gdb >= 14); das Programm muss mit Debug-Symbolen (-g) gebaut sein."""
    return ("native", lambda root: DapClient(["gdb", "-i", "dap"], str(root)), {"program": str(binary), "cwd": str(cwd), "args": []})


class DebugSession(QObject):
    stateChanged = Signal(str)            # starting | running | paused | ended
    paused = Signal(str, str)             # Grund (breakpoint|step|exception|pause|…), Text (z. B. Ausnahme)
    framesChanged = Signal(list, int)     # Frames, ausgewählter Index
    output = Signal(str, str)             # Text, Art: stdout|stderr|info
    breakpointState = Signal(str, list)   # Pfad, [(Zeile, verifiziert)]
    ended = Signal(int)                   # Exit-Code (-1 unbekannt)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client: DapClient | None = None
        self.kind = ""
        self.state = "idle"
        self.thread_id: int | None = None
        self.frames: list[Frame] = []
        self.sel = 0
        self.procs: list[QProcess] = []
        self.bps: dict[str, list[Bp]] = {}
        self._started = False
        self._exit: int | None = None
        self._finished = False

    # --- Lebenszyklus -----------------------------------------------------------------------------------
    def start(self, spec, root: Path, bps: dict):
        self.kind, factory, launch = spec
        self.bps = bps
        c = factory(root)
        c.setParent(self)
        self.client = c
        c.event.connect(self._on_event)
        c.reverseRequest.connect(self._on_reverse)
        c.closed.connect(self._on_closed)
        c.stderrText.connect(self._adapter_text)
        self._set("starting")
        c.start()
        if not c.alive and c.proc is not None and c.proc.state() == QProcess.NotRunning:
            pass     # FailedToStart wird über closed gemeldet
        c.request("initialize", {"clientID": "visual-death-studio", "adapterID": self.kind, "linesStartAt1": True, "columnsStartAt1": True,
                                 "pathFormat": "path", "supportsRunInTerminalRequest": True, "supportsVariableType": True})
        c.request("launch", launch, self._launched)

    def _adapter_text(self, text: str):
        """Text, den der Adapter-Prozess selbst ausgibt (bei Delve ist das auch die Ausgabe des Programms)."""
        if self.kind == "python":
            if "Traceback" in text:
                self.output.emit(text, "stderr")
        elif self.kind == "go":
            text = "".join(l for l in text.splitlines(True) if "Type 'dlv help'" not in l)
            if text:
                self.output.emit(text, "stdout")

    def _launched(self, ok, body, msg):
        if not ok:
            self.output.emit(f"Debugger konnte das Programm nicht starten: {msg}\n", "stderr")
            self._finish(-1)

    def stop(self):
        if self._finished or not self.client:
            return
        self.client.request("disconnect", {"terminateDebuggee": True})
        QTimer.singleShot(1500, lambda: self._finish(self._exit if self._exit is not None else -1))

    def _set(self, state):
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)

    def _finish(self, code):
        if self._finished:
            return
        self._finished = True
        for p in self.procs:
            if p.state() != QProcess.NotRunning:
                p.kill()
        if self.client:
            self.client.stop()
        self.frames = []
        self._set("ended")
        self.ended.emit(code if code is not None else -1)

    def _on_closed(self, code):
        self._finish(self._exit if self._exit is not None else (code if code == 127 else -1))

    # --- Ereignisse -------------------------------------------------------------------------------------
    def _on_event(self, name, body):
        c = self.client
        if name == "initialized":
            for path, bps in self.bps.items():
                self._send_breakpoints(path, bps)
            if self.kind in ("python", "node"):
                c.request("setExceptionBreakpoints", {"filters": ["uncaught"]})
            c.request("configurationDone", {}, lambda ok, b, m: self._set("running"))
        elif name == "process":
            self._started = True
        elif name == "output":
            cat = body.get("category", "console")
            if cat == "telemetry" or (self.kind == "native" and not self._started):
                return
            self.output.emit(body.get("output", ""), "stderr" if cat == "stderr" else "info" if cat in ("console", "important") else "stdout")
        elif name == "stopped":
            self.thread_id = body.get("threadId", self.thread_id)
            self._set("paused")
            self._load_frames(body.get("reason", "pause"), body.get("text", ""))
        elif name == "continued":
            self._set("running")
        elif name == "exited":
            self._exit = body.get("exitCode")
        elif name == "terminated":
            QTimer.singleShot(150, lambda: self._finish(self._exit if self._exit is not None else 0))
        elif name == "breakpoint":
            bp = body.get("breakpoint", {})
            src = (bp.get("source") or {}).get("path")
            if src and bp.get("line"):
                self.breakpointState.emit(src, [(bp["line"], bool(bp.get("verified")))])

    def _load_frames(self, reason, text):
        def got(ok, body, msg):
            self.frames = [Frame(f["id"], f.get("name", "?"), (f.get("source") or {}).get("path"), f.get("line", 0), f.get("column", 1))
                           for f in body.get("stackFrames", [])] if ok else []
            self.sel = 0
            self.framesChanged.emit(self.frames, 0)
            if reason == "exception" and self.kind == "python":
                self.client.request("exceptionInfo", {"threadId": self.thread_id},
                                    lambda ok2, b2, m2: self.paused.emit(reason, f"{b2.get('exceptionId', '')}: {(b2.get('description') or '').strip()}" if ok2 else text))
            else:
                self.paused.emit(reason, text)
        self.client.request("stackTrace", {"threadId": self.thread_id, "levels": 60}, got)

    # --- Programm-I/O über runInTerminal --------------------------------------------------------------------
    def _on_reverse(self, req):
        if req.get("command") != "runInTerminal":
            return self.client.respond(req, False, message="nicht unterstützt")
        a = req["arguments"]
        p = QProcess(self)
        p.setWorkingDirectory(a.get("cwd") or ".")
        env = QProcessEnvironment.systemEnvironment()
        for k, v in (a.get("env") or {}).items():
            env.remove(k) if v is None else env.insert(k, str(v))
        env.insert("PYTHONUNBUFFERED", "1")
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(lambda: self.output.emit(bytes(p.readAllStandardOutput()).decode("utf-8", "replace"), "stdout"))
        p.readyReadStandardError.connect(lambda: self.output.emit(bytes(p.readAllStandardError()).decode("utf-8", "replace"), "stderr"))
        self.procs.append(p)
        p.start(a["args"][0], a["args"][1:])
        if p.waitForStarted(5000):
            self.client.respond(req, True, {"processId": int(p.processId())})
        else:
            self.client.respond(req, False, message="Prozess konnte nicht gestartet werden")

    def write_stdin(self, text: str):
        if self.client and hasattr(self.client, "write_stdin") and self.client.write_stdin(text):
            return              # Adapter besitzt den Prozess selbst (Node, Java)
        for p in self.procs:
            if p.state() == QProcess.Running:
                p.write(text.encode())
                return

    # --- Haltepunkte ------------------------------------------------------------------------------------------
    def _send_breakpoints(self, path: str, bps: list):
        self.client.request("setBreakpoints", {"source": {"path": path}, "breakpoints": [
            {"line": b.line, **({"condition": b.condition} if b.condition else {})} for b in bps]},
            lambda ok, body, m: ok and self.breakpointState.emit(path, [(x.get("line", 0), bool(x.get("verified"))) for x in body.get("breakpoints", [])]))

    def set_breakpoints(self, path: str, bps: list):
        self.bps[path] = bps
        if self.client and self.client.alive and not self._finished:
            self._send_breakpoints(path, bps)

    # --- Steuerung -----------------------------------------------------------------------------------------------
    def _ctl(self, command):
        if self.client and self.client.alive and self.thread_id is not None and self.state in ("paused", "running"):
            self.client.request(command, {"threadId": self.thread_id})

    def resume(self): self._ctl("continue")
    def pause(self): self._ctl("pause")
    def step_over(self): self._ctl("next")
    def step_in(self): self._ctl("stepIn")
    def step_out(self): self._ctl("stepOut")

    # --- Daten abfragen ---------------------------------------------------------------------------------------------
    @property
    def frame(self) -> Frame | None:
        return self.frames[self.sel] if 0 <= self.sel < len(self.frames) else None

    def select_frame(self, i: int):
        if 0 <= i < len(self.frames):
            self.sel = i
            self.framesChanged.emit(self.frames, i)

    def scopes(self, cb):
        f = self.frame
        if not f or self.state != "paused":
            return cb([])
        self.client.request("scopes", {"frameId": f.id}, lambda ok, b, m: cb([(s["name"], s["variablesReference"]) for s in b.get("scopes", [])] if ok else []))

    def variables(self, ref: int, cb):
        self.client.request("variables", {"variablesReference": ref}, lambda ok, b, m: cb(
            [{"name": v.get("name", "?"), "value": v.get("value", ""), "type": v.get("type", ""), "ref": v.get("variablesReference", 0)}
             for v in b.get("variables", [])] if ok else []))

    def evaluate(self, expr: str, cb, context="watch"):
        f = self.frame
        args = {"expression": expr, "context": context, **({"frameId": f.id} if f else {})}
        self.client.request("evaluate", args, lambda ok, b, m: cb(ok, b.get("result", "") if ok else m, b.get("type", "") if ok else "", b.get("variablesReference", 0) if ok else 0))
