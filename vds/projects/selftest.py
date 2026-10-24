"""Selbsttest für frisch gebaute Projekte: findet Syntaxfehler und kaputte Importe, bevor der Nutzer F5 drückt.
Python: Syntax aller Dateien, dann Import jedes Moduls im .venv des Projekts. PHP: 'php -l'. Java Swing: 'javac'."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "vendor", "site-packages", "storage", "target", "build", "dist", ".vds", ".idea", "bootstrap"}
MAX_ERRORS = 15

IMPORT_SCRIPT = r'''
import importlib, json, os, sys, traceback
root = os.path.realpath(sys.argv[1]); sys.path.insert(0, root)
out = []
for name in json.loads(sys.argv[2]):
    try:
        importlib.import_module(name)
    except BaseException as e:
        frames = [f for f in traceback.extract_tb(e.__traceback__) if os.path.realpath(f.filename).startswith(root)]
        where = f"{os.path.relpath(os.path.realpath(frames[-1].filename), root)}:{frames[-1].lineno}" if frames else ""
        out.append({"module": name, "error": f"{type(e).__name__}: {e}", "where": where})
print("\n@@RESULT@@" + json.dumps(out))
'''


def _files(root: Path, suffix: str) -> list:
    out = []
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        out += [Path(dirpath) / n for n in sorted(names) if n.endswith(suffix)]
    return out


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def python_syntax(root: Path) -> list:
    errs = []
    for f in _files(root, ".py"):
        try:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")
        except SyntaxError as e:
            errs.append(f"{_rel(root, f)}:{e.lineno or 0}: Syntaxfehler: {e.msg}")
        except (OSError, ValueError) as e:
            errs.append(f"{_rel(root, f)}: nicht lesbar: {e}")
    return errs


def module_names(root: Path) -> list:
    """Importierbare Modulnamen des Projekts (ohne Tests und Konfigurationsdateien)."""
    names = []
    for f in _files(root, ".py"):
        parts = list(f.relative_to(root).with_suffix("").parts)
        if any(p.startswith("test") or p in ("tests", "conftest", "setup", "__main__") for p in parts):
            continue
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(p.isidentifier() for p in parts):
            names.append(".".join(parts))
    return sorted(set(names))


def python_imports(root: Path, python: str, timeout: int = 90, ignore_missing: bool = False) -> list:
    names = module_names(root)
    if not names:
        return []
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        r = subprocess.run([python, "-c", IMPORT_SCRIPT, str(root), json.dumps(names)], cwd=root, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return []                       # ein Modul startet beim Import die Anwendung – das ist kein Fehler
    except OSError as e:
        return [f"Python ließ sich nicht starten: {e}"]
    m = re.search(r"@@RESULT@@(.*)", r.stdout)
    if not m:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        return ["Import-Test ist abgestürzt: " + " | ".join(tail)] if r.returncode else []
    found = json.loads(m.group(1))
    if ignore_missing:                 # fremder Interpreter: nicht installierte Pakete sind kein Fehler des Projekts
        found = [d for d in found if not d["error"].startswith("ModuleNotFoundError")]
    grouped: dict = {}                 # dieselbe Ursache (Fehler + Stelle) nur einmal melden, mit allen betroffenen Modulen
    for d in found:
        grouped.setdefault((d["error"], d["where"]), []).append(d["module"])
    return [f"Import schlägt fehl: {err}" + (f" (in {where})" if where else "") + (f" – betrifft {', '.join(mods[:4])}" if len(mods) > 1 else f" – Modul {mods[0]}")
            for (err, where), mods in grouped.items()]


def php_syntax(root: Path) -> list:
    php = shutil.which("php")
    if not php:
        return []
    errs = []
    for f in _files(root, ".php"):
        r = subprocess.run([php, "-l", str(f)], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            text = r.stderr + "\n" + r.stdout
            m = re.search(r"(?:Parse|Fatal) error:\s+(.*?) in \S+ on line (\d+)", text)
            errs.append(f"{_rel(root, f)}:{m.group(2) if m else 0}: Syntaxfehler: {m.group(1) if m else (text.strip().splitlines() or ['unbekannt'])[0]}")
    return errs


def java_compile(root: Path) -> list:
    javac = shutil.which("javac")
    files = _files(root, ".java")
    if not javac or not files:
        return []
    with tempfile.TemporaryDirectory() as out:
        r = subprocess.run([javac, "-Xlint:none", "-d", out, *map(str, files)], cwd=root, capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        return []
    lines = [l for l in r.stderr.splitlines() if re.match(r".+\.java:\d+: (error|Fehler):", l)]
    return [l.replace(str(root) + "/", "") for l in lines] or [r.stderr.strip()[:300]]


def detect(root: Path, lang_id: str = "", template_id: str = "") -> str:
    if lang_id in ("python", "php") or template_id == "java-swing":
        return "java" if template_id == "java-swing" else lang_id
    if _files(root, ".py"):
        return "python"
    if _files(root, ".php") and (root / "composer.json").exists():
        return "php"
    return ""


def check_project(root: Path, lang_id: str = "", template_id: str = "", imports: bool = True) -> list:
    """Liefert eine Liste verständlicher Fehlermeldungen (leer = alles in Ordnung)."""
    root = Path(root)
    kind = detect(root, lang_id, template_id)
    errs: list = []
    if kind == "python":
        errs = python_syntax(root)
        if not errs and imports:
            own = next((str(root / c) for c in (".venv/bin/python", "venv/bin/python") if (root / c).is_file()), None)
            errs = python_imports(root, own) if own else python_imports(root, sys.executable, ignore_missing=True)
    elif kind == "php":
        errs = php_syntax(root)
    elif kind == "java":
        errs = java_compile(root)
    return errs[:MAX_ERRORS]


def fix_prompt(name: str, errors: list) -> str:
    bullets = "\n".join(f"- {e}" for e in errors)
    return (f"Der automatische Selbsttest hat im Projekt '{name}' Fehler gefunden:\n{bullets}\n\n"
            "Behebe genau diese Fehler und suche nach gleichartigen Fehlern an anderen Stellen. Prüfe besonders Importe und Namen: "
            "importiere nur Module, Klassen und Funktionen, die es in der verwendeten Bibliothek wirklich gibt. "
            "Beende deine Antwort wieder mit der Zeile MAIN: <relativer Pfad der Hauptdatei>.")
