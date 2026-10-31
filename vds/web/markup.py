"""Elementstruktur von HTML-, Blade-, PHP-, Vue-, JSX-Vorlagen: toleranter Parser, Zuordnung „Element der Seite → Stelle im Quelltext“
und die Strukturänderungen (einfügen, duplizieren, löschen, umordnen), jeweils als `Plan` mit Unterschied."""
import bisect
import html as _html
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import source_map as sm
from .writer import Plan

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAWTEXT = {"script", "style"}
IMPLIED = {"li": {"li"}, "option": {"option"}, "tr": {"tr"}, "td": {"td", "th"}, "th": {"td", "th"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}}   # öffnendes Tag schließt offene Tags
NAME = re.compile(r"[A-Za-z][\w:.-]*")
SPECIAL = re.compile(r"<!--|<\?|\{\{--|\{\{|\{!!|@php\b|</?[A-Za-z]")
COND = re.compile(r"@(?:if|unless|isset|empty|auth|guest|can|env|production)\b.*?@end\w+", re.S)       # bedingte Blade-Blöcke
DYNAMIC = re.compile(r"\{\{.*?\}\}|\{!!.*?!!\}|<\?.*?\?>|@\w+\s*\([^)]*\)", re.S)


@dataclass(eq=False)
class Node:
    tag: str
    start: int
    open_end: int
    attr: dict
    parent: "Node | None" = None
    close_start: int | None = None
    end: int | None = None
    complete: bool = True
    void: bool = False
    line: int = 1
    children: list = field(default_factory=list)


# --- Lesen -----------------------------------------------------------------------------------------------------------
def _skip_quoted(text: str, i: int, q: str) -> int:
    """Index hinter dem schließenden Anführungszeichen; {{ … }} darf selbst Anführungszeichen enthalten."""
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            j = text.find("}}", i)
            i = n if j < 0 else j + 2
        elif text[i] == q:
            return i + 1
        else:
            i += 1
    return n


def _skip_parens(text: str, i: int) -> int:
    """i steht auf „(“ einer Blade-Direktive; Index hinter der passenden „)“."""
    depth, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            i = _skip_quoted(text, i + 1, c); continue
        depth += (c == "(") - (c == ")")
        i += 1
        if depth == 0:
            break
    return i


def _scan_tag(text: str, i: int) -> int:
    """Index von „>“, das das Tag ab i beendet (Anführungszeichen, {{ }}, <?php ?>, @if(…) werden übersprungen); -1 wenn keins."""
    n = len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            i = _skip_quoted(text, i + 1, c); continue
        if text.startswith("{{", i) or text.startswith("{!!", i):
            j = text.find("}}" if text.startswith("{{", i) else "!!}", i)
            i = n if j < 0 else j + (2 if text.startswith("{{", i) else 3); continue
        if text.startswith("<?", i):
            j = text.find("?>", i); i = n if j < 0 else j + 2; continue
        if c == "@" and re.match(r"@\w+\s*\(", text[i:i + 40]):
            i = _skip_parens(text, text.index("(", i)); continue
        if c == ">":
            return i
        if c == "<" and i + 1 < n and text[i + 1].isalpha():
            return -1                                           # nächstes Tag beginnt: dieses war keins
        i += 1
    return -1


def parse_attrs(s: str) -> dict:
    out, i, n = {}, 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace() or c == "/":
            i += 1; continue
        if c == "@" and re.match(r"@\w+\s*\(", s[i:i + 40]):
            i = _skip_parens(s, s.index("(", i)); continue
        if s.startswith("{{", i) or s.startswith("<?", i):
            j = s.find("}}" if s.startswith("{{", i) else "?>", i); i = n if j < 0 else j + 2; continue
        m = re.match(r"[^\s=/>\"']+", s[i:])
        if not m:
            i += 1; continue
        name = m.group(0); i += len(name)
        while i < n and s[i].isspace():
            i += 1
        if i < n and s[i] == "=":
            i += 1
            while i < n and s[i].isspace():
                i += 1
            if i < n and s[i] in "\"'":
                q = s[i]; j = _skip_quoted(s, i + 1, q); out[name] = s[i + 1:j - 1]; i = j
            else:
                m2 = re.match(r"(?:\{\{.*?\}\}|[^\s>])+", s[i:], re.S)
                out[name] = m2.group(0) if m2 else ""; i += len(m2.group(0)) if m2 else 0
        else:
            out[name] = ""
    return out


def parse(text: str) -> Node:
    root = Node("#root", 0, 0, {}, end=len(text), close_start=len(text))
    nl = [m.start() for m in re.finditer("\n", text)]
    line = lambda pos: bisect.bisect_left(nl, pos) + 1
    stack, i, n = [root], 0, len(text)
    while i < n:
        m = SPECIAL.search(text, i)
        if not m:
            break
        tok = m.group(0)
        if tok in ("<!--", "<?", "{{--", "{{", "{!!") or tok == "@php":
            end_tok = {"<!--": "-->", "<?": "?>", "{{--": "--}}", "{{": "}}", "{!!": "!!}"}.get(tok, "@endphp")
            if tok == "@php" and re.match(r"@php\s*\(", text[m.start():m.start() + 20]):
                i = m.end(); continue                            # @php(…) als Einzeiler
            j = text.find(end_tok, m.end())
            i = n if j < 0 else j + len(end_tok)
            continue
        if tok.startswith("</"):
            gt = text.find(">", m.start())
            if gt < 0:
                break
            tag = NAME.match(text, m.start() + 2).group(0).lower()
            idx = next((k for k in range(len(stack) - 1, 0, -1) if stack[k].tag == tag), None)
            if idx is not None:
                for above in stack[idx + 1:]:
                    above.close_start = above.end = m.start(); above.complete = False
                stack[idx].close_start, stack[idx].end = m.start(), gt + 1
                del stack[idx:]
            i = gt + 1
            continue
        nm = NAME.match(text, m.start() + 1)
        tag = nm.group(0).lower()
        e = _scan_tag(text, nm.end())
        if e < 0:
            i = m.end(); continue
        attrs_text = text[nm.end():e]
        if tag in IMPLIED and stack[-1].tag in IMPLIED[tag]:
            top = stack.pop(); top.close_start = top.end = m.start(); top.complete = False
        node = Node(tag, m.start(), e + 1, parse_attrs(attrs_text), stack[-1], line=line(m.start()))
        stack[-1].children.append(node)
        if tag in VOID or attrs_text.rstrip().endswith("/"):
            node.void = True; node.end = e + 1; i = e + 1
        elif tag in RAWTEXT:
            mc = re.compile(r"</" + tag + r"\s*>", re.I).search(text, e + 1)
            if mc:
                node.close_start, node.end = mc.start(), mc.end(); i = mc.end()
            else:
                node.complete = False; node.end = node.close_start = e + 1; i = e + 1
        else:
            stack.append(node); i = e + 1
    for node in stack[1:]:
        node.complete = False; node.end = node.close_start = n
    return root


_CACHE: dict = {}


def parsed(path: Path):
    """(Text, Wurzelknoten) einer Datei; gemerkt, solange sich Größe und Zeitstempel nicht ändern."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1], hit[2]
    text = sm.read(path)
    if text is None:
        return None
    if len(_CACHE) > 400:
        _CACHE.clear()
    _CACHE[path] = (key, text, parse(text))
    return text, _CACHE[path][2]


def walk(node: Node):
    for c in node.children:
        yield c
        yield from walk(c)


# --- Zuordnung -----------------------------------------------------------------------------------------------------------
def static_classes(value: str | None) -> tuple:
    """(feste Klassen, enthält Dynamisches) eines class-Attributs."""
    if value is None:
        return [], False
    plain = DYNAMIC.sub(" ", COND.sub(" ", value))
    toks = [t for t in plain.split() if not re.search(r"[$?{}@]", t)]
    return toks, plain != value or len(toks) != len(plain.split())


def own_text(text: str, node: Node) -> tuple:
    """(fester Text direkt im Element ohne Unterelemente, enthält Dynamisches)."""
    if node.void or node.close_start is None or not node.complete:
        return "", False
    parts, pos = [], node.open_end
    for c in node.children:
        parts.append(text[pos:c.start]); pos = c.end or c.start
    parts.append(text[pos:node.close_start])
    raw = " ".join(parts)
    plain = DYNAMIC.sub(" ", raw)
    return _html.unescape(re.sub(r"\s+", " ", plain)).strip(), plain != raw or bool(re.search(r"@\w+", raw))


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def score(node: Node, text: str, info: dict):
    """Wie gut passt der Quelltext-Knoten zum Element der Seite? None = passt nicht."""
    if node.tag != info.get("tag"):
        return None
    s = 5
    dom_classes, stable = set(info.get("classes") or []), set(info.get("stableClasses") or info.get("classes") or [])
    ident, nid = info.get("id", ""), node.attr.get("id")
    if ident and nid is not None and not re.search(r"[${@]", nid):
        if nid != ident:
            return None
        s += 100
    cls, dyn = static_classes(node.attr.get("class", node.attr.get("className")))
    if not set(cls) <= dom_classes:
        return None                                           # im Quelltext steht eine Klasse, die das Element der Seite nicht hat
    hit = set(cls) & stable
    s += 12 * len(hit)
    if not dyn:
        s -= 6 * len(stable - set(cls))
        if stable and not hit:
            s -= 20
    dom_attrs = info.get("attrs") or {}
    for a in ("href", "src", "name", "type", "for", "action", "placeholder"):
        v, dv = node.attr.get(a), dom_attrs.get(a)
        if v is None or dv is None or re.search(r"[${@]", v):
            continue
        s += 6 if v == dv else -15
    txt, tdyn = own_text(text, node)
    want = _norm(info.get("text", ""))
    if want and txt and not tdyn:
        s += 30 if txt == want else -25
    elif want and tdyn:
        s += 3
    anc = node.parent
    for c in info.get("chain") or []:
        while anc is not None and anc.tag != "#root" and anc.tag != c.get("tag"):
            anc = anc.parent
        if anc is None or anc.tag == "#root":
            break
        s += 6
        a_cls, _ = static_classes(anc.attr.get("class", anc.attr.get("className")))
        if (c.get("id") and anc.attr.get("id") == c["id"]) or (a_cls and set(a_cls) <= set(c.get("classes") or [])):
            s += 4
        anc = anc.parent
    return s


@dataclass
class Match:
    file: Path
    node: Node
    score: int
    text: str
    kind: str = "struktur"

    @property
    def line(self) -> int:
        return self.node.line

    @property
    def pos(self) -> int:
        return self.node.start

    @property
    def snippet(self) -> str:
        return sm.snippet_at(self.text, self.node.start)

    def label(self, root: Path) -> str:
        try:
            rel = self.file.relative_to(root)
        except ValueError:
            rel = self.file
        return f"{rel}:{self.line}  [{self.score}]  {self.snippet}"


def locate(root: Path, info: dict, limit=6, minimum=15) -> list:
    """Stellen im Projekt, an denen das Element der Seite stehen kann – beste zuerst."""
    found = []
    for f in sm.project_files(Path(root), sm.MARKUP_EXT):
        p = parsed(f)
        if not p:
            continue
        text, tree = p
        for node in walk(tree):
            sc = score(node, text, info)
            if sc is not None and sc >= minimum:
                found.append(Match(f, node, sc, text))
    found.sort(key=lambda m: (-m.score, str(m.file), m.line))
    return found[:limit]


# --- Änderungen am Aufbau -------------------------------------------------------------------------------------------
def indent_of(text: str, pos: int) -> str:
    ls = text.rfind("\n", 0, pos) + 1
    return re.match(r"[ \t]*", text[ls:]).group(0)


def detect_unit(text: str) -> str:
    if re.search(r"^\t", text, re.M):
        return "\t"
    widths = sorted({len(m.group(1)) for m in re.finditer(r"^( +)\S", text, re.M) if len(m.group(1)) <= 8})
    return " " * (widths[0] if widths and widths[0] in (2, 4) else 4)


def block(snippet: str, indent: str, unit: str) -> str:
    """Mehrzeilige Vorlage (zwei Leerzeichen je Ebene) auf Einrückung und Einheit der Datei bringen."""
    out = []
    for ln in snippet.split("\n"):
        depth = (len(ln) - len(ln.lstrip(" "))) // 2
        out.append(indent + unit * depth + ln.lstrip(" "))
    return "\n".join(out)


def _oneline(snippet: str) -> str:
    return "".join(l.strip() for l in snippet.split("\n"))


def _alone(text: str, start: int, end: int):
    """(Zeilenanfang, Anfang der Folgezeile), wenn das Stück als Einziges auf seinen Zeilen steht."""
    ls = text.rfind("\n", 0, start) + 1
    eol = text.find("\n", end)
    eol = len(text) if eol < 0 else eol
    if text[ls:start].strip() == "" and text[end:eol].strip() == "":
        return ls, min(len(text), eol + 1)
    return None


def _plan(m: Match, root: Path, label: str, new: str) -> Plan:
    rel = m.file.relative_to(root) if root in m.file.parents else m.file.name
    return Plan("struktur", f"{label}  ({rel}:{m.line})", m.file, m.text, new)


def insert_plan(m: Match, root: Path, snippet: str, where: str, label="Einfügen") -> Plan | None:
    """snippet vor, nach oder in das Element (am Ende) schreiben."""
    t, n = m.text, m.node
    if n.end is None or not n.complete and where != "before":
        return None
    unit, ind = detect_unit(t), indent_of(t, n.start)
    jsx = m.file.suffix.lower() in (".jsx", ".tsx", ".js", ".ts")
    if jsx:
        snippet = re.sub(r"\bclass=", "className=", snippet)
    if where == "inside":
        if n.void or n.close_start is None:
            return None
        cl = t.rfind("\n", 0, n.close_start) + 1
        if cl > n.open_end and t[cl:n.close_start].strip() == "":
            new = t[:cl] + block(snippet, ind + unit, unit) + "\n" + t[cl:]
        else:
            new = t[:n.close_start] + _oneline(snippet) + t[n.close_start:]
    else:
        al = _alone(t, n.start, n.end)
        if where == "before":
            new = (t[:al[0]] + block(snippet, ind, unit) + "\n" + t[al[0]:]) if al else t[:n.start] + _oneline(snippet) + t[n.start:]
        else:
            if al:
                pre = "" if al[1] == 0 or t[al[1] - 1] == "\n" else "\n"
                new = t[:al[1]] + pre + block(snippet, ind, unit) + "\n" + t[al[1]:]
            else:
                new = t[:n.end] + _oneline(snippet) + t[n.end:]
    return _plan(m, root, f"{label} ({ {'before': 'vor', 'after': 'nach', 'inside': 'in'}[where] } dem Element)", new)


def delete_plan(m: Match, root: Path) -> Plan | None:
    t, n = m.text, m.node
    if n.end is None or not n.complete:
        return None
    al = _alone(t, n.start, n.end)
    return _plan(m, root, "Element löschen", (t[:al[0]] + t[al[1]:]) if al else t[:n.start] + t[n.end:])


def duplicate_plan(m: Match, root: Path) -> Plan | None:
    t, n = m.text, m.node
    if n.end is None or not n.complete:
        return None
    src, al = t[n.start:n.end], _alone(t, n.start, n.end)
    if al:
        pre = "" if al[1] == 0 or t[al[1] - 1] == "\n" else "\n"
        new = t[:al[1]] + pre + indent_of(t, n.start) + src + "\n" + t[al[1]:]
    else:
        new = t[:n.end] + src + t[n.end:]
    return _plan(m, root, "Element duplizieren", new)


def move_plan(m: Match, root: Path, direction: str) -> Plan | None:
    """„up“/„down“: mit dem vorherigen/nächsten Geschwister-Element tauschen."""
    n = m.node
    sibs = n.parent.children if n.parent else []
    if n not in sibs or n.end is None or not n.complete:
        return None
    i = sibs.index(n)
    j = i - 1 if direction == "up" else i + 1
    if j < 0 or j >= len(sibs) or sibs[j].end is None or not sibs[j].complete:
        return None
    a, b = (sibs[j], n) if direction == "up" else (n, sibs[j])
    t = m.text
    new = t[:a.start] + t[b.start:b.end] + t[a.end:b.start] + t[a.start:a.end] + t[b.end:]
    return _plan(m, root, "Element nach oben" if direction == "up" else "Element nach unten", new)
