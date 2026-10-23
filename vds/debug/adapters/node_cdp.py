"""Node.js-Debugger über das V8-Inspector-Protokoll (CDP) als DAP-kompatibler Adapter.
`node --inspect-brk=127.0.0.1:0 script.js` -> WebSocket -> Debugger.*/Runtime.* -> DAP-Ereignisse und -Antworten."""
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QProcess, QProcessEnvironment, QUrl
from PySide6.QtWebSockets import QWebSocket

from .base import ShimAdapter

WS_URL = re.compile(r"ws://[\d.]+:\d+/[\w-]+")
SCOPE_NAMES = {"local": "Locals", "closure": "Closure", "block": "Block", "script": "Script", "catch": "Catch", "with": "With", "module": "Module"}


class NodeAdapter(ShimAdapter):
    def __init__(self, root=None, parent=None):
        super().__init__(root, parent)
        self.ws: QWebSocket | None = None
        self._id = 0
        self._cb: dict = {}
        self._queue: list = []          # CDP-Nachrichten, die auf die Verbindung warten
        self._connected = False
        self.frames: list = []
        self.scripts: dict = {}         # scriptId -> URL (callFrames tragen selbst keine URL)
        self.refs: dict = {}
        self._next_ref = 1
        self.bp_ids: dict[str, list] = {}
        self._start_pause_seen = False
        self._configured = False
        self._waiting_start = False
        self._last_cmd = ""
        self._err_buf = ""

    # --- Start ------------------------------------------------------------------------------------------------------
    def _do_initialize(self, a, cb):
        self._reply(cb, True, {"supportsConfigurationDoneRequest": True, "supportsConditionalBreakpoints": True})

    def _do_launch(self, a, cb):
        node = shutil.which("node")
        if not node:
            return self._reply(cb, False, {}, "node ist nicht installiert")
        p = QProcess(self)
        if a.get("cwd"):
            p.setWorkingDirectory(a["cwd"])
        env = QProcessEnvironment.systemEnvironment()
        for k, v in (a.get("env") or {}).items():
            env.insert(k, str(v))
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(lambda: self.out(bytes(p.readAllStandardOutput()).decode("utf-8", "replace")))
        p.readyReadStandardError.connect(self._stderr)
        p.finished.connect(self._proc_done)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self.closed.emit(127))
        self.proc = p
        p.start(node, ["--inspect-brk=127.0.0.1:0", *a.get("runtimeArgs", []), a["program"], *a.get("args", [])])
        self._reply(cb, True)

    def _stderr(self):
        text = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
        if not self.ws:
            self._err_buf += text
            m = WS_URL.search(self._err_buf)
            if m:
                self._open_ws(m.group(0))
        if "Waiting for the debugger to disconnect" in text and self.ws:
            self.ws.close()                      # Node wartet am Programmende (oder nach einer Ausnahme), bis der Debugger sich trennt
        # die Inspector-Hinweise sind für Nutzer Rauschen
        keep = [l for l in text.splitlines(True) if not re.match(r"\s*(Debugger listening on|For help, see:|Debugger attached\.|Waiting for the debugger)", l)]
        self.out("".join(keep), "stderr")

    def _open_ws(self, url: str):
        ws = QWebSocket()
        ws.setParent(self)
        ws.textMessageReceived.connect(self._on_message)
        ws.connected.connect(self._on_connected)
        ws.disconnected.connect(lambda: None)
        self.ws = ws
        ws.open(QUrl(url))

    def _on_connected(self):
        self._connected = True
        for m in self._queue:
            self.ws.sendTextMessage(m)
        self._queue.clear()
        self.cdp("Runtime.enable")
        self.cdp("Debugger.enable", cb=lambda r, e: self.cdp("Runtime.runIfWaitingForDebugger", cb=lambda r2, e2: self.event.emit("initialized", {})))

    # --- CDP-Transport -------------------------------------------------------------------------------------------------
    def cdp(self, method: str, params: dict | None = None, cb=None):
        self._id += 1
        if cb:
            self._cb[self._id] = cb
        msg = json.dumps({"id": self._id, "method": method, "params": params or {}})
        if self._connected:
            self.ws.sendTextMessage(msg)
        else:
            self._queue.append(msg)

    def _on_message(self, text: str):
        m = json.loads(text)
        if "id" in m:
            cb = self._cb.pop(m["id"], None)
            if cb:
                cb(m.get("result"), m.get("error"))
        elif m.get("method"):
            self._on_event(m["method"], m.get("params") or {})

    def _on_event(self, method: str, p: dict):
        if method == "Debugger.scriptParsed":
            self.scripts[p.get("scriptId", "")] = p.get("url", "")
        elif method == "Debugger.paused":
            self._paused(p)
        elif method == "Debugger.resumed":
            self.event.emit("continued", {"threadId": 1})
        elif method == "Debugger.breakpointResolved":
            loc = p.get("location", {})
            self.event.emit("breakpoint", {"reason": "changed", "breakpoint": {"verified": True, "line": loc.get("lineNumber", 0) + 1}})

    def _paused(self, p: dict):
        self.frames = p.get("callFrames", [])
        self.refs.clear()
        self._next_ref = 1
        if not self._start_pause_seen:                     # erste Pause: --inspect-brk hält vor der ersten Zeile an
            self._start_pause_seen = True
            if not p.get("hitBreakpoints"):
                self._waiting_start = True
                if self._configured:
                    self._waiting_start = False
                    self.cdp("Debugger.resume")
                return
        reason = p.get("reason", "other")
        text = ""
        if p.get("hitBreakpoints"):
            r = "breakpoint"
        elif reason in ("exception", "promiseRejection"):
            r = "exception"
            text = ((p.get("data") or {}).get("description") or "").split("\n")[0]
        elif self._last_cmd == "pause":
            r = "pause"
        elif self._last_cmd in ("next", "stepIn", "stepOut"):
            r = "step"
        else:
            r = "breakpoint"                                 # z. B. eine debugger;-Anweisung
        self._last_cmd = ""
        self.event.emit("stopped", {"reason": r, "threadId": 1, "text": text})

    def _proc_done(self, code, _status):
        if self._closing:
            return
        self.event.emit("exited", {"exitCode": code})
        self.event.emit("terminated", {})

    # --- DAP-Anfragen ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _url(path: str) -> str:
        return Path(path).as_uri()

    def _do_setBreakpoints(self, a, cb):
        path = a["source"]["path"]
        for bid in self.bp_ids.pop(path, []):
            self.cdp("Debugger.removeBreakpoint", {"breakpointId": bid})
        wanted = a.get("breakpoints", [])
        results: list = [None] * len(wanted)
        if not wanted:
            return self._reply(cb, True, {"breakpoints": []})
        left = [len(wanted)]
        ids = self.bp_ids.setdefault(path, [])

        def done(i, bp, res, err):
            ok = bool(res and res.get("locations"))
            if res and res.get("breakpointId"):
                ids.append(res["breakpointId"])
            results[i] = {"verified": ok, "line": bp["line"]}
            left[0] -= 1
            if left[0] == 0 and cb:
                cb(True, {"breakpoints": results}, "")
        for i, bp in enumerate(wanted):
            params = {"lineNumber": bp["line"] - 1, "url": self._url(path)}
            if bp.get("condition"):
                params["condition"] = bp["condition"]
            self.cdp("Debugger.setBreakpointByUrl", params, cb=lambda r, e, i=i, bp=bp: done(i, bp, r, e))

    def _do_setExceptionBreakpoints(self, a, cb):
        self.cdp("Debugger.setPauseOnExceptions", {"state": "uncaught"})
        self._reply(cb, True)

    def _do_configurationDone(self, a, cb):
        self._configured = True
        if self._waiting_start:
            self._waiting_start = False
            self.cdp("Debugger.resume")
        self._reply(cb, True)

    def _frame_path(self, f: dict) -> str | None:
        url = f.get("url") or self.scripts.get(f.get("location", {}).get("scriptId", ""), "")
        if url.startswith("file://"):
            return unquote(urlparse(url).path)
        return None

    def _do_stackTrace(self, a, cb):
        """Interne Node-Frames (node:…) werden ausgeblendet; die äußerste Benutzer-Funktion ohne Namen heißt <module>."""
        user = [i for i, f in enumerate(self.frames) if self._frame_path(f)]
        outer = user[-1] if user else -1
        frames = []
        for i, f in enumerate(self.frames):
            path = self._frame_path(f)
            if not path and user:
                continue
            loc = f["location"]
            name = f.get("functionName") or ("<module>" if i == outer else "(anonymous)")
            frames.append({"id": i, "name": name, "line": loc["lineNumber"] + 1, "column": loc.get("columnNumber", 0) + 1,
                           **({"source": {"path": path, "name": Path(path).name}} if path else {})})
        self._reply(cb, True, {"stackFrames": frames, "totalFrames": len(frames)})

    def _ref(self, object_id: str) -> int:
        r = self._next_ref
        self._next_ref += 1
        self.refs[r] = object_id
        return r

    def _do_scopes(self, a, cb):
        i = a.get("frameId", 0)
        scopes = []
        if 0 <= i < len(self.frames):
            for s in self.frames[i].get("scopeChain", []):
                if s["type"] == "global":
                    continue
                oid = (s.get("object") or {}).get("objectId")
                if oid:
                    scopes.append({"name": SCOPE_NAMES.get(s["type"], s["type"].title()), "variablesReference": self._ref(oid), "expensive": False})
        self._reply(cb, True, {"scopes": scopes})

    def _fmt(self, ro: dict):
        t, st = ro.get("type", ""), ro.get("subtype", "")
        if t == "string":
            val = "'" + str(ro.get("value", "")) + "'"
        elif t == "boolean":
            val = "true" if ro.get("value") else "false"
        elif t in ("number", "bigint"):
            val = ro.get("unserializableValue") or (str(ro["value"]) if ro.get("value") is not None else ro.get("description", ""))
        elif t == "undefined":
            val = "undefined"
        elif st == "null":
            val = "null"
        else:
            val = (ro.get("description") or ro.get("className") or t).split("\n")[0][:200]
        ref = self._ref(ro["objectId"]) if ro.get("objectId") and t in ("object", "function") and st != "null" else 0
        typ = ro.get("className") or st or t
        return val, typ, ref

    def _do_variables(self, a, cb):
        oid = self.refs.get(a.get("variablesReference"))
        if not oid:
            return self._reply(cb, True, {"variables": []})

        def got(res, err):
            out = []
            for p in (res or {}).get("result", []):
                if p["name"] == "__proto__" or "value" not in p:
                    continue
                v, t, r = self._fmt(p["value"])
                out.append({"name": p["name"], "value": v, "type": t, "variablesReference": r})
            cb(True, {"variables": out}, "")
        self.cdp("Runtime.getProperties", {"objectId": oid, "ownProperties": True}, cb=got)

    def _do_evaluate(self, a, cb):
        expr, fid = a.get("expression", ""), a.get("frameId")

        def got(res, err):
            if err or not res:
                return cb(False, {}, (err or {}).get("message", "Fehler"), )
            if res.get("exceptionDetails"):
                d = res["exceptionDetails"].get("exception", {}).get("description") or res["exceptionDetails"].get("text", "Fehler")
                return cb(False, {}, d.split("\n")[0])
            v, t, r = self._fmt(res["result"])
            cb(True, {"result": v, "type": t, "variablesReference": r}, "")
        if fid is not None and 0 <= fid < len(self.frames):
            self.cdp("Debugger.evaluateOnCallFrame", {"callFrameId": self.frames[fid]["callFrameId"], "expression": expr}, cb=got)
        else:
            self.cdp("Runtime.evaluate", {"expression": expr}, cb=got)

    def _step(self, method: str, name: str, cb):
        self._last_cmd = name
        self.cdp(method)
        self._reply(cb, True)

    def _do_continue(self, a, cb): self._step("Debugger.resume", "continue", cb)
    def _do_next(self, a, cb): self._step("Debugger.stepOver", "next", cb)
    def _do_stepIn(self, a, cb): self._step("Debugger.stepInto", "stepIn", cb)
    def _do_stepOut(self, a, cb): self._step("Debugger.stepOut", "stepOut", cb)
    def _do_pause(self, a, cb): self._step("Debugger.pause", "pause", cb)

    def _do_disconnect(self, a, cb):
        self._reply(cb, True)
        self.stop()
        self.event.emit("terminated", {})
