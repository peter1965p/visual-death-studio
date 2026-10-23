"""Diff-Engine: Zeilenvergleich mit Ausrichtung für die Seite-an-Seite-Ansicht, Zeichenvergleich innerhalb
geänderter Zeilen und Hunk-Operationen (Änderung nach links/rechts übernehmen)."""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MAX_INTRALINE = 400     # längere Zeilen bekommen keinen Zeichenvergleich


@dataclass
class Text:
    lines: list
    trailing_nl: bool = True

    @staticmethod
    def parse(text: str) -> "Text":
        lines = text.split("\n")
        nl = len(lines) > 1 and lines[-1] == ""
        if nl:
            lines.pop()
        elif lines == [""]:
            lines = []
        return Text(lines, nl or text == "")

    def join(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.trailing_nl and self.lines else "")


@dataclass
class Row:
    kind: str                 # eq | add | del | chg
    lno: int | None           # 1-basierte Zeilennummer links/rechts (None = Platzhalter)
    rno: int | None
    ltext: str
    rtext: str
    hunk: int | None = None
    lspans: list = field(default_factory=list)   # [(start, ende)] geänderte Zeichen
    rspans: list = field(default_factory=list)


@dataclass
class Hunk:
    index: int
    a1: int
    a2: int                   # Zeilenbereich links  [a1, a2)
    b1: int
    b2: int                   # Zeilenbereich rechts [b1, b2)
    row1: int = 0
    row2: int = 0             # Zeilenbereich in der Zeilenliste [row1, row2)


def _key(line: str, ignore_ws: bool) -> str:
    return re.sub(r"\s+", " ", line).strip() if ignore_ws else line


def _spans(a: str, b: str):
    if not a or not b or len(a) > MAX_INTRALINE or len(b) > MAX_INTRALINE:
        return [], []
    ls, rs = [], []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("delete", "replace"):
            ls.append((i1, i2))
        if tag in ("insert", "replace"):
            rs.append((j1, j2))
    return ls, rs


SIM_MIN = 0.6           # ab dieser Ähnlichkeit gelten zwei Zeilen als „geändert“ statt gelöscht+hinzugefügt
MAX_ALIGN = 40000       # größere Blöcke (n*m) werden einfach der Reihe nach gepaart


def _sim(x: str, y: str) -> float:
    if x == y:
        return 1.0
    if not x.strip() or not y.strip():
        return 0.0
    sm = SequenceMatcher(None, x, y, autojunk=False)
    return sm.ratio() if sm.real_quick_ratio() >= SIM_MIN and sm.quick_ratio() >= SIM_MIN else 0.0


def _align(a: list, b: list):
    """Ordnet die Zeilen eines Ersetzen-Blocks nach Ähnlichkeit zu. Rückgabe: [('chg', i, j) | ('del', i) | ('add', j)]."""
    n, m = len(a), len(b)
    if n * m > MAX_ALIGN:
        return [("chg", k, k) if k < n and k < m else ("del", k) if k < n else ("add", k) for k in range(max(n, m))]
    sim = [[_sim(a[i], b[j]) for j in range(m)] for i in range(n)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1], best[i + 1][j + 1] + sim[i][j] if sim[i][j] >= SIM_MIN else 0.0)
    ops, i, j = [], 0, 0
    while i < n or j < m:
        if i < n and j < m and sim[i][j] >= SIM_MIN and best[i][j] == best[i + 1][j + 1] + sim[i][j]:
            ops.append(("chg", i, j)); i += 1; j += 1
        elif i < n and (j >= m or best[i][j] == best[i + 1][j]):
            ops.append(("del", i)); i += 1
        else:
            ops.append(("add", j)); j += 1
    return ops


def diff(a: list, b: list, ignore_ws: bool = False):
    """Rückgabe: (rows, hunks) für die Zeilenlisten a (links) und b (rechts)."""
    sm = SequenceMatcher(None, [_key(x, ignore_ws) for x in a], [_key(x, ignore_ws) for x in b], autojunk=False)
    rows, hunks = [], []
    for tag, a1, a2, b1, b2 in sm.get_opcodes():
        if tag == "equal":
            rows += [Row("eq", a1 + k + 1, b1 + k + 1, a[a1 + k], b[b1 + k]) for k in range(a2 - a1)]
            continue
        h = Hunk(len(hunks), a1, a2, b1, b2, row1=len(rows))
        for op in _align(a[a1:a2], b[b1:b2]):
            if op[0] == "chg":
                i, j = a1 + op[1], b1 + op[2]
                ls, rs = _spans(a[i], b[j])
                rows.append(Row("chg", i + 1, j + 1, a[i], b[j], h.index, ls, rs))
            elif op[0] == "del":
                rows.append(Row("del", a1 + op[1] + 1, None, a[a1 + op[1]], "", h.index))
            else:
                rows.append(Row("add", None, b1 + op[1] + 1, "", b[b1 + op[1]], h.index))
        h.row2 = len(rows)
        hunks.append(h)
    return rows, hunks


def stats(rows):
    added = sum(1 for r in rows if r.kind in ("add", "chg"))
    removed = sum(1 for r in rows if r.kind in ("del", "chg"))
    return added, removed


def apply_to_right(a: Text, b: Text, h: Hunk) -> Text:
    """Ersetzt den rechten Bereich durch den linken (Änderung rechts rückgängig machen)."""
    return Text(b.lines[: h.b1] + a.lines[h.a1: h.a2] + b.lines[h.b2:], b.trailing_nl)


def apply_to_left(a: Text, b: Text, h: Hunk) -> Text:
    """Ersetzt den linken Bereich durch den rechten (Änderung links übernehmen)."""
    return Text(a.lines[: h.a1] + b.lines[h.b1: h.b2] + a.lines[h.a2:], a.trailing_nl)
