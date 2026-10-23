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
    Lang("python", "Python", (".py", ".pyw"), ["python3", "-u", "{file}"], lsp=["pylsp"], comment="#", snippets={
        "def – Funktion": "def name(args):\n    pass\n", "class – Klasse": "class Name:\n    def __init__(self):\n        pass\n",
        "dataclass": "from dataclasses import dataclass\n\n\n@dataclass\nclass Name:\n    feld: int = 0\n",
        "main-Guard": 'if __name__ == "__main__":\n    main()\n', "for-Schleife": "for item in items:\n    pass\n",
        "while-Schleife": "while bedingung:\n    pass\n", "try / except": "try:\n    pass\nexcept Exception as e:\n    print(e)\n",
        "with open": "with open(\"datei.txt\", encoding=\"utf-8\") as f:\n    text = f.read()\n",
        "List Comprehension": "[x for x in items if x]\n", "if / elif / else": "if a:\n    pass\nelif b:\n    pass\nelse:\n    pass\n",
        "argparse": "import argparse\n\nparser = argparse.ArgumentParser()\nparser.add_argument(\"name\")\nargs = parser.parse_args()\n",
        "async def": "import asyncio\n\n\nasync def main():\n    await asyncio.sleep(1)\n\n\nasyncio.run(main())\n",
        "logging": "import logging\n\nlogging.basicConfig(level=logging.INFO)\nlog = logging.getLogger(__name__)\n",
        "JSON lesen/schreiben": "import json\n\ndata = json.load(open(\"daten.json\", encoding=\"utf-8\"))\njson.dump(data, open(\"daten.json\", \"w\", encoding=\"utf-8\"), indent=2)\n",
        "unittest-Klasse": "import unittest\n\n\nclass MeinTest(unittest.TestCase):\n    def test_beispiel(self):\n        self.assertEqual(1 + 1, 2)\n",
        "pytest-Test": "def test_beispiel():\n    assert 1 + 1 == 2\n"}),
    Lang("javascript", "Node.js", (".js", ".mjs", ".cjs"), ["node", "{file}"], lsp=["typescript-language-server", "--stdio"], snippets={
        "function": "function name(args) {\n}\n", "Arrow-Funktion": "const name = (args) => {\n};\n", "class": "class Name {\n  constructor() {\n  }\n}\n",
        "console.log": "console.log();\n", "async / await": "async function name() {\n  const res = await fetch(url);\n  return res.json();\n}\n",
        "try / catch": "try {\n} catch (e) {\n  console.error(e);\n}\n", "for … of": "for (const item of items) {\n}\n",
        "map / filter": "const result = items.filter(x => x).map(x => x);\n", "Promise": "new Promise((resolve, reject) => {\n});\n",
        "Datei lesen": "const fs = require('node:fs');\nconst text = fs.readFileSync('datei.txt', 'utf8');\n",
        "node:test": "const test = require('node:test');\nconst assert = require('node:assert');\n\ntest('beispiel', () => {\n  assert.strictEqual(1 + 1, 2);\n});\n"}),
    Lang("typescript", "TypeScript", (".ts",), ["node", "--experimental-strip-types", "{file}"], lsp=["typescript-language-server", "--stdio"], snippets={
        "interface": "interface Name {\n  feld: string;\n}\n", "type-Alias": "type Name = string | number;\n", "enum": "enum Farbe {\n  Rot,\n  Gruen,\n}\n",
        "generische Funktion": "function name<T>(wert: T): T {\n  return wert;\n}\n", "class": "class Name {\n  constructor(private feld: string) {}\n}\n",
        "async function": "async function name(): Promise<void> {\n}\n"}),
    Lang("c", "C", (".c",), ["{out}"], build=["gcc", "-g", "-Wall", "{file}", "-o", "{out}"], lsp=["clangd"], snippets={
        "main": "#include <stdio.h>\n\nint main(void) {\n    return 0;\n}\n", "for-Schleife": "for (int i = 0; i < n; i++) {\n}\n",
        "while-Schleife": "while (bedingung) {\n}\n", "struct": "typedef struct {\n    int feld;\n} Name;\n", "Funktion": "int name(int a) {\n    return a;\n}\n",
        "printf": 'printf("%d\\n", wert);\n', "scanf": 'int x;\nscanf("%d", &x);\n', "malloc / free": "int *p = malloc(n * sizeof *p);\nif (!p) return 1;\nfree(p);\n",
        "Include-Guard": "#ifndef NAME_H\n#define NAME_H\n\n#endif\n", "switch": "switch (x) {\n    case 1:\n        break;\n    default:\n        break;\n}\n"}),
    Lang("cpp", "C++", (".cpp", ".cc", ".cxx", ".hpp", ".h"), ["{out}"], build=["g++", "-g", "-Wall", "-std=c++20", "{file}", "-o", "{out}"], lsp=["clangd"], snippets={
        "main": "#include <iostream>\n\nint main() {\n    return 0;\n}\n", "class": "class Name {\npublic:\n    Name() = default;\n};\n",
        "range-for": "for (const auto& x : items) {\n}\n", "Lambda": "auto f = [](int a) { return a; };\n", "vector": "#include <vector>\n\nstd::vector<int> v{1, 2, 3};\n",
        "unique_ptr": "#include <memory>\n\nauto p = std::make_unique<Name>();\n", "template": "template <typename T>\nT name(T a) {\n    return a;\n}\n",
        "try / catch": "try {\n} catch (const std::exception& e) {\n    std::cerr << e.what() << '\\n';\n}\n", "std::sort": "#include <algorithm>\n\nstd::sort(v.begin(), v.end(), [](int a, int b) { return a < b; });\n"}),
    Lang("csharp", "C#", (".cs",), ["dotnet", "run", "{file}"], lsp=["csharp-ls"], lsp_id="csharp", snippets={
        "Console.WriteLine": "Console.WriteLine();\n", "class": "public class Name\n{\n}\n", "foreach": "foreach (var item in items)\n{\n}\n",
        "LINQ": "var result = items.Where(x => x > 0).Select(x => x * 2).ToList();\n", "async Methode": "public async Task NameAsync()\n{\n    await Task.Delay(100);\n}\n",
        "Property": "public int Feld { get; set; }\n", "switch-Ausdruck": "var r = x switch\n{\n    1 => \"eins\",\n    _ => \"andere\",\n};\n",
        "record": "public record Name(int Feld);\n", "using / try": "using var f = File.OpenRead(pfad);\n"}),
    Lang("rust", "Rust", (".rs",), ["{out}"], build=["rustc", "-g", "{file}", "-o", "{out}"], lsp=["rust-analyzer"], snippets={
        "fn main": "fn main() {\n}\n", "struct + impl": "struct Name {\n    feld: i32,\n}\n\nimpl Name {\n    fn neu() -> Self {\n        Self { feld: 0 }\n    }\n}\n",
        "match": "match wert {\n    1 => {}\n    _ => {}\n}\n", "Result": "fn name() -> Result<(), Box<dyn std::error::Error>> {\n    Ok(())\n}\n",
        "for-Schleife": "for i in 0..n {\n}\n", "trait": "trait Name {\n    fn tu(&self);\n}\n", "#[test]": "#[test]\nfn beispiel() {\n    assert_eq!(1 + 1, 2);\n}\n"}),
    Lang("go", "Go", (".go",), ["go", "run", "{file}"], lsp=["gopls"], snippets={
        "main": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hallo")\n}\n', "func": "func name(a int) int {\n\treturn a\n}\n",
        "struct + Methode": "type Name struct {\n\tFeld int\n}\n\nfunc (n *Name) Tu() {\n}\n", "Goroutine": "go func() {\n}()\n",
        "Fehlerbehandlung": "if err != nil {\n\treturn err\n}\n", "for range": "for i, v := range items {\n}\n", "select": "select {\n\tcase v := <-ch:\n\t\t_ = v\n}\n",
        "Test": 'func TestBeispiel(t *testing.T) {\n\tif 1+1 != 2 {\n\t\tt.Fatal("falsch")\n\t}\n}\n'}),
    Lang("java", "Java", (".java",), ["java", "{file}"], lsp=["jdtls"], snippets={
        "main": "public class Main {\n    public static void main(String[] args) {\n    }\n}\n", "class": "public class Name {\n}\n",
        "for-each": "for (var x : items) {\n}\n", "try-with-resources": "try (var r = new java.io.FileReader(\"datei.txt\")) {\n} catch (Exception e) {\n}\n",
        "interface": "public interface Name {\n    void tu();\n}\n", "record": "public record Name(int feld) {}\n", "Stream": "var r = items.stream().filter(x -> x > 0).toList();\n"}),
    Lang("shell", "Bash", (".sh", ".bash"), ["bash", "{file}"], lsp=["bash-language-server", "start"], lsp_id="shellscript", comment="#", snippets={
        "Skript-Kopf": "#!/usr/bin/env bash\nset -euo pipefail\n", "Funktion": "name() {\n    echo \"$1\"\n}\n", "if": "if [[ -f datei ]]; then\n    echo ja\nfi\n",
        "for": "for f in *.txt; do\n    echo \"$f\"\ndone\n", "while read": "while IFS= read -r line; do\n    echo \"$line\"\ndone < datei.txt\n",
        "case": "case \"$1\" in\n    start) ;;\n    *) ;;\nesac\n", "getopts": "while getopts \"ab:\" opt; do\n    case $opt in\n        a) ;;\n        b) arg=$OPTARG ;;\n    esac\ndone\n"}),
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
