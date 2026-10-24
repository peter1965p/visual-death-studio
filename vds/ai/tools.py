"""Werkzeuge für den Claude-Agenten im API-Modus: Dateien lesen/schreiben/ändern/suchen, optional Shell-Befehle – alles nur im Projektordner."""
import fnmatch
import re
import subprocess
import threading
from pathlib import Path

SKIP_DIRS = {".git", ".vds", ".venv", "venv", "node_modules", "__pycache__", "target", ".idea", ".mypy_cache", ".pytest_cache"}
MAX_READ, MAX_LIST, MAX_HITS, MAX_OUT, CMD_TIMEOUT = 200_000, 300, 100, 20_000, 120

DEFINITIONS = [
    {"name": "list_files", "description": "Listet Dateien im Projekt (relative Pfade, höchstens 300). Optional mit Glob-Muster wie '**/*.py'.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Glob-Muster, Standard **/*"}}}},
    {"name": "read_file", "description": "Liest eine Textdatei des Projekts. Mit start_line/end_line (1-basiert) nur einen Ausschnitt.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "Schreibt eine Datei komplett (legt sie und fehlende Ordner an, überschreibt vorhandene).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Ersetzt in einer Datei genau einen Textabschnitt (old_string muss eindeutig vorkommen, sonst replace_all=true).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
                                                       "replace_all": {"type": "boolean"}}, "required": ["path", "old_string", "new_string"]}},
    {"name": "search_files", "description": "Durchsucht Projektdateien mit einem regulären Ausdruck; liefert 'pfad:zeile: text' (höchstens 100 Treffer).",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "glob": {"type": "string"}}, "required": ["pattern"]}},
]
RUN_COMMAND = {"name": "run_command", "description": "Führt einen Shell-Befehl im Projektordner aus (Zeitlimit 120 s), z. B. Tests oder pip install.",
               "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}


class ToolError(Exception):
    pass


class ToolBox:
    def __init__(self, root: Path, allow_command: bool = False):
        self.root = Path(root).resolve()
        self.allow_command = allow_command

    def definitions(self, eager: bool = False) -> list:
        defs = [dict(d) for d in DEFINITIONS + ([RUN_COMMAND] if self.allow_command else [])]
        if eager:
            for d in defs:
                d["eager_input_streaming"] = True
        return defs

    # --- Pfade ---------------------------------------------------------------------------------
    def resolve(self, path, write: bool = False) -> Path:
        if not isinstance(path, str) or not path.strip():
            raise ToolError("Pfad fehlt.")
        p = (self.root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolError(f"'{path}' liegt außerhalb des Projektordners.")
        rel = p.relative_to(self.root).parts
        if write and rel and rel[0] in (".git", ".vds"):
            raise ToolError(f"In '{rel[0]}' wird nicht geschrieben.")
        return p

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def _files(self, glob: str = "**/*"):
        for p in sorted(self.root.glob(glob)):
            if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
                yield p

    # --- Ausführung ----------------------------------------------------------------------------
    def label(self, name: str, inp: dict) -> str:
        if name == "run_command":
            return "run_command: " + str(inp.get("command", ""))[:80]
        return f"{name} {inp.get('path') or inp.get('pattern') or ''}".strip()

    def execute(self, name: str, inp, cancel: threading.Event | None = None) -> tuple:
        """-> (Ergebnistext, is_error). Fehlerhafte oder unvollständige Eingaben werden dem Modell als Fehler zurückgemeldet."""
        try:
            if not isinstance(inp, dict):
                raise ToolError("Eingabe ist kein Objekt.")
            fn = getattr(self, "_" + name, None) if name in {d["name"] for d in DEFINITIONS} | ({"run_command"} if self.allow_command else set()) else None
            if fn is None:
                raise ToolError(f"Unbekanntes oder nicht erlaubtes Werkzeug '{name}'.")
            return fn(inp, cancel), False
        except ToolError as e:
            return str(e), True
        except OSError as e:
            return f"Dateifehler: {e.strerror or e}", True

    @staticmethod
    def _need(inp, *keys):
        for k in keys:
            if not isinstance(inp.get(k), str):
                raise ToolError(f"Pflichtfeld '{k}' fehlt oder ist kein Text (Eingabe evtl. abgeschnitten).")

    def _list_files(self, inp, cancel):
        files = [self.rel(p) for p in self._files(str(inp.get("pattern") or "**/*"))]
        more = f"\n… und {len(files) - MAX_LIST} weitere" if len(files) > MAX_LIST else ""
        return "\n".join(files[:MAX_LIST]) + more if files else "(keine Dateien)"

    def _read_file(self, inp, cancel):
        self._need(inp, "path")
        p = self.resolve(inp["path"])
        if not p.is_file():
            raise ToolError(f"'{inp['path']}' ist keine Datei.")
        text = p.read_text(encoding="utf-8", errors="replace")
        a, b = inp.get("start_line"), inp.get("end_line")
        if isinstance(a, int) or isinstance(b, int):
            lines = text.splitlines()
            a = max(1, a) if isinstance(a, int) else 1
            text = "\n".join(lines[a - 1:b if isinstance(b, int) else None])
        return text[:MAX_READ] + ("\n… (gekürzt)" if len(text) > MAX_READ else "")

    def _write_file(self, inp, cancel):
        self._need(inp, "path", "content")
        p = self.resolve(inp["path"], write=True)
        if p.is_dir():
            raise ToolError(f"'{inp['path']}' ist ein Ordner.")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp["content"], encoding="utf-8")
        return f"{self.rel(p)} geschrieben ({len(inp['content'])} Zeichen)."

    def _edit_file(self, inp, cancel):
        self._need(inp, "path", "old_string", "new_string")
        p = self.resolve(inp["path"], write=True)
        if not p.is_file():
            raise ToolError(f"'{inp['path']}' existiert nicht.")
        text, old = p.read_text(encoding="utf-8"), inp["old_string"]
        n = text.count(old) if old else 0
        if n == 0:
            raise ToolError("old_string kommt in der Datei nicht vor.")
        if n > 1 and not inp.get("replace_all"):
            raise ToolError(f"old_string kommt {n}-mal vor – mehr Kontext angeben oder replace_all=true setzen.")
        p.write_text(text.replace(old, inp["new_string"]) if inp.get("replace_all") else text.replace(old, inp["new_string"], 1), encoding="utf-8")
        return f"{self.rel(p)}: {n if inp.get('replace_all') else 1} Ersetzung(en)."

    def _search_files(self, inp, cancel):
        self._need(inp, "pattern")
        try:
            rx = re.compile(inp["pattern"])
        except re.error as e:
            raise ToolError(f"Ungültiger regulärer Ausdruck: {e}")
        glob = str(inp.get("glob") or "")
        hits = []
        for p in self._files():
            if glob and not fnmatch.fnmatch(p.name, glob) and not fnmatch.fnmatch(self.rel(p), glob):
                continue
            try:
                for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{self.rel(p)}:{n}: {line.strip()[:200]}")
                        if len(hits) >= MAX_HITS:
                            return "\n".join(hits) + "\n… (weitere Treffer abgeschnitten)"
            except (UnicodeDecodeError, OSError):
                continue
        return "\n".join(hits) or "(keine Treffer)"

    def _run_command(self, inp, cancel):
        self._need(inp, "command")
        proc = subprocess.Popen(["bash", "-c", inp["command"]], cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        timer = threading.Timer(CMD_TIMEOUT, proc.kill)
        timer.start()
        try:
            while True:
                try:
                    out, _ = proc.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel and cancel.is_set():
                        proc.kill(); out, _ = proc.communicate()
                        break
        finally:
            timer.cancel()
        out = out if len(out) <= MAX_OUT else out[:MAX_OUT // 2] + "\n… (gekürzt) …\n" + out[-MAX_OUT // 2:]
        return f"{out}\n[Exit-Code {proc.returncode}]"
