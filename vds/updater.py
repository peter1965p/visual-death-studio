"""Selbst-Update: prüft die GitHub-Releases und spielt eine neuere Version in einer Git-Installation ein.

Aktualisiert wird nur, wenn der Programmordner ein sauberer Git-Klon ist (so legt `install.sh` ihn an): `git fetch --tags`, dann
Fast-Forward auf das Release-Tag, danach die Abhängigkeiten per pip. Lokale Änderungen oder eigene Commits werden nie überschrieben."""
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://api.github.com/repos/peter1965p/visual-death-studio/releases/latest"
TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass
class Release:
    tag: str
    url: str
    notes: str


def parse_version(v: str) -> tuple | None:
    m = TAG_RE.match(str(v).strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(tag: str, current: str) -> bool:
    a, b = parse_version(tag), parse_version(current)
    return a is not None and b is not None and a > b


def fetch_latest(url: str = API, timeout: float = 8.0) -> Release | None:
    """Neuestes veröffentlichtes Release oder None (offline, Fehler, Entwurf, Vorabversion)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "VisualDeathStudio-Updater"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("draft") or d.get("prerelease") or parse_version(d.get("tag_name", "")) is None:
        return None
    return Release(d["tag_name"], str(d.get("html_url", "")), str(d.get("body") or ""))


def _git(root: Path, *args, timeout=120):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip()


def blocker(root: Path) -> str:
    """Grund, warum ein Selbst-Update nicht geht – oder '' wenn es möglich ist."""
    root = Path(root)
    if not (root / ".git").exists() or not shutil.which("git"):
        return "Diese Installation ist kein Git-Klon (oder git fehlt) – bitte von Hand aktualisieren: git pull und ./install.sh."
    rc, out = _git(root, "status", "--porcelain", "--untracked-files=no")
    if rc or out:
        return "Im Programmordner gibt es lokale Änderungen – das Update würde sie gefährden. Bitte erst committen oder zurücksetzen."
    rc, out = _git(root, "remote", "get-url", "origin")
    if rc or not out:
        return "Der Programmordner hat kein Remote »origin«."
    return ""


def apply_update(root: Path, tag: str) -> tuple:
    """(ok, Meldung). Setzt den Programmordner per Fast-Forward auf das Release-Tag und aktualisiert die Pakete."""
    root = Path(root)
    if parse_version(tag) is None:
        return False, f"Ungültiges Release-Tag: {tag}"
    why = blocker(root)
    if why:
        return False, why
    tag = tag if tag.startswith("v") else "v" + tag
    rc, out = _git(root, "fetch", "--tags", "origin")
    if rc:
        return False, "Abrufen fehlgeschlagen: " + out
    rc, out = _git(root, "merge", "--ff-only", f"refs/tags/{tag}")
    if rc:
        return False, f"Das Update auf {tag} ist nicht als einfaches Vorspulen möglich (eigene Commits?): {out}"
    req = root / "requirements.txt"
    if req.is_file():
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-r", str(req)],
                               capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"Der Code ist auf {tag}, aber die Pakete konnten nicht installiert werden: {e}"
        if r.returncode:
            return False, f"Der Code ist auf {tag}, aber pip meldet: {(r.stderr or r.stdout).strip()[-400:]}"
    return True, f"Aktualisiert auf {tag}."
