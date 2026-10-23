"""Kleine lokale Projektanalyse (Sprachen, Manifeste, Einstiegspunkte) für das Menü Projekt.
Das eigentliche REA (rea-agents, MCP) ist ein separates Werkzeug und wird hier nicht ersetzt."""
import re
from collections import Counter
from pathlib import Path

from .build.languages import lang_for

SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "target", "dist", "build", ".vds"}
MANIFESTS = {"requirements.txt", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "CMakeLists.txt", "Makefile", "pom.xml"}
ENTRY = re.compile(r"__main__|\bint\s+main\s*\(|\bfn\s+main\s*\(|\bfunc\s+main\s*\(|static\s+void\s+Main|public\s+static\s+void\s+main")


def analyze_dir(root: Path) -> str:
    files = [p for p in root.rglob("*") if p.is_file() and not SKIP & set(p.relative_to(root).parts)][:5000]
    langs, lines, manifests, entries = Counter(), Counter(), [], []
    for p in files:
        if p.name in MANIFESTS:
            manifests.append(p.relative_to(root).as_posix())
        lang = lang_for(p)
        if lang and p.stat().st_size < 1_000_000:
            text = p.read_text(encoding="utf-8", errors="replace")
            langs[lang.name] += 1; lines[lang.name] += text.count("\n") + 1
            if ENTRY.search(text):
                entries.append(p.relative_to(root).as_posix())
    out = [f"Analyse von {root} – {len(files)} Dateien\n", "\nSprachen:\n"]
    out += [f"  {n:<12}{langs[n]:>5} Dateien {lines[n]:>8} Zeilen\n" for n in sorted(langs, key=lambda k: -lines[k])]
    out += ["\nProjektdateien:\n"] + [f"  {m}\n" for m in manifests]
    out += ["\nEinstiegspunkte:\n"] + [f"  {e}\n" for e in entries]
    return "".join(out)
