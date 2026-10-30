"""Änderungserkennung: Snapshot-Vergleich (für Claude-Läufe) und Git-Hilfen (Status, HEAD-Inhalt, Stage, Commit)."""
import subprocess
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", ".vds", "target", "dist", "build", "bin", "obj", ".idea"}
MAX_FILES, MAX_BYTES, MAX_TOTAL = 3000, 1_000_000, 40_000_000


@dataclass
class Change:
    rel: str
    status: str            # M geändert | A neu | D gelöscht
    old: str | None
    new: str | None


def read_text(p: Path) -> str | None:
    """Textinhalt oder None bei Binär-/zu großen/unlesbaren Dateien."""
    try:
        if p.stat().st_size > MAX_BYTES:
            return None
        data = p.read_bytes()
    except OSError:
        return None
    return None if b"\0" in data[:8192] else data.decode("utf-8", errors="replace")


def _walk(root: Path):
    n = 0
    for p in root.rglob("*"):
        if SKIP_DIRS & set(p.relative_to(root).parts[:-1]) or p.name in SKIP_DIRS or not p.is_file():
            continue
        yield p
        n += 1
        if n >= MAX_FILES:
            return


def take_snapshot(root: Path) -> dict:
    snap, total = {}, 0
    for p in _walk(root):
        t = read_text(p)
        if t is not None:
            total += len(t)
            if total > MAX_TOTAL:
                break
            snap[p.relative_to(root).as_posix()] = t
    return snap


def diff_snapshot(root: Path, snap: dict) -> list:
    now = take_snapshot(root)
    out = [Change(r, "M", snap[r], now[r]) for r in sorted(snap.keys() & now.keys()) if snap[r] != now[r]]
    out += [Change(r, "A", None, now[r]) for r in sorted(now.keys() - snap.keys())]
    out += [Change(r, "D", snap[r], None) for r in sorted(snap.keys() - now.keys()) if not (root / r).exists()]
    return sorted(out, key=lambda c: c.rel)


# --- Git ---------------------------------------------------------------------------------------
@dataclass
class GitEntry:
    rel: str               # relativ zum Repository-Wurzelverzeichnis
    x: str                 # Index-Status
    y: str                 # Arbeitsbaum-Status

    @property
    def staged(self):
        return self.x not in " ?"

    @property
    def unstaged(self):
        return self.y != " "

    @property
    def label(self):
        return "??" if self.x == "?" else (self.x + self.y).replace(" ", "·")


def git(cwd: Path, *args, check=False, timeout=30, env=None):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout))


def toplevel(root: Path) -> Path | None:
    rc, out = git(root, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if rc == 0 and out.strip() else None


def branch(top: Path) -> str:
    rc, out = git(top, "branch", "--show-current")
    return out.strip() if rc == 0 and out.strip() else "(losgelöst)"


def status(top: Path) -> list:
    rc, out = git(top, "status", "--porcelain=v1", "-z", "-uall")
    if rc != 0:
        return []
    parts, entries, i = out.split("\0"), [], 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        x, y, rel = e[0], e[1], e[3:]
        if x in "RC":
            i += 1            # alter Name folgt als eigener Eintrag
        entries.append(GitEntry(rel, x, y))
    return entries


def head_text(top: Path, rel: str) -> str:
    """Inhalt in HEAD; leer, wenn die Datei dort nicht existiert."""
    try:
        r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=top, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 and b"\0" not in r.stdout[:8192] else ""


def stage(top, rels):
    return git(top, "add", "--", *rels)


def unstage(top, rels):
    rc, out = git(top, "restore", "--staged", "--", *rels)
    return (rc, out) if rc == 0 else git(top, "rm", "--cached", "-q", "--", *rels)


def discard(top, entries):
    """Verwirft Änderungen: getrackte Dateien aus HEAD wiederherstellen, unversionierte löschen."""
    errs = []
    for e in entries:
        p = top / e.rel
        if e.x == "?":
            try:
                p.unlink()
            except OSError as ex:
                errs.append(str(ex))
        else:
            rc, out = git(top, "checkout", "HEAD", "--", e.rel)
            if rc != 0:
                errs.append(out.strip())
    return (1, "\n".join(errs)) if errs else (0, "")


def commit(top, msg):
    return git(top, "commit", "-m", msg)


def remotes(top: Path) -> dict:
    """{Name: URL} der konfigurierten Remotes."""
    rc, out = git(top, "remote", "-v")
    found = {}
    for line in out.splitlines() if rc == 0 else []:
        parts = line.split()
        if len(parts) >= 2:
            found.setdefault(parts[0], parts[1])
    return found


def add_remote(top: Path, url: str, name: str = "origin"):
    return git(top, "remote", "add", name, url.strip())


def upstream(top: Path) -> str:
    rc, out = git(top, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return out.strip() if rc == 0 else ""


def _net_env():
    import os
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true", "SSH_ASKPASS": "true"}      # nie auf eine Passwort-Eingabe warten


def _explain(out: str) -> str:
    low = out.lower()
    if any(k in low for k in ("authentication failed", "permission denied", "could not read username", "terminal prompts disabled", "403")):
        return out.strip() + ("\n\nAnmeldung fehlgeschlagen: Hinterlege einen SSH-Schlüssel oder einen Credential-Helper "
                              "(z. B. `gh auth login` und `gh auth setup-git`), dann erneut versuchen.")
    return out.strip()


def push(top: Path):
    """Push des aktuellen Branches; ohne Upstream wird er mit -u auf das erste Remote gesetzt."""
    rem = remotes(top)
    if not rem:
        return 1, "Kein Remote eingetragen."
    args = ["push"] if upstream(top) else ["push", "-u", "origin" if "origin" in rem else next(iter(rem)), "HEAD"]
    rc, out = git(top, *args, timeout=180, env=_net_env())
    return rc, _explain(out) if rc else (out.strip() or "Push erledigt.")


def pull(top: Path):
    rc, out = git(top, "pull", "--ff-only", timeout=180, env=_net_env())
    return rc, _explain(out) if rc else (out.strip() or "Bereits aktuell.")
