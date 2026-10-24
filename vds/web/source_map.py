"""Findet zu einem angeklickten DOM-Element die Stellen im Projektquelltext (id, Klassen, Text) – sortiert nach Treffsicherheit."""
import re
from dataclasses import dataclass
from pathlib import Path

MARKUP_EXT = {".html", ".htm", ".vue", ".svelte", ".astro", ".jsx", ".tsx", ".js", ".ts", ".php", ".twig", ".erb", ".ejs", ".njk", ".mdx", ".cshtml", ".razor", ".hbs"}
STYLE_EXT = {".css", ".scss", ".less"}
SKIP_DIRS = {"node_modules", ".git", ".vds", "dist", "build", ".next", ".nuxt", ".output", "vendor", "storage", "__pycache__", ".svelte-kit", "coverage", ".angular", ".cache"}
MAX_FILE = 600_000


@dataclass
class Candidate:
    file: Path
    line: int
    pos: int
    score: int
    kind: str          # id | klasse | text
    snippet: str

    def label(self, root: Path) -> str:
        try:
            rel = self.file.relative_to(root)
        except ValueError:
            rel = self.file
        return f"{rel}:{self.line}  [{self.kind}, {self.score}]  {self.snippet}"


def project_files(root: Path, exts=None, limit=4000) -> list:
    exts = exts or (MARKUP_EXT | STYLE_EXT)
    out = []
    root = Path(root)
    for p in sorted(root.rglob("*")):
        if len(out) >= limit:
            break
        if p.is_file() and p.suffix.lower() in exts and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            try:
                if p.stat().st_size <= MAX_FILE:
                    out.append(p)
            except OSError:
                pass
    return out


def read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def snippet_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:end if end >= 0 else len(text)].strip()[:90]


CLASS_ATTR = re.compile(r"""(?:\bclass|\bclassName|:class|\bclass:list)\s*[:=]\s*\{?\s*(["'`])(.*?)\1""", re.S)


def search(root: Path, info: dict, limit=25) -> list:
    """Kandidaten für ein Element (info aus der Seite: id, stableClasses, text, tag)."""
    ident, classes, text, tag = info.get("id", ""), info.get("stableClasses") or [], (info.get("text") or "").strip(), info.get("tag", "")
    found: dict = {}

    def add(file, pos, score, kind, src):
        key = (file, line_of(src, pos))
        if key not in found or found[key].score < score:
            found[key] = Candidate(file, key[1], pos, score, kind, snippet_at(src, pos))

    id_rx = re.compile(r"""\bid\s*[:=]\s*\{?\s*["'`]""" + re.escape(ident) + r"""["'`]""") if ident else None
    for f in project_files(root, MARKUP_EXT):
        src = read(f)
        if src is None:
            continue
        if id_rx:
            for m in id_rx.finditer(src):
                add(f, m.start(), 100, "id", src)
        if classes:
            want = set(classes)
            for m in CLASS_ATTR.finditer(src):
                tokens = set(re.split(r"[\s]+", re.sub(r"\$\{[^}]*\}", " ", m.group(2)).strip()))
                hit = want & tokens
                if hit == want:
                    lt = src.rfind("<", 0, m.start())
                    bonus = 5 if tag and lt >= 0 and src[lt + 1:lt + 1 + len(tag)].lower() == tag else 0
                    add(f, m.start(), 80 + min(len(want), 5) + bonus, "klasse", src)
                elif len(want) >= 3 and len(hit) * 10 >= len(want) * 6:
                    add(f, m.start(), 45, "klasse", src)
        if len(text) >= 2 and "\n" not in text:
            t = re.escape(text)
            for m in re.finditer(r">\s*" + t + r"\s*<", src):
                add(f, m.start() + 1, 70, "text", src)
            for m in re.finditer(r"""(["'`])""" + t + r"""\1""", src):
                add(f, m.start(), 55, "text", src)
            for m in re.finditer(r"(?<=\n)[^\n<>]*" + t + r"[^\n<>]*(?=\n)", src):
                add(f, m.start() + m.group(0).find(text), 45, "text", src)
    return sorted(found.values(), key=lambda c: (-c.score, str(c.file), c.line))[:limit]
