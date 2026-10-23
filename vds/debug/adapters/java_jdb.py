"""Java-Debugger: Das Programm läuft mit JDWP-Agent als eigener Prozess (eigenes stdin/stdout), `jdb -attach` steuert es.
Die jdb-Ausgabe wird auf Englisch erzwungen und in DAP-Antworten/-Ereignisse übersetzt."""
import re
import shutil
from collections import deque
from pathlib import Path

from PySide6.QtCore import QProcess

from .base import ShimAdapter

PROMPT = re.compile(r"(?:^|\n)[\w$.\-]+\[\d+\] $")
LISTENING = re.compile(r"Listening for transport dt_socket at address:\s*(?:[\w.]+:)?(\d+)")
HIT = re.compile(r'Breakpoint hit: "thread=[^"]*", ([\w$.<>]+)\(\), line=(\d+)')
STEP = re.compile(r'Step completed: "thread=[^"]*", ([\w$.<>]+)\(\), line=(\d+)')
EXC = re.compile(r"Exception occurred: ([\w$.]+) \(uncaught\)")
FRAME = re.compile(r"\[(\d+)\]\s+(\S+)\s+\((.+?):(\d+)\)")
VAR = re.compile(r"^\s*([\w$]+) = (.*)$")
FIELD = re.compile(r"^\s*([\w$]+): (.*)$")
ERRORS = ("ParseException", "Name unknown", "InvocationException", "Internal exception", "Unable to", "No code at line", "not a valid")
FRAME_BASE = 1_000_000


def scan_classes(text: str, package: str = "") -> list:
    """[(binärer Klassenname, Startzeile, Endzeile)] für class/interface/enum/record-Deklarationen (mit Verschachtelung Äußere$Innere)."""
    out, stack, depth, line = [], [], 0, 1
    pending: list = []
    i, n = 0, len(text)
    decl = re.compile(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)")
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            line += text.count("\n", i, end); i = end
            continue
        elif c in "\"'":
            q = c; i += 1
            while i < n and text[i] != q:
                if text[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        elif c == "{":
            depth += 1
            if pending:
                name = pending.pop()
                full = "$".join([s[0] for s in stack] + [name])
                stack.append((name, depth, line, len(out)))
                out.append([package + full if package else full, line, line])
        elif c == "}":
            if stack and stack[-1][1] == depth:
                _, _, _, idx = stack.pop()
                out[idx][2] = line
            depth -= 1
        else:
            m = decl.match(text, i) if c in "cief r" or c.isalpha() else None
            if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                pending.append(m.group(1)); i = m.end(); continue
        i += 1
    return [tuple(x) for x in out]


class JavaAdapter(ShimAdapter):
    def __init__(self, root=None, parent=None):
        super().__init__(root, parent)
        self.jdb: QProcess | None = None
        self.buf = ""
        self.suspended = False
        self.cmdq: deque = deque()
        self.inflight = None
        self.frames: list = []
        self.cur_frame = 0
        self.refs: dict = {}
        self._next_ref = 1
        self.sourcepath = "."
        self.conds: dict = {}
        self.bps: dict[str, list] = {}
        self._configured = False
        self._ready = False
        self._out_buf = ""
        self._exited = False

    # --- Start ----------------------------------------------------------------------------------------------------------
    def _do_initialize(self, a, cb):
        self._reply(cb, True, {"supportsConfigurationDoneRequest": True, "supportsConditionalBreakpoints": True})

    def _do_launch(self, a, cb):
        java, jdb = shutil.which("java"), shutil.which("jdb")
        if not java or not jdb:
            return self._reply(cb, False, {}, "java und jdb (JDK) werden benötigt")
        self.sourcepath = a.get("sourcepath") or "."
        p = QProcess(self)
        if a.get("cwd"):
            p.setWorkingDirectory(a["cwd"])
        p.readyReadStandardOutput.connect(self._debuggee_out)
        p.readyReadStandardError.connect(lambda: self.out(bytes(p.readAllStandardError()).decode("utf-8", "replace"), "stderr"))
        p.finished.connect(self._debuggee_done)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self.closed.emit(127))
        self.proc = p
        p.start(java, ["-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=127.0.0.1:0", "-cp", a.get("classpath", "."),
                       *a.get("javaArgs", []), a["mainClass"], *a.get("args", [])])
        self._reply(cb, True)

    def _debuggee_out(self):
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        if self.jdb is None:
            self._out_buf += text
            m = LISTENING.search(self._out_buf)
            if m:
                text = LISTENING.sub("", self._out_buf).lstrip("\n")
                self._out_buf = ""
                self._attach(int(m.group(1)))
            else:
                return
        self.out(text)

    def _attach(self, port: int):
        j = QProcess(self)
        j.setProcessChannelMode(QProcess.MergedChannels)
        j.readyReadStandardOutput.connect(self._jdb_data)
        j.finished.connect(lambda c, s: None)
        self.jdb = j
        j.start(shutil.which("jdb"), ["-J-Duser.language=en", "-J-Duser.country=US", "-attach", f"127.0.0.1:{port}", "-sourcepath", self.sourcepath])

    # --- jdb-Ein-/Ausgabe ---------------------------------------------------------------------------------------------------
    def _jdb_data(self):
        self.buf += bytes(self.jdb.readAllStandardOutput()).decode("utf-8", "replace")
        m = PROMPT.search(self.buf)
        if not m or not self.buf.endswith(m.group(0)):
            return
        text, self.buf = self.buf[:m.start()], ""
        self.suspended = True
        if not self._ready:                          # VM ist am Start angehalten: Haltepunkte setzen lassen
            self._ready = True
            return self.event.emit("initialized", {})
        job, self.inflight = self.inflight, None
        if job and job[0] == "cmd":
            job[1](text)
        else:
            self._stopped(text, job[1] if job else "")
        self._pump()

    def _enqueue(self, cmd: str, cb, resume: str = ""):
        self.cmdq.append((cmd, cb, resume))
        self._pump()

    def _pump(self):
        if not self.suspended or self.inflight or not self.cmdq or not self.jdb:
            return
        cmd, cb, resume = self.cmdq.popleft()
        self.suspended = False
        self.inflight = ("resume", resume) if resume else ("cmd", cb or (lambda text: None))
        if resume:
            self.frames, self.cur_frame = [], 0
            self.event.emit("continued", {"threadId": 1})
        self.jdb.write((cmd + "\n").encode())

    def _stopped(self, text: str, how: str):
        """Auswertung nach cont/next/step: Haltepunkt, Schritt, Ausnahme oder Programmende."""
        if "The application exited" in text or "The application has been disconnected" in text:
            return
        m = HIT.search(text)
        if m:
            cls, line = m.group(1).rsplit(".", 1)[0], int(m.group(2))
            cond = self.conds.get((cls, line))
            if cond:                                  # jdb kennt keine bedingten Haltepunkte: hier auswerten
                def check(res):
                    if re.search(r"= false\s*$", res.strip()):
                        self._enqueue("cont", None, "continue")
                    else:
                        self.event.emit("stopped", {"reason": "breakpoint", "threadId": 1})
                return self._enqueue("eval " + cond, check)
            return self.event.emit("stopped", {"reason": "breakpoint", "threadId": 1})
        m = EXC.search(text)
        if m:
            return self.event.emit("stopped", {"reason": "exception", "threadId": 1, "text": m.group(1)})
        if STEP.search(text):
            return self.event.emit("stopped", {"reason": "step", "threadId": 1})
        if how == "pause" or how:
            return self.event.emit("stopped", {"reason": "step" if how != "continue" else "breakpoint", "threadId": 1})

    def _debuggee_done(self, code, _status):
        if self._exited or self._closing:
            return
        self._exited = True
        if self.jdb and self.jdb.state() != QProcess.NotRunning:
            self.jdb.kill()
        self.event.emit("exited", {"exitCode": code})
        self.event.emit("terminated", {})

    # --- Quellen & Klassen ----------------------------------------------------------------------------------------------------
    def _class_for(self, path: str, line: int):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.M)
        package = (pkg.group(1) + ".") if pkg else ""
        best = None
        for name, a, b in scan_classes(text, package):
            if a <= line <= b and (best is None or a >= best[1]):
                best = (name, a)
        return best[0] if best else package + Path(path).stem

    def _resolve_source(self, qualified: str, fname: str) -> str | None:
        rel = qualified.split("$")[0].replace(".", "/") + ".java"
        for root in self.sourcepath.split(":"):
            cand = Path(root) / rel
            if cand.exists():
                return str(cand.resolve())
        for root in self.sourcepath.split(":"):
            hits = list(Path(root).rglob(fname))
            if hits:
                return str(hits[0].resolve())
        return None

    # --- DAP-Anfragen ------------------------------------------------------------------------------------------------------------
    def _do_setBreakpoints(self, a, cb):
        path = a["source"]["path"]
        for cls, line in self.bps.pop(path, []):
            self._enqueue(f"clear {cls}:{line}", None)
            self.conds.pop((cls, line), None)
        results, wanted = [], a.get("breakpoints", [])
        if not wanted:
            return self._reply(cb, True, {"breakpoints": []})
        left = [len(wanted)]
        mine = self.bps.setdefault(path, [])
        for bp in wanted:
            cls = self._class_for(path, bp["line"])
            if not cls:
                results.append({"verified": False, "line": bp["line"]}); left[0] -= 1
                continue
            mine.append((cls, bp["line"]))
            if bp.get("condition"):
                self.conds[(cls, bp["line"])] = bp["condition"]
            res = {"verified": True, "line": bp["line"]}
            results.append(res)

            def done(text, res=res):
                if any(e in text for e in ERRORS):
                    res["verified"] = False
                left[0] -= 1
                if left[0] == 0 and cb:
                    cb(True, {"breakpoints": results}, "")
            self._enqueue(f"stop at {cls}:{bp['line']}", done)
        if left[0] == 0:
            self._reply(cb, True, {"breakpoints": results})

    def _do_setExceptionBreakpoints(self, a, cb):
        self._enqueue("catch uncaught java.lang.Throwable", lambda t: cb and cb(True, {}, ""))

    def _do_configurationDone(self, a, cb):
        self._configured = True
        self._reply(cb, True)
        self._enqueue("cont", None, "continue")

    def _do_stackTrace(self, a, cb):
        def got(text):
            frames = []
            for m in FRAME.finditer(text):
                idx, qual, fname, line = int(m.group(1)) - 1, m.group(2), m.group(3), int(m.group(4))
                cls, _, method = qual.rpartition(".")
                cls = cls.split("/")[-1]
                src = self._resolve_source(cls, fname)
                frames.append({"id": idx, "name": f"{cls.split('.')[-1]}.{method}", "line": line, "column": 1,
                               **({"source": {"path": src, "name": fname}} if src else {})})
            self.frames = frames
            cb(True, {"stackFrames": frames, "totalFrames": len(frames)}, "")
        self._enqueue("where", got)

    def _do_scopes(self, a, cb):
        self._reply(cb, True, {"scopes": [{"name": "Locals", "variablesReference": FRAME_BASE + a.get("frameId", 0), "expensive": False}]})

    def _select_frame(self, i: int):
        d = i - self.cur_frame
        if d > 0:
            self._enqueue(f"up {d}", lambda t: None)
        elif d < 0:
            self._enqueue(f"down {-d}", lambda t: None)
        self.cur_frame = i

    def _mk(self, name: str, value: str, expr: str) -> dict:
        m = re.match(r"instance of ([\w$.\[\]<>]+?)\s*\(id=(\d+)\)", value)
        if m:
            r = self._next_ref
            self._next_ref += 1
            self.refs[r] = expr
            return {"name": name, "value": f"{m.group(1).split('.')[-1]} (id={m.group(2)})", "type": m.group(1), "variablesReference": r}
        typ = "String" if value.startswith('"') else "char" if value.startswith("'") else ""
        return {"name": name, "value": value, "type": typ, "variablesReference": 0}

    def _do_variables(self, a, cb):
        ref = a.get("variablesReference", 0)
        if ref >= FRAME_BASE:
            self._select_frame(ref - FRAME_BASE)

            def got(text):
                out = []
                for line in text.splitlines():
                    m = VAR.match(line)
                    if m and not line.startswith(("Method arguments", "Local variables")):
                        out.append(self._mk(m.group(1), m.group(2).strip(), m.group(1)))
                cb(True, {"variables": out}, "")
            return self._enqueue("locals", got)
        expr = self.refs.get(ref)
        if not expr:
            return self._reply(cb, True, {"variables": []})

        def dumped(text):
            out = []
            lines = [l for l in text.splitlines() if l.strip()]
            fields = [FIELD.match(l) for l in lines[1:-1]]
            if lines and fields and all(fields):
                for m in fields:
                    out.append(self._mk(m.group(1), m.group(2).strip(), f"{expr}.{m.group(1)}"))
            else:                                       # Array/Liste: Elemente durch Komma getrennt
                body = " ".join(lines[1:-1]) if len(lines) > 2 else ""
                for i, el in enumerate([x.strip() for x in body.split(",") if x.strip()]):
                    out.append(self._mk(f"[{i}]", el, f"{expr}[{i}]"))
            cb(True, {"variables": out}, "")
        self._enqueue("dump " + expr, dumped)

    def _do_evaluate(self, a, cb):
        fid = a.get("frameId")
        if fid is not None and fid != self.cur_frame:
            self._select_frame(fid)
        expr = a.get("expression", "")

        def got(text):
            if any(e in text for e in ERRORS):
                msg = next((l for l in text.splitlines() if any(e in l for e in ERRORS)), "Fehler")
                return cb(False, {}, msg.split(":")[-1].strip())
            m = re.search(r"^\s*(.*?) = (.*)$", text.strip(), re.S)
            if not m:
                return cb(False, {}, "keine Antwort")
            v = self._mk(expr, m.group(2).strip(), expr)
            cb(True, {"result": v["value"], "type": v["type"], "variablesReference": v["variablesReference"]}, "")
        self._enqueue("eval " + expr, got)

    def _do_continue(self, a, cb): self._reply(cb, True); self._enqueue("cont", None, "continue")
    def _do_next(self, a, cb): self._reply(cb, True); self._enqueue("next", None, "next")
    def _do_stepIn(self, a, cb): self._reply(cb, True); self._enqueue("step", None, "step")
    def _do_stepOut(self, a, cb): self._reply(cb, True); self._enqueue("step up", None, "step")
    def _do_pause(self, a, cb): self._reply(cb, False, {}, "Unterbrechen wird für Java (jdb) nicht unterstützt")

    def _do_disconnect(self, a, cb):
        self._reply(cb, True)
        self._closing = True
        if self.jdb and self.jdb.state() != QProcess.NotRunning:
            self.jdb.kill(); self.jdb.waitForFinished(300)
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill(); self.proc.waitForFinished(500)
        self.event.emit("terminated", {})

    def stop(self):
        self._closing = True
        for p in (self.jdb, self.proc):
            if p and p.state() != QProcess.NotRunning:
                p.kill(); p.waitForFinished(500)
