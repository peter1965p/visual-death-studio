"""Test-Frameworks: Entdecken und Ausführen von Tests samt Auswertung der Ergebnisse.
Unterstützt pytest, unittest, Node (node:test), Go, Cargo und dotnet. Alle Befehle laufen im Projektordner."""
import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "target", "dist", "build", ".vds", "bin", "obj"}


@dataclass
class TestCase:
    __test__ = False        # kein pytest-Test, obwohl der Name mit „Test“ beginnt
    id: str                 # eindeutig, z. B. tests/test_x.py::TestA::test_b
    name: str
    file: str = ""          # relativ zum Projekt
    group: tuple = ()       # Anzeigehierarchie unterhalb der Datei, z. B. ("TestA",)
    line: int = 0


@dataclass
class Result:
    status: str             # passed | failed | skipped | error
    message: str = ""
    seconds: float = 0.0


def _files(root: Path, patterns: tuple, limit=2000):
    out = []
    for pat in patterns:
        for p in root.rglob(pat):
            if not SKIP_DIRS & set(p.relative_to(root).parts[:-1]) and p.is_file():
                out.append(p)
    return sorted(set(out))[:limit]


def locate(root: Path, file: str, name: str) -> int:
    """Zeile der Testdefinition (Python: def/class, JS: test/it, Go: func) – 0, wenn nicht gefunden."""
    try:
        text = (root / file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    base = re.split(r"[\[(]", name)[0]
    pat = re.compile(rf"(def\s+{re.escape(base)}\b|func\s+{re.escape(base)}\b|fn\s+{re.escape(base)}\b|(?:test|it|describe)\s*\(\s*['\"`]{re.escape(name)}|\b{re.escape(base)}\s*\()")
    for i, line in enumerate(text, 1):
        if pat.search(line):
            return i
    return 0


class Framework:
    name = ""
    can_debug = False

    def __init__(self, root: Path, python: str):
        self.root, self.python = Path(root), python

    def detect(self) -> bool: ...
    def discover_cmd(self) -> tuple | None: ...                    # (cmd, cwd)
    def parse_discovery(self, out: str, err: str, code: int) -> list: ...
    def run_cmd(self, ids: list | None, tmp: Path) -> tuple: ...   # (cmd, cwd)
    def parse_results(self, out: str, err: str, code: int, tmp: Path, cases: dict) -> dict: ...


# ---------------------------------------------------------------------------------------------------------------------
class Pytest(Framework):
    name, can_debug = "pytest", True

    def detect(self):
        if not (_files(self.root, ("test_*.py", "*_test.py"), 5) or (self.root / "tests").is_dir()):
            return False
        import subprocess
        return subprocess.run([self.python, "-c", "import pytest"], capture_output=True).returncode == 0

    def discover_cmd(self):
        return [self.python, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], self.root

    def parse_discovery(self, out, err, code):
        cases = []
        for line in out.splitlines():
            m = re.match(r"^(\S+?\.py)::(.+)$", line.strip())
            if not m:
                continue
            parts = m.group(2).split("::")
            cases.append(TestCase(line.strip(), parts[-1], m.group(1), tuple(parts[:-1]), locate(self.root, m.group(1), parts[-1])))
        return cases

    def run_cmd(self, ids, tmp):
        return [self.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml", str(tmp / "r.xml"), *(ids or [])], self.root

    def _id_for(self, classname: str, name: str) -> str:
        parts = classname.split(".") if classname else []
        for i in range(len(parts), 0, -1):
            f = Path(*parts[:i]).with_suffix(".py")
            if (self.root / f).exists():
                return "::".join([f.as_posix(), *parts[i:], name])
        return "::".join([*parts, name])

    def parse_results(self, out, err, code, tmp, cases):
        res = {}
        try:
            tree = ET.parse(tmp / "r.xml")
        except (OSError, ET.ParseError):
            return res
        for tc in tree.iter("testcase"):
            tid = self._id_for(tc.get("classname", ""), tc.get("name", ""))
            t = float(tc.get("time", 0) or 0)
            fail, err_, skip = tc.find("failure"), tc.find("error"), tc.find("skipped")
            if fail is not None:
                res[tid] = Result("failed", (fail.get("message", "") + "\n" + (fail.text or "")).strip(), t)
            elif err_ is not None:
                res[tid] = Result("error", (err_.get("message", "") + "\n" + (err_.text or "")).strip(), t)
            elif skip is not None:
                res[tid] = Result("skipped", skip.get("message", ""), t)
            else:
                res[tid] = Result("passed", "", t)
        return res


class Unittest(Framework):
    name, can_debug = "unittest", True

    LIST = ("import unittest,sys\n"
            "def walk(s):\n    for t in s:\n        walk(t) if isinstance(t, unittest.TestSuite) else print('ID', t.id())\n"
            "walk(unittest.defaultTestLoader.discover('.', top_level_dir='.'))\n")

    def detect(self):
        return bool(_files(self.root, ("test*.py", "*_test.py"), 5))

    def discover_cmd(self):
        return [self.python, "-c", self.LIST], self.root

    def _file_for(self, tid: str):
        parts = tid.split(".")
        for i in range(len(parts), 0, -1):
            f = Path(*parts[:i]).with_suffix(".py")
            if (self.root / f).exists():
                return f.as_posix(), tuple(parts[i:-1]), parts[-1]
        return "", tuple(parts[:-1]), parts[-1]

    def parse_discovery(self, out, err, code):
        cases = []
        for line in out.splitlines():
            if line.startswith("ID "):
                tid = line[3:].strip()
                f, group, name = self._file_for(tid)
                cases.append(TestCase(tid, name, f, group, locate(self.root, f, name) if f else 0))
        return cases

    def run_cmd(self, ids, tmp):
        if ids:
            return [self.python, "-m", "unittest", "-v", *ids], self.root
        return [self.python, "-m", "unittest", "discover", "-v", "-s", ".", "-t", "."], self.root

    def parse_results(self, out, err, code, tmp, cases):
        text = err + "\n" + out
        res = {}
        for m in re.finditer(r"^(\w+) \(([\w.]+)\)(?:\n[^\n]*?)? \.\.\. (ok|FAIL|ERROR|skipped '?(.*?)'?|expected failure|unexpected success)\s*$", text, re.M):
            tid, st = m.group(2), m.group(3)
            res[tid] = Result("passed" if st in ("ok", "expected failure") else "skipped" if st.startswith("skipped") else "failed" if st in ("FAIL", "unexpected success") else "error",
                              m.group(4) or "")
        for m in re.finditer(r"^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)\n-{10,}\n(.*?)(?=\n={10,}|\n-{10,}\nRan |\Z)", text, re.M | re.S):
            if m.group(2) in res:
                res[m.group(2)].message = m.group(3).strip()
        return res


# ---------------------------------------------------------------------------------------------------------------------
class NodeTest(Framework):
    name = "node:test"
    PATTERNS = ("*.test.js", "*.test.mjs", "*.test.cjs", "*.test.ts", "*-test.js", "*_test.js", "test-*.js")

    def detect(self):
        return shutil.which("node") is not None and bool(_files(self.root, self.PATTERNS, 3))

    def discover_cmd(self):
        return None                                   # Entdeckung über Quelltext-Suche

    def discover_static(self) -> list:
        cases = []
        for f in _files(self.root, self.PATTERNS):
            rel = f.relative_to(self.root).as_posix()
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                m = re.search(r"\b(?:test|it)\s*\(\s*(['\"`])(.+?)\1", line)
                if m:
                    cases.append(TestCase(f"{rel}::{m.group(2)}", m.group(2), rel, (), i))
        return cases

    def parse_discovery(self, out, err, code):
        return self.discover_static()

    def run_cmd(self, ids, tmp):
        files = sorted({i.split("::")[0] for i in ids}) if ids else []
        return ["node", "--test", "--test-reporter=tap", *files], self.root

    def parse_results(self, out, err, code, tmp, cases):
        res, cur_file = {}, ""
        lines = out.splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)# Subtest: (.+)$", line)
            if m and not m.group(1):
                cur_file = m.group(2).strip()
            m = re.match(r"^(\s*)(not ok|ok) \d+ - (.+?)(?: # (SKIP|TODO).*)?$", line)
            if not m:
                continue
            name, ok, skip = m.group(3).strip(), m.group(2) == "ok", m.group(4)
            msg = []
            for nxt in lines[i + 1:i + 40]:
                if re.match(r"^\s*(not ok|ok) \d+ - ", nxt):
                    break
                msg.append(nxt.strip())
            for cid, c in cases.items():
                if c.name == name:
                    res[cid] = Result("skipped" if skip else "passed" if ok else "failed", "" if ok else "\n".join(msg[:25]).strip())
        return res


class GoTest(Framework):
    name = "go test"

    def detect(self):
        return shutil.which("go") is not None and bool(_files(self.root, ("*_test.go",), 3))

    def discover_cmd(self):
        return ["go", "test", "-list", ".*", "./..."], self.root

    def parse_discovery(self, out, err, code):
        cases = []
        for line in out.splitlines():
            if re.match(r"^(Test|Example|Benchmark)\w*$", line.strip()):
                n = line.strip()
                f = next((p.relative_to(self.root).as_posix() for p in _files(self.root, ("*_test.go",)) if f"func {n}(" in p.read_text(errors="replace")), "")
                cases.append(TestCase(n, n, f, (), locate(self.root, f, n) if f else 0))
        return cases

    def run_cmd(self, ids, tmp):
        cmd = ["go", "test", "-json", "-count=1"]
        if ids:
            cmd += ["-run", "^(" + "|".join(re.escape(i) for i in ids) + ")$"]
        return cmd + ["./..."], self.root

    def parse_results(self, out, err, code, tmp, cases):
        res, outputs = {}, {}
        for line in out.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = e.get("Test")
            if not t:
                continue
            if e["Action"] == "output":
                outputs.setdefault(t, []).append(e.get("Output", ""))
            elif e["Action"] in ("pass", "fail", "skip"):
                res[t] = Result({"pass": "passed", "fail": "failed", "skip": "skipped"}[e["Action"]],
                                "" if e["Action"] == "pass" else "".join(outputs.get(t, [])).strip(), e.get("Elapsed", 0))
        return res


class CargoTest(Framework):
    name = "cargo test"

    def detect(self):
        return shutil.which("cargo") is not None and (self.root / "Cargo.toml").exists()

    def discover_cmd(self):
        return ["cargo", "test", "--", "--list"], self.root

    def parse_discovery(self, out, err, code):
        return [TestCase(m.group(1), m.group(1).split("::")[-1], "", tuple(m.group(1).split("::")[:-1])) for m in re.finditer(r"^(\S+): test$", out, re.M)]

    def run_cmd(self, ids, tmp):
        return ["cargo", "test", *(ids or []), "--", "--test-threads=1"], self.root

    def parse_results(self, out, err, code, tmp, cases):
        res = {}
        for m in re.finditer(r"^test (\S+) \.\.\. (ok|FAILED|ignored)", out, re.M):
            msg = ""
            if m.group(2) == "FAILED":
                f = re.search(rf"---- {re.escape(m.group(1))} stdout ----\n(.*?)(?=\n---- |\nfailures:|\Z)", out, re.S)
                msg = f.group(1).strip() if f else ""
            res[m.group(1)] = Result("passed" if m.group(2) == "ok" else "skipped" if m.group(2) == "ignored" else "failed", msg)
        return res


class DotnetTest(Framework):
    name = "dotnet test"

    def detect(self):
        return shutil.which("dotnet") is not None and any("Test" in p.read_text(errors="replace") and "Microsoft.NET.Test.Sdk" in p.read_text(errors="replace")
                                                            for p in _files(self.root, ("*.csproj",), 20))

    def discover_cmd(self):
        return ["dotnet", "test", "--list-tests"], self.root

    def parse_discovery(self, out, err, code):
        cases, on = [], False
        for line in out.splitlines():
            if "following Tests are available" in line or "folgenden Tests sind verfügbar" in line.lower():
                on = True
            elif on and line.startswith("    "):
                n = line.strip()
                cases.append(TestCase(n, n.split(".")[-1], "", tuple(n.split(".")[:-1])))
        return cases

    def run_cmd(self, ids, tmp):
        cmd = ["dotnet", "test", "--logger", f"trx;LogFileName={tmp / 'r.trx'}"]
        if ids:
            cmd += ["--filter", "|".join(f"FullyQualifiedName={i}" for i in ids)]
        return cmd, self.root

    def parse_results(self, out, err, code, tmp, cases):
        res = {}
        try:
            tree = ET.parse(tmp / "r.trx")
        except (OSError, ET.ParseError):
            return res
        for r in tree.iter():
            if r.tag.endswith("UnitTestResult"):
                oc = r.get("outcome", "")
                msg = ""
                for el in r.iter():
                    if el.tag.endswith("Message") and el.text:
                        msg = el.text.strip()
                name = r.get("testName", "")
                full = next((cid for cid in cases if cid.endswith(name)), name)
                res[full] = Result("passed" if oc == "Passed" else "skipped" if oc in ("NotExecuted", "Skipped") else "failed", msg)
        return res


def detect_frameworks(root: Path, python: str) -> list:
    """Alle passenden Frameworks im Projekt (pytest hat Vorrang vor unittest)."""
    found = []
    for cls in (Pytest, Unittest, NodeTest, GoTest, CargoTest, DotnetTest):
        fw = cls(root, python)
        if fw.detect():
            if cls is Unittest and any(isinstance(f, Pytest) for f in found):
                continue
            found.append(fw)
    return found
