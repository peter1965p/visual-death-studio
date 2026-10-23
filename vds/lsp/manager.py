"""LSP-Verwaltung: ein Server je Sprache, Dokument-Synchronisation, Vorschläge (mit Wort-Index als Rückfall), Hover, Signatur, Definition."""
import builtins
import json
from collections import Counter
import keyword
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QTextStream, QTimer, Signal
from PySide6.QtGui import QTextDocument

from ..build.languages import lang_for
from ..build.runner import Runner
from ..branding import SETTINGS_APP, SETTINGS_ORG
from .client import LspClient
from .ranking import KIND_NAME

LSP_ID = {"shell": "shellscript"}
SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "info"}
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

KEYWORDS = {
    "python": keyword.kwlist,
    "c": "auto break case char const continue default do double else enum extern float for goto if inline int long register return short signed sizeof static struct switch typedef union unsigned void volatile while".split(),
    "cpp": "auto break case catch char class const constexpr continue default delete do double else enum explicit extern false final float for friend goto if inline int long namespace new noexcept nullptr operator override private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while bool decltype".split(),
    "javascript": "async await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null of return super switch this throw true try typeof undefined var void while with yield".split(),
    "typescript": "abstract any as async await boolean break case catch class const continue declare default delete do else enum export extends false finally for from function if implements import in instanceof interface let namespace new null number of private protected public readonly return static string super switch this throw true try type typeof undefined var void while yield".split(),
    "rust": "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while".split(),
    "go": "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var".split(),
    "csharp": "abstract as async await base bool break byte case catch char class const continue decimal default delegate do double else enum event false finally float for foreach if in int interface internal is lock long namespace new null object out override private protected public readonly record ref return sealed short static string struct switch this throw true try typeof uint ulong using var virtual void while".split(),
    "java": "abstract boolean break byte case catch char class const continue default do double else enum extends false final finally float for if implements import instanceof int interface long new null package private protected public return short static super switch this throw throws true try void volatile while".split(),
    "shell": "if then else elif fi for while do done case esac function in echo export local return exit read set unset source".split(),
}


def md_to_html(md: str) -> str:
    """Markdown -> HTML-Fragment (nur der <body>-Inhalt, ohne den CSS-Block von QTextDocument)."""
    d = QTextDocument()
    d.setMarkdown(md)
    m = re.search(r"<body[^>]*>(.*)</body>", d.toHtml(), re.S)
    return m.group(1).strip() if m else md


class _Server:
    def __init__(self, lang_id):
        self.lang = lang_id
        self.client: LspClient | None = None
        self.state = "idle"            # idle | starting | ready | failed
        self.queue: list = []          # Aufgaben, die auf 'ready' warten
        self.opened: set = set()
        self.caps: dict = {}


class _Doc:
    def __init__(self, doc):
        self.doc, self.version, self.dirty = doc, 1, False
        self.timer = QTimer(singleShot=True, interval=160)


class LspManager(QObject):
    diagnostics = Signal(str, list)        # Pfad, [(Schwere, Text, Zeile(1), Spalte(1))]
    editRequested = Signal(dict, str)      # Server will Änderungen anwenden: {Pfad: [Edit]}, Beschriftung
    statusChanged = Signal(str, str)       # Sprach-ID, Statustext

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.servers: dict[str, _Server] = {}
        self.docs: dict[str, _Doc] = {}
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.mru: dict[str, dict] = {}

    def set_root(self, root: Path):
        self.shutdown()
        self.root = Path(root)

    # --- Server ----------------------------------------------------------------------------------------------
    def _command(self, lang) -> list | None:
        if not lang or not lang.lsp:
            return None
        cmd = list(lang.lsp)
        if lang.id == "python":
            local = Path(sys.executable).parent / "pylsp"
            if local.exists():
                cmd[0] = str(local)
        return cmd if (shutil.which(cmd[0]) or Path(cmd[0]).exists()) else None

    def _server(self, lang) -> _Server | None:
        sv = self.servers.get(lang.id)
        if sv:
            return sv if sv.state != "failed" else None
        cmd = self._command(lang)
        sv = _Server(lang.id)
        self.servers[lang.id] = sv
        if not cmd:
            sv.state = "failed"
            self.statusChanged.emit(lang.id, f"kein Server ({lang.lsp[0] if lang.lsp else 'keiner'})")
            return None
        sv.state = "starting"
        self.statusChanged.emit(lang.id, "startet …")
        c = LspClient(cmd, str(self.root), self)
        sv.client = c
        c.notification.connect(lambda m, p, sv=sv: self._notification(sv, m, p))
        c.closed.connect(lambda _code, sv=sv, lang=lang: self._closed(sv, lang))
        c.serverRequest.connect(lambda m, p, i, sv=sv: self._server_request(sv, m, p, i))
        c.start()
        uri = self.root.as_uri()
        caps = {"textDocument": {"synchronization": {"didSave": True},
                                 "completion": {"completionItem": {"snippetSupport": False, "deprecatedSupport": True, "documentationFormat": ["markdown", "plaintext"]}},
                                 "hover": {"contentFormat": ["markdown", "plaintext"]},
                                 "signatureHelp": {"signatureInformation": {"documentationFormat": ["markdown", "plaintext"], "parameterInformation": {"labelOffsetSupport": True}}},
                                 "definition": {"linkSupport": False}, "publishDiagnostics": {}},
                "workspace": {"configuration": True}}
        c.request("initialize", {"processId": None, "rootUri": uri, "rootPath": str(self.root), "workspaceFolders": [{"uri": uri, "name": self.root.name}],
                                 "capabilities": caps}, lambda res, err, sv=sv, lang=lang: self._initialized(sv, lang, res, err))
        return sv

    def _initialized(self, sv, lang, res, err):
        if err or not sv.client:
            sv.state = "failed"
            return self.statusChanged.emit(lang.id, "Start fehlgeschlagen")
        sv.caps = (res or {}).get("capabilities", {})
        sv.client.notify("initialized", {})
        if lang.id == "python":
            env = Runner.python_for(self.root / "x.py")
            sv.client.notify("workspace/didChangeConfiguration", {"settings": {"pylsp": {"plugins": {
                "jedi": {"environment": env}, "pycodestyle": {"enabled": False}, "mccabe": {"enabled": False},
                "pydocstyle": {"enabled": False}, "pyflakes": {"enabled": True}, "jedi_completion": {"include_params": False}}}}})
        sv.state = "ready"
        self.statusChanged.emit(lang.id, "bereit")
        for job in sv.queue:
            job()
        sv.queue.clear()

    def _closed(self, sv, lang):
        sv.state = "failed"
        self.statusChanged.emit(lang.id, "beendet")

    def shutdown(self):
        for t in self.docs.values():
            t.timer.stop()
        for sv in self.servers.values():
            if sv.client:
                sv.client.stop()
        self.servers.clear(); self.docs.clear()

    def when_ready(self, sv, job):
        job() if sv.state == "ready" else sv.queue.append(job)

    # --- Dokumente ---------------------------------------------------------------------------------------------
    def attach(self, doc):
        lang = lang_for(doc.path)
        if doc.kind != "code" or not lang:
            return
        key = str(doc.path)
        if key in self.docs:
            return
        st = _Doc(doc)
        self.docs[key] = st
        st.timer.timeout.connect(lambda k=key: self._flush(k))
        doc.view.document().contentsChanged.connect(lambda k=key: self._mark(k))
        sv = self._server(lang)
        if sv:
            self.when_ready(sv, lambda: self._open(sv, lang, st))

    def _open(self, sv, lang, st):
        if not sv.client or str(st.doc.path) in sv.opened:
            return
        sv.opened.add(str(st.doc.path))
        sv.client.notify("textDocument/didOpen", {"textDocument": {"uri": st.doc.path.as_uri(), "languageId": LSP_ID.get(lang.id, lang.id),
                                                                    "version": st.version, "text": st.doc.view.toPlainText()}})

    def _mark(self, key):
        st = self.docs.get(key)
        if st:
            st.dirty = True
            st.timer.start()

    def _flush(self, key):
        """Geänderten Text sofort an den Server schicken (vor Anfragen und nach dem Tipp-Timer)."""
        st = self.docs.get(key)
        if not st or not st.dirty:
            return
        lang = lang_for(st.doc.path)
        sv = self.servers.get(lang.id) if lang else None
        if sv and sv.state == "ready" and key in sv.opened:
            st.version += 1; st.dirty = False
            sv.client.notify("textDocument/didChange", {"textDocument": {"uri": st.doc.path.as_uri(), "version": st.version},
                                                         "contentChanges": [{"text": st.doc.view.toPlainText()}]})

    def did_save(self, path: Path):
        st = self.docs.get(str(path))
        lang = lang_for(path)
        sv = self.servers.get(lang.id) if lang else None
        if st and sv and sv.state == "ready":
            self._flush(str(path))
            sv.client.notify("textDocument/didSave", {"textDocument": {"uri": path.as_uri()}})

    def detach(self, path: Path):
        key = str(path)
        st = self.docs.pop(key, None)
        lang = lang_for(path)
        sv = self.servers.get(lang.id) if lang else None
        if st:
            st.timer.stop()
        if sv and sv.state == "ready" and key in sv.opened:
            sv.opened.discard(key)
            sv.client.notify("textDocument/didClose", {"textDocument": {"uri": path.as_uri()}})
        self.diagnostics.emit(key, [])

    def _notification(self, sv, method, params):
        if method == "textDocument/publishDiagnostics":
            try:
                path = str(Path(params["uri"].replace("file://", "")).resolve()) if params["uri"].startswith("file://") else params["uri"]
            except OSError:
                return
            from urllib.parse import unquote
            path = unquote(path)
            items = [(SEVERITY.get(d.get("severity", 1), "error"), d.get("message", ""), d["range"]["start"]["line"] + 1,
                      d["range"]["start"]["character"] + 1) for d in params.get("diagnostics", [])]
            self.diagnostics.emit(path, items)

    # --- Anfragen ---------------------------------------------------------------------------------------------------
    def _ready_server(self, path: Path):
        lang = lang_for(path)
        sv = self.servers.get(lang.id) if lang else None
        return (sv, lang) if sv and sv.state == "ready" and str(path) in sv.opened else (None, lang)

    def word_index(self, lang_id: str, exclude_at: tuple | None = None) -> set:
        """Alle Bezeichner aus den offenen Dateien dieser Sprache (Rückfall und Kontext-Bonus).
        exclude_at = (Pfad, Zeile, Spalte): das Wort, das man gerade tippt, schlägt sich nicht selbst vor."""
        counts: Counter = Counter()
        for t in self.docs.values():
            lg = lang_for(t.doc.path)
            if lg and lg.id == lang_id:
                counts.update(WORD.findall(t.doc.view.toPlainText()[:300_000]))
        if exclude_at:
            path, line, col = exclude_at
            t = self.docs.get(str(path))
            if t:
                lines = t.doc.view.toPlainText().split("\n")
                if line < len(lines):
                    text = lines[line]
                    a = col
                    while a > 0 and (text[a - 1].isalnum() or text[a - 1] == "_"):
                        a -= 1
                    b = col
                    while b < len(text) and (text[b].isalnum() or text[b] == "_"):
                        b += 1
                    cur = text[a:b]
                    if cur in counts:
                        counts[cur] -= 1
        return {w for w, n in counts.items() if n > 0}

    def local_words(self, path: Path) -> set:
        t = self.docs.get(str(path))
        return set(WORD.findall(t.doc.view.toPlainText()[:300_000])) if t else set()

    def _fallback(self, lang, with_builtins: bool, at: tuple | None = None) -> list:
        items = [{"label": w, "kind": 14, "detail": "Schlüsselwort"} for w in KEYWORDS.get(lang.id, [])]
        if with_builtins and lang.id == "python":
            items += [{"label": n, "kind": 3, "detail": "eingebaut"} for n in dir(builtins) if not n.startswith("_")]
        items += [{"label": w, "kind": 6, "detail": "aus offenen Dateien"} for w in self.word_index(lang.id, at)]
        return items

    def complete(self, path: Path, line: int, col: int, trigger: str | None, cb):
        """cb(items) – LSP-Vorschläge plus Wörter aus offenen Dateien; ranken übernimmt der Aufrufer."""
        lang = lang_for(path)
        if not lang:
            return cb([])
        sv, _ = self._ready_server(path)
        have_lsp = sv is not None
        local = self._fallback(lang, with_builtins=not have_lsp, at=(path, line, col))
        if not have_lsp:
            return cb(local)
        self._flush(str(path))
        done = {"v": False}

        def finish(items):
            if done["v"]:
                return
            done["v"] = True
            seen = {i["name"] for i in items}
            cb(items + [i for i in local if i["label"] not in seen])

        def got(res, err):
            if err or res is None:
                return finish([])
            raw = res.get("items", []) if isinstance(res, dict) else res
            finish([self._norm(i) for i in raw])
        ctx = {"triggerKind": 2, "triggerCharacter": trigger} if trigger else {"triggerKind": 1}
        sv.client.request("textDocument/completion", {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": col}, "context": ctx}, got)
        QTimer.singleShot(1500, lambda: finish([]))           # Server zu langsam: mit lokalen Wörtern weiterarbeiten

    @staticmethod
    def _norm(i: dict) -> dict:
        doc = i.get("documentation")
        doc = doc.get("value", "") if isinstance(doc, dict) else (doc or "")
        te = i.get("textEdit")
        if isinstance(te, dict) and "newText" not in te:           # InsertReplaceEdit
            te = {"range": te.get("insert") or te.get("replace"), "newText": te.get("newText", "")}
        label = i.get("label", "")
        name = i.get("filterText") or re.split(r"[\s(\[<:]", label.strip(), maxsplit=1)[0] or label
        return {"label": label, "name": name, "kind": i.get("kind"), "detail": i.get("detail") or (i.get("labelDetails") or {}).get("description", ""),
                "documentation": doc, "insertText": i.get("insertText") or name, "textEdit": te, "filterText": i.get("filterText"),
                "sortText": i.get("sortText"), "deprecated": bool(i.get("deprecated")) or 1 in (i.get("tags") or []), "snippet": i.get("insertTextFormat") == 2}

    def hover(self, path: Path, line: int, col: int, cb):
        sv, _ = self._ready_server(path)
        if not sv:
            return cb(None)
        self._flush(str(path))

        def got(res, err):
            c = (res or {}).get("contents") if not err else None
            parts = c if isinstance(c, list) else [c] if c else []
            text = "\n\n".join(p.get("value", "") if isinstance(p, dict) else str(p) for p in parts).strip()
            cb(md_to_html(text) if text else None)
        sv.client.request("textDocument/hover", {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": col}}, got)

    def signature(self, path: Path, line: int, col: int, cb):
        sv, _ = self._ready_server(path)
        if not sv:
            return cb(None)
        self._flush(str(path))

        def got(res, err):
            if err or not res or not res.get("signatures"):
                return cb(None)
            sig = res["signatures"][min(res.get("activeSignature") or 0, len(res["signatures"]) - 1)]
            label, params = sig.get("label", ""), sig.get("parameters") or []
            ai = res.get("activeParameter", sig.get("activeParameter")) or 0
            span = None
            if 0 <= ai < len(params):
                pl = params[ai].get("label")
                if isinstance(pl, list):
                    span = tuple(pl)
                elif isinstance(pl, str) and pl in label:
                    s = label.find(pl); span = (s, s + len(pl))
            doc = sig.get("documentation")
            doc = doc.get("value", "") if isinstance(doc, dict) else (doc or "")
            cb({"label": label, "active": span, "doc": doc.strip().split("\n\n")[0][:200]})
        sv.client.request("textDocument/signatureHelp", {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": col}}, got)

    def definition(self, path: Path, line: int, col: int, cb):
        sv, _ = self._ready_server(path)
        if not sv:
            return cb([])
        self._flush(str(path))

        def got(res, err):
            from urllib.parse import unquote
            res = res if isinstance(res, list) else [res] if res else []
            out = []
            for loc in res:
                uri = loc.get("uri") or loc.get("targetUri")
                rng = loc.get("range") or loc.get("targetSelectionRange")
                if uri and rng and uri.startswith("file://"):
                    out.append((unquote(uri[7:]), rng["start"]["line"] + 1, rng["start"]["character"] + 1))
            cb(out)
        sv.client.request("textDocument/definition", {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": col}}, got)

    # --- Zuletzt benutzt --------------------------------------------------------------------------------------------
    def mru_for(self, lang_id: str) -> dict:
        if lang_id not in self.mru:
            try:
                self.mru[lang_id] = json.loads(self.settings.value(f"intel/mru/{lang_id}", "{}"))
            except ValueError:
                self.mru[lang_id] = {}
        return self.mru[lang_id]

    def record_choice(self, lang_id: str, label: str):
        m = self.mru_for(lang_id)
        for k in list(m):
            m[k] = max(0, m[k] - 0.05)                 # langsam vergessen
        m[label] = min(5, m.get(label, 0) + 1)
        m = dict(sorted(((k, v) for k, v in m.items() if v > 0), key=lambda kv: -kv[1])[:300])
        self.mru[lang_id] = m
        self.settings.setValue(f"intel/mru/{lang_id}", json.dumps(m))


    # --- Refactoring ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _uri_path(uri: str) -> str:
        from urllib.parse import unquote
        return unquote(uri[7:]) if uri.startswith("file://") else uri

    def _edits_from(self, we: dict | None) -> dict:
        """WorkspaceEdit -> {Pfad: [(Zeile0, Spalte0, Zeile0, Spalte0, Text)]} (nur Textänderungen)."""
        out: dict = {}
        if not we:
            return out
        def add(uri, edits):
            for e in edits:
                r = e["range"]
                out.setdefault(self._uri_path(uri), []).append((r["start"]["line"], r["start"]["character"], r["end"]["line"], r["end"]["character"], e.get("newText", "")))
        for uri, edits in (we.get("changes") or {}).items():
            add(uri, edits)
        for dc in we.get("documentChanges") or []:
            if "edits" in dc:
                add(dc["textDocument"]["uri"], dc["edits"])
        return out

    def _server_request(self, sv, method, params, req_id):
        if method == "workspace/applyEdit":
            edits = self._edits_from((params or {}).get("edit"))
            self.editRequested.emit(edits, (params or {}).get("label", "Refactoring"))
            sv.client.reply(req_id, {"applied": bool(edits)})

    def supports(self, path: Path, feature: str) -> bool:
        """feature: rename | references | formatting | codeAction"""
        lang = lang_for(path)
        sv = self.servers.get(lang.id) if lang else None
        key = {"rename": "renameProvider", "references": "referencesProvider", "formatting": "documentFormattingProvider", "codeAction": "codeActionProvider"}[feature]
        return bool(sv and sv.state == "ready" and sv.caps.get(key))

    def rename(self, path: Path, line: int, col: int, new_name: str, cb):
        sv, _ = self._ready_server(path)
        if not sv:
            return cb(None, "Kein Language Server aktiv")
        self._flush(str(path))
        sv.client.request("textDocument/rename", {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": col}, "newName": new_name},
                          lambda res, err: cb(None, (err or {}).get("message", "Umbenennen nicht möglich")) if err or not res else cb(self._edits_from(res), ""))

    def references(self, path: Path, line: int, col: int, cb):
        sv, _ = self._ready_server(path)
        if not sv:
            return cb([])
        self._flush(str(path))

        def got(res, err):
            out = []
            for loc in (res or []) if not err else []:
                p = self._uri_path(loc["uri"])
                ln = loc["range"]["start"]["line"]
                try:
                    text = Path(p).read_text(encoding="utf-8", errors="replace").splitlines()[ln].strip()
                except (OSError, IndexError):
                    text = ""
                out.append((p, ln + 1, loc["range"]["start"]["character"] + 1, text))
            cb(sorted(out))
        sv.client.request("textDocument/references", {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": col},
                                                       "context": {"includeDeclaration": True}}, got)

    def format_document(self, path: Path, cb):
        sv, _ = self._ready_server(path)
        if not sv:
            return cb(None, "Kein Language Server aktiv")
        self._flush(str(path))
        sv.client.request("textDocument/formatting", {"textDocument": {"uri": path.as_uri()}, "options": {"tabSize": 4, "insertSpaces": True}},
                          lambda res, err: cb(None, (err or {}).get("message", "Formatieren nicht möglich")) if err or res is None
                          else cb(self._edits_from({"changes": {path.as_uri(): res}}), ""))

    def code_actions(self, path: Path, line: int, col: int, end_line: int, end_col: int, cb):
        """cb([{title, kind, edits|None, command|None}])"""
        sv, _ = self._ready_server(path)
        if not sv:
            return cb([])
        self._flush(str(path))
        rng = {"start": {"line": line, "character": col}, "end": {"line": end_line, "character": end_col}}

        def got(res, err):
            acts = []
            for a in (res or []) if not err else []:
                acts.append({"title": a.get("title", "?"), "kind": a.get("kind", ""), "edits": self._edits_from(a.get("edit")) if a.get("edit") else None,
                             "command": a.get("command") if isinstance(a.get("command"), dict) else (a if "command" in a and "arguments" in a else None)})
            cb(acts)
        sv.client.request("textDocument/codeAction", {"textDocument": {"uri": path.as_uri()}, "range": rng, "context": {"diagnostics": []}}, got)

    def execute_command(self, path: Path, command: dict, cb=None):
        sv, _ = self._ready_server(path)
        if sv:
            sv.client.request("workspace/executeCommand", {"command": command.get("command"), "arguments": command.get("arguments", [])}, lambda r, e: cb and cb(r, e))
