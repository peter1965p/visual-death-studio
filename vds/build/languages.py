"""Sprachtabelle: Build-/Run-Kommandos und Language Server je Sprache.
{file} = Quelldatei, {out} = Binärdatei im Build-Verzeichnis."""
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Lang:
    id: str
    name: str
    exts: tuple
    run: list
    build: list | None = None
    lsp: list | None = None
    lsp_id: str = ""        # languageId für LSP, falls abweichend
    comment: str = "//"
    snippets: dict = field(default_factory=dict)


LANGS = [
    Lang("python", "Python", (".py", ".pyw"), ["python3", "-u", "{file}"], lsp=["pylsp"], comment="#",
         snippets={"def": "def name(args):\n    pass\n", "class": "class Name:\n    def __init__(self):\n        pass\n",
                   "main-Guard": 'if __name__ == "__main__":\n    main()\n', "for": "for item in items:\n    pass\n"}),
    Lang("javascript", "Node.js", (".js", ".mjs", ".cjs"), ["node", "{file}"], lsp=["typescript-language-server", "--stdio"],
         snippets={"function": "function name(args) {\n}\n", "console.log": "console.log();\n"}),
    Lang("typescript", "TypeScript", (".ts",), ["node", "--experimental-strip-types", "{file}"],
         lsp=["typescript-language-server", "--stdio"]),
    Lang("c", "C", (".c",), ["{out}"], build=["gcc", "-g", "-Wall", "{file}", "-o", "{out}"], lsp=["clangd"],
         snippets={"main": "#include <stdio.h>\n\nint main(void) {\n    return 0;\n}\n", "for": "for (int i = 0; i < n; i++) {\n}\n"}),
    Lang("cpp", "C++", (".cpp", ".cc", ".cxx", ".hpp", ".h"), ["{out}"],
         build=["g++", "-g", "-Wall", "-std=c++20", "{file}", "-o", "{out}"], lsp=["clangd"],
         snippets={"main": "#include <iostream>\n\nint main() {\n    return 0;\n}\n", "class": "class Name {\npublic:\n};\n"}),
    Lang("csharp", "C#", (".cs",), ["dotnet", "run", "{file}"], lsp=["csharp-ls"], lsp_id="csharp",
         snippets={"Main": "Console.WriteLine();\n", "class": "public class Name\n{\n}\n"}),
    Lang("rust", "Rust", (".rs",), ["{out}"], build=["rustc", "-g", "{file}", "-o", "{out}"], lsp=["rust-analyzer"],
         snippets={"fn main": "fn main() {\n}\n"}),
    Lang("go", "Go", (".go",), ["go", "run", "{file}"], lsp=["gopls"],
         snippets={"func main": "package main\n\nfunc main() {\n}\n"}),
    Lang("java", "Java", (".java",), ["java", "{file}"], lsp=["jdtls"]),
    Lang("shell", "Bash", (".sh", ".bash"), ["bash", "{file}"], lsp=["bash-language-server", "start"], lsp_id="shellscript", comment="#"),
]
BY_ID = {l.id: l for l in LANGS}


def lang_for(path: str | Path) -> Lang | None:
    ext = Path(path).suffix.lower()
    return next((l for l in LANGS if ext in l.exts), None)


def available(cmd: list | None) -> bool:
    return bool(cmd) and (cmd[0].startswith("{") or shutil.which(cmd[0]) is not None)


# --- Compiler-/Interpreter-Meldungen -> Fehlerliste ---------------------------------
_GCC = re.compile(r"^(?P<file>[^\s:][^:]*):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>fatal error|error|warning|note)?:?\s*(?P<msg>.+)$")
_RUST = re.compile(r"^\s*--> (?P<file>.+):(?P<line>\d+):(?P<col>\d+)$")
_PY = re.compile(r'^\s*File "(?P<file>.+)", line (?P<line>\d+)')


def parse_problems(text: str):
    """Liefert [(severity, message, file, line, col)] aus gcc/g++/go/node/rustc/python-Ausgaben."""
    out, pending, lines = [], None, text.splitlines()
    py_loc = None
    for i, ln in enumerate(lines):
        m = _PY.match(ln)
        if m:
            py_loc = (m["file"], int(m["line"]))
            continue
        m = _RUST.match(ln)
        if m and pending:
            out.append((pending[0], pending[1], m["file"], int(m["line"]), int(m["col"])))
            pending = None
            continue
        r = re.match(r"^(error|warning)(\[\w+\])?: (.+)$", ln)
        if r:
            pending = ("error" if r[1] == "error" else "warning", r[3])
            continue
        m = _GCC.match(ln)
        if m and m["sev"] and "/" not in (m["file"] or "")[:0]:
            sev = {"warning": "warning", "note": "info"}.get(m["sev"], "error")
            out.append((sev, m["msg"], m["file"], int(m["line"]), int(m["col"] or 1)))
    if py_loc:
        msg = next((l for l in reversed(lines) if l.strip() and not l.startswith(" ")), "Fehler")
        out.append(("error", msg, py_loc[0], py_loc[1], 1))
    return out
