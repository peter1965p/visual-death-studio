"""Paketquellen: NuGet, PyPI (pip), npm, crates.io (cargo). Jede Quelle liefert Suche, Versionen und den Zustand eines Projekts
sowie die Kommandos zum Installieren/Entfernen. Netzwerkaufrufe sind blockierend – sie laufen im Hintergrund-Thread der UI."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

UA = "VisualDeathStudio/0.1 (package manager)"
SKIP = {".git", "node_modules", "venv", ".venv", "bin", "obj", "target", "__pycache__", ".vds"}


def http_json(url: str, headers: dict | None = None, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def vkey(v: str):
    """Grober Versionsschlüssel (Zahlen vor Text); Vorabversionen sortieren vor der Release."""
    core, _, pre = v.partition("-")
    nums = [int(x) if x.isdigit() else 0 for x in re.split(r"[.+]", core)]
    return (nums, 0 if pre else 1, pre)


def is_pre(v: str) -> bool:
    return "-" in v or bool(re.search(r"(a|b|rc|dev|alpha|beta|pre)\d*$", v, re.I))


@dataclass
class Pkg:
    id: str
    version: str
    description: str = ""
    authors: str = ""
    downloads: int | None = None
    url: str = ""
    license: str = ""
    versions: list = field(default_factory=list)   # neueste zuerst
    installed: str | None = None
    latest: str | None = None


@dataclass
class Target:
    path: Path             # Projektdatei oder -ordner
    label: str


def _find(root: Path, pattern: str, depth=4):
    out = []
    for p in sorted(root.rglob(pattern)):
        parts = p.relative_to(root).parts
        if len(parts) <= depth and not SKIP & set(parts[:-1]):
            out.append(p)
    return out


class Source:
    name = ""
    ecosystem = ""
    supports_search = True

    def targets(self, root: Path) -> list: ...
    def search(self, q: str, pre: bool) -> list: ...
    def versions(self, pkg_id: str) -> list: return []
    def installed(self, t: Target) -> list: ...
    def install_cmd(self, t: Target, pkg_id: str, version: str) -> tuple: ...   # (cmd, cwd)
    def remove_cmd(self, t: Target, pkg_id: str) -> tuple: ...
    def after(self, t: Target, op: str, pkg_id: str, version: str = ""): ...    # z. B. requirements.txt pflegen
    def latest(self, pkg_id: str, pre: bool = False) -> str | None:
        vs = [v for v in self.versions(pkg_id) if pre or not is_pre(v)]
        return vs[0] if vs else None


# --- NuGet -------------------------------------------------------------------------------------------------
class NuGet(Source):
    name, ecosystem = "NuGet", "nuget"

    def targets(self, root):
        return [Target(p, p.name) for p in _find(root, "*.csproj")]

    def search(self, q, pre):
        d = http_json("https://azuresearch-usnc.nuget.org/query?" + urllib.parse.urlencode(
            {"q": q, "take": 30, "prerelease": str(pre).lower(), "semVerLevel": "2.0.0"}))
        out = []
        for x in d.get("data", []):
            vs = [v["version"] for v in x.get("versions", [])][::-1]
            out.append(Pkg(x["id"], x.get("version", ""), (x.get("description") or x.get("summary") or "").strip(),
                           ", ".join(x.get("authors") or []) if isinstance(x.get("authors"), list) else x.get("authors") or "",
                           x.get("totalDownloads"), x.get("projectUrl") or "", x.get("licenseUrl") or "", vs))
        return out

    def versions(self, pkg_id):
        try:
            d = http_json(f"https://api.nuget.org/v3-flatcontainer/{pkg_id.lower()}/index.json")
        except urllib.error.URLError:
            return []
        return sorted(d.get("versions", []), key=vkey, reverse=True)

    def installed(self, t):
        out = []
        try:
            root = ET.parse(t.path).getroot()
        except (ET.ParseError, OSError):
            return out
        for e in root.iter("PackageReference"):
            name = e.get("Include") or e.get("Update")
            ver = e.get("Version") or (e.findtext("Version") or "")
            if name:
                out.append(Pkg(name, ver, installed=ver))
        return out

    def install_cmd(self, t, pkg_id, version):
        cmd = ["dotnet", "add", str(t.path), "package", pkg_id]
        return (cmd + ["--version", version] if version else cmd), t.path.parent

    def remove_cmd(self, t, pkg_id):
        return ["dotnet", "remove", str(t.path), "package", pkg_id], t.path.parent


# --- PyPI / pip -----------------------------------------------------------------------------------------------
class PyPI(Source):
    name, ecosystem, supports_search = "PyPI (pip)", "pypi", False   # PyPI bietet keine Volltextsuche: exakter Name

    def targets(self, root):
        dirs = {p.parent for p in _find(root, "requirements.txt")} | {p.parent for p in _find(root, "pyproject.toml")}
        if not dirs and (_find(root, "*.py", 2) or (root / ".venv").exists()):
            dirs = {root}      # Python-Projekt ohne requirements.txt: pip trotzdem anbieten
        return [Target(d, (d.relative_to(root).as_posix() if d != root else ".") + "  (Python)") for d in sorted(dirs)]

    @staticmethod
    def python(t) -> str | None:
        p = t.path / ".venv" / "bin" / "python"
        return str(p) if p.exists() else None

    def search(self, q, pre):
        name = q.strip()
        if not name:
            return []
        try:
            d = http_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            raise
        info = d["info"]
        vs = sorted((v for v, files in d["releases"].items() if files and not all(f.get("yanked") for f in files)), key=vkey, reverse=True)
        return [Pkg(info["name"], info["version"], info.get("summary") or "", info.get("author") or "", None,
                    info.get("home_page") or (info.get("project_urls") or {}).get("Homepage", ""), info.get("license") or "", vs)]

    def versions(self, pkg_id):
        try:
            d = http_json(f"https://pypi.org/pypi/{urllib.parse.quote(pkg_id)}/json")
        except urllib.error.URLError:
            return []
        return sorted((v for v, f in d["releases"].items() if f), key=vkey, reverse=True)

    def installed(self, t):
        req = t.path / "requirements.txt"
        out = {}
        if req.exists():
            for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.split("#")[0].strip()
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(?:==\s*([^\s;]+))?", line)
                if m and not line.startswith("-"):
                    out[m.group(1).lower()] = Pkg(m.group(1), m.group(2) or "", installed=m.group(2) or "")
        return list(out.values())

    def install_cmd(self, t, pkg_id, version):
        py = self.python(t)
        if not py:
            raise RuntimeError("Keine virtuelle Umgebung (.venv) im Projekt. Lege sie an: python3 -m venv .venv")
        return [py, "-m", "pip", "install", f"{pkg_id}=={version}" if version else pkg_id], t.path

    def remove_cmd(self, t, pkg_id):
        py = self.python(t)
        if not py:
            raise RuntimeError("Keine virtuelle Umgebung (.venv) im Projekt.")
        return [py, "-m", "pip", "uninstall", "-y", pkg_id], t.path

    def after(self, t, op, pkg_id, version=""):
        req = t.path / "requirements.txt"
        lines = req.read_text(encoding="utf-8").splitlines() if req.exists() else []
        keep = [l for l in lines if not re.match(rf"\s*{re.escape(pkg_id)}\s*(==|>=|<=|~=|$|#)", l, re.I)]
        if op == "install":
            keep.append(f"{pkg_id}=={version}" if version else pkg_id)
        req.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")


# --- npm ------------------------------------------------------------------------------------------------------
class Npm(Source):
    name, ecosystem = "npm", "npm"

    def targets(self, root):
        return [Target(p.parent, (p.parent.relative_to(root).as_posix() if p.parent != root else ".") + "  (package.json)")
                for p in _find(root, "package.json")]

    def search(self, q, pre):
        d = http_json("https://registry.npmjs.org/-/v1/search?" + urllib.parse.urlencode({"text": q, "size": 30}))
        out = []
        for o in d.get("objects", []):
            p = o["package"]
            out.append(Pkg(p["name"], p.get("version", ""), p.get("description") or "", (p.get("publisher") or {}).get("username", ""),
                           None, (p.get("links") or {}).get("homepage") or (p.get("links") or {}).get("npm", ""), "", []))
        return out

    def versions(self, pkg_id):
        try:
            d = http_json(f"https://registry.npmjs.org/{urllib.parse.quote(pkg_id, safe='@')}", {"Accept": "application/vnd.npm.install-v1+json"}, 20)
        except urllib.error.URLError:
            return []
        return sorted(d.get("versions", {}).keys(), key=vkey, reverse=True)

    def installed(self, t):
        f = t.path / "package.json"
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        deps = {**d.get("dependencies", {}), **d.get("devDependencies", {})}
        return [Pkg(k, v.lstrip("^~"), installed=v.lstrip("^~")) for k, v in deps.items()]

    def install_cmd(self, t, pkg_id, version):
        return ["npm", "install", f"{pkg_id}@{version}" if version else pkg_id], t.path

    def remove_cmd(self, t, pkg_id):
        return ["npm", "uninstall", pkg_id], t.path


# --- crates.io / cargo ---------------------------------------------------------------------------------------------
class Crates(Source):
    name, ecosystem = "crates.io (cargo)", "crates"

    def targets(self, root):
        return [Target(p.parent, (p.parent.relative_to(root).as_posix() if p.parent != root else ".") + "  (Cargo.toml)")
                for p in _find(root, "Cargo.toml")]

    def search(self, q, pre):
        d = http_json("https://crates.io/api/v1/crates?" + urllib.parse.urlencode({"q": q, "per_page": 30}))
        return [Pkg(c["name"], c.get("max_stable_version") or c.get("max_version", ""), c.get("description") or "", "", c.get("downloads"),
                    c.get("homepage") or c.get("repository") or "", "", []) for c in d.get("crates", [])]

    def versions(self, pkg_id):
        try:
            d = http_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(pkg_id)}")
        except urllib.error.URLError:
            return []
        return sorted((v["num"] for v in d.get("versions", []) if not v.get("yanked")), key=vkey, reverse=True)

    def installed(self, t):
        f = t.path / "Cargo.toml"
        out, in_deps = [], False
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for line in lines:
            m = re.match(r"\s*\[(.+)\]\s*$", line)
            if m:
                in_deps = m.group(1).endswith("dependencies")
                continue
            if in_deps and "=" in line and not line.strip().startswith("#"):
                name, _, val = line.partition("=")
                v = re.search(r'"([^"]+)"', val)
                out.append(Pkg(name.strip(), v.group(1) if v else "", installed=v.group(1) if v else ""))
        return out

    def install_cmd(self, t, pkg_id, version):
        return ["cargo", "add", f"{pkg_id}@{version}" if version else pkg_id], t.path

    def remove_cmd(self, t, pkg_id):
        return ["cargo", "remove", pkg_id], t.path


SOURCES = [NuGet(), PyPI(), Npm(), Crates()]
BY_ECO = {s.ecosystem: s for s in SOURCES}
