"""Schreibt visuelle Änderungen (Stile, Text) zurück in den Quellcode: bestehende CSS-Regel, Tailwind-Klassen, Inline-Style oder neue Regel.
Jede Möglichkeit ist ein `Plan` mit alter und neuer Dateifassung – der Nutzer sieht den Unterschied, bevor etwas geschrieben wird."""
import base64
import difflib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import source_map as sm

STYLE_BLOCK = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.S | re.I)
UNITLESS = {"opacity", "z-index", "font-weight", "line-height", "flex", "order"}
CSS_FILES = ("src/index.css", "src/App.css", "src/style.css", "src/styles.css", "src/assets/main.css", "src/assets/css/main.css", "assets/css/main.css",
             "app/globals.css", "styles/globals.css", "public/css/style.css", "public/style.css", "css/style.css", "style.css", "styles.css",
             "public/css/app.css", "resources/css/app.css")


@dataclass
class Plan:
    kind: str          # css-regel | tailwind | inline | neue-regel | text
    label: str
    file: Path
    old: str
    new: str
    shared: int = 0    # >1: die Regel gilt für so viele Elemente der Seite
    run: tuple | None = None   # kein Dateiplan, sondern eine Aktion: ("setting", Projektordner, Schlüssel, alter Text, neuer Text)

    def diff(self, root: Path | None = None) -> str:
        if self.run:
            return f"Datenbank-Einstellung „{self.run[2]}“\n- {self.run[3]}\n+ {self.run[4]}\n"
        name = str(self.file.relative_to(root)) if root and root in self.file.parents else self.file.name
        return "".join(difflib.unified_diff(self.old.splitlines(True), self.new.splitlines(True), "a/" + name, "b/" + name, n=2))


def kebab(prop: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), prop).lower()


def camel(prop: str) -> str:
    return re.sub(r"-([a-z])", lambda m: m.group(1).upper(), prop)


# --- CSS lesen/ändern ------------------------------------------------------------------------------------
@dataclass
class Rule:
    selector: str
    start: int           # Anfang des Inhalts (nach "{")
    end: int             # Position der schließenden "}"
    depth: int
    in_media: bool
    line: int


def iter_rules(css: str, base=0, full: str | None = None):
    """Regeln auf oberster Ebene und in @media/@supports (Verschachteltes wie SCSS-Unterregeln wird übersprungen)."""
    full = full if full is not None else css
    stack, i, n, sel_start = [], 0, len(css), 0
    while i < n:
        c = css[i]
        if css.startswith("/*", i):
            j = css.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        if c in "\"'":
            j = i + 1
            while j < n and css[j] != c:
                j += 2 if css[j] == "\\" else 1
            i = j + 1; continue
        if c == "{":
            sel = css[sel_start:i].strip()
            stack.append((sel, i + 1))
            sel_start = i + 1
        elif c == "}" and stack:
            sel, start = stack.pop()
            at = sel.startswith("@")
            parents = [s for s, _ in stack]
            if not at and all(p.startswith(("@media", "@supports", "@layer")) for p in parents) and not sel.startswith("@"):
                yield Rule(sel, base + start, base + i, len(stack), bool(parents), line_of_pos(full, base + start))
            sel_start = i + 1
        elif c == ";" and not stack:
            sel_start = i + 1
        i += 1


def line_of_pos(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def css_regions(path: Path, text: str):
    """[(Basisoffset, CSS-Text)]: ganze Datei bei .css/.scss/.less, sonst die <style>-Blöcke."""
    if path.suffix.lower() in sm.STYLE_EXT:
        return [(0, text)]
    return [(m.start(2), m.group(2)) for m in STYLE_BLOCK.finditer(text)]


def split_decls(body: str):
    """Deklarationen des Regelinhalts auf oberster Ebene: [(start, end, name, value)] (end ohne Semikolon)."""
    out, depth, start, i, n, quote = [], 0, 0, 0, len(body), None
    while i <= n:
        c = body[i] if i < n else ";"
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "({":
            depth += 1
        elif c in ")}":
            depth -= 1
        elif c == ";" and depth == 0:
            seg = body[start:i]
            m = re.match(r"\s*([\w-]+)\s*:\s*(.*?)\s*$", seg, re.S)
            if m and "{" not in seg:
                out.append((start, i, m.group(1).lower(), m.group(2)))
            start = i + 1
        i += 1
    return out


def set_decls(body: str, props: dict, indent: str = "  ") -> str:
    """Neue Fassung des Regelinhalts: vorhandene Eigenschaften ersetzen (!important bleibt), neue anhängen."""
    decls = split_decls(body)
    todo = {kebab(k): v for k, v in props.items()}
    for start, end, name, value in reversed(decls):
        if name in todo:
            imp = " !important" if re.search(r"!\s*important\s*$", value, re.I) else ""
            seg = body[start:end]
            lead = seg[:len(seg) - len(seg.lstrip())]
            body = body[:start] + f"{lead}{name}: {todo.pop(name)}{imp}" + body[end:]
    if todo and "\n" not in body.strip() and body.strip():          # einzeilige Regel bleibt einzeilig
        stripped = body.rstrip()
        if not stripped.endswith(";"):
            stripped += ";"
        return stripped + "".join(f" {k}: {v};" for k, v in todo.items()) + " "
    if todo:
        m = re.search(r"\n([ \t]+)\S", body)
        ind = m.group(1) if m else indent
        add = "".join(f"\n{ind}{k}: {v};" for k, v in todo.items())
        stripped = body.rstrip()
        trail = body[len(stripped):]
        if stripped and not stripped.endswith((";", "{")):
            stripped += ";"
        body = stripped + add + (trail if "\n" in trail else "\n")
    return body


def rule_matches(selector: str, ident: str, classes: list) -> int:
    """Wie gut passt ein Selektor (Liste per Komma) auf das Element? 0 = gar nicht; nur einfache Selektoren ohne Kombinatoren/Pseudos."""
    best = 0
    for s in (x.strip() for x in selector.split(",")):
        if not s or re.search(r"[\s>+~:\[\]*()]", s):
            continue
        m = re.fullmatch(r"([a-zA-Z][\w-]*)?((?:\.[\w-]+)*)(#[\w-]+)?", s)
        if not m or not (m.group(2) or m.group(3)):
            continue
        rc = [c for c in m.group(2).split(".") if c]
        rid = m.group(3)[1:] if m.group(3) else ""
        if rid and rid != ident:
            continue
        if any(c not in classes for c in rc):
            continue
        best = max(best, (100 if rid else 0) + 10 * len(rc))
    return best


def sheet_files(root: Path, sheets: list | None) -> list:
    """Stylesheets, die die Seite wirklich lädt (URL-Pfade aus dem Browser), als Dateien im Projekt – z. B. /css/app.css → public/css/app.css."""
    root, out = Path(root).resolve(), []
    for url in sheets or []:
        rel = url.split("?")[0].lstrip("/")
        for base in ("public", "", "static", "web", "wwwroot"):
            f = (root / base / rel).resolve()
            try:
                parts = f.relative_to(root).parts
            except ValueError:
                continue
            if rel and f.is_file() and f.suffix.lower() in sm.STYLE_EXT and not any(x in sm.SKIP_DIRS for x in parts) and f not in out:
                out.append(f); break
    return out


def rule_reach(selector: str, ident: str, classes: list, counts: dict) -> int:
    """Für wie viele Elemente der Seite gilt die Regel höchstens? (Obergrenze aus den Klassenzahlen; 1 = nur dieses Element)"""
    best = 1
    for s in (x.strip() for x in selector.split(",")):
        if rule_matches(s, ident, classes) and "#" not in s:
            rc = [c for c in s.split("#")[0].split(".")[1:] if c]
            if rc:
                best = max(best, min(counts.get(c, 1) for c in rc))
    return best


def css_plans(root: Path, info: dict, props: dict) -> list:
    ident, classes, counts = info.get("id", ""), info.get("classes", []), info.get("classCounts") or {}
    plans = []
    loaded = sheet_files(root, info.get("sheets"))
    files = sm.project_files(root, sm.STYLE_EXT | {".vue", ".svelte", ".html", ".htm", ".php", ".astro"})
    for f in sorted(files, key=lambda f: f.resolve() not in loaded):                     # geladene Stylesheets zuerst

        text = sm.read(f)
        if text is None or (f.suffix.lower() not in sm.STYLE_EXT and "<style" not in text.lower()):
            continue
        for base, region in css_regions(f, text):
            scored = [(rule_matches(r.selector, ident, classes), r) for r in iter_rules(region, base, text)]
            scored = [(s, r) for s, r in scored if s]
            if not scored:
                continue
            top = max(s for s, _ in scored)
            for s, r in scored:
                if s != top or r.in_media:
                    continue
                new_body = set_decls(text[r.start:r.end], props)
                new = text[:r.start] + new_body + text[r.end:]
                reach = rule_reach(r.selector, ident, classes, counts)
                note = f"  ⚠ gilt für {reach} Elemente der Seite" if reach > 1 else ""
                plans.append(Plan("css-regel", f"Regel „{r.selector}“ ändern  ({f.relative_to(root)}:{r.line}){note}", f, text, new, reach if reach > 1 else 0))
    return plans


def unique_selector(info: dict) -> str:
    """Klassen-Selektor nur für dieses Element: die seltenste Klasse, sonst alle zusammen (z. B. .btn.btn-primary.btn-lg statt .btn)."""
    cls, counts = info.get("stableClasses") or [], info.get("classCounts") or {}
    if not cls:
        return ""
    rare = min(cls, key=lambda c: counts.get(c, 1))
    return "." + rare if counts.get(rare, 1) <= 1 else "".join("." + c for c in cls)


def new_rule_plan(root: Path, info: dict, props: dict) -> Plan | None:
    sel = f"#{info['id']}" if info.get("id") else unique_selector(info)
    if not sel:
        return None
    body = "".join(f"\n  {kebab(k)}: {v};" for k, v in props.items())
    block = f"\n{sel} {{{body}\n}}\n"
    for f in sheet_files(root, info.get("sheets")):                                   # in das Stylesheet, das die Seite lädt
        text = sm.read(f)
        if text is not None:
            rel = f.relative_to(Path(root).resolve())
            return Plan("neue-regel", f"Neue Regel „{sel}“ am Ende von {rel}", f, text, text.rstrip("\n") + "\n" + block)
    for rel in CSS_FILES:
        f = root / rel
        text = sm.read(f) if f.exists() else None
        if text is not None:
            return Plan("neue-regel", f"Neue Regel „{sel}“ am Ende von {rel}", f, text, text.rstrip("\n") + "\n" + block)
    for f in sm.project_files(root, {".vue", ".svelte"}):             # Komponenten mit eigenem <style>
        text = sm.read(f)
        m = list(STYLE_BLOCK.finditer(text or ""))
        if m:
            end = m[-1].start(3)
            return Plan("neue-regel", f"Neue Regel „{sel}“ im <style> von {f.relative_to(root)}", f, text, text[:end].rstrip("\n") + "\n" + block + text[end:])
    return None


# --- Tag-Suche und Inline-Style -----------------------------------------------------------------------------------
def tag_end(text: str, lt: int) -> int | None:
    """Ende (exklusiv) des öffnenden Tags, das bei `lt` ('<') beginnt; berücksichtigt Anführungszeichen, {…}, <?php …?>."""
    i, n, depth = lt + 1, len(text), 0
    while i < n:
        c = text[i]
        if text.startswith("<?", i):
            j = text.find("?>", i); i = n if j < 0 else j + 2; continue
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth <= 0:
            return i + 1
        elif c == "<" and depth <= 0 and i > lt + 1:
            return None
        i += 1
    return None


def find_tag(text: str, pos: int) -> tuple | None:
    lt = pos
    for _ in range(12):
        lt = text.rfind("<", 0, lt)
        if lt < 0:
            return None
        if lt + 1 < len(text) and (text[lt + 1].isalpha()):
            end = tag_end(text, lt)
            if end and lt < pos < end:
                return lt, end
    return None


def jsx_value(prop: str, val: str) -> str:
    if prop in UNITLESS and re.fullmatch(r"-?\d+(\.\d+)?", val):
        return val
    return json.dumps(val, ensure_ascii=False)


def inline_edit_tag(tag: str, props: dict, jsx: bool) -> str | None:
    """Neue Fassung des öffnenden Tags mit gesetzten Stilen; None, wenn der vorhandene style nicht änderbar ist (z. B. style={variable})."""
    if jsx:
        m = re.search(r"\bstyle\s*=\s*\{\{", tag)
        if m:
            i, depth = m.end(), 2
            j = i
            while j < len(tag) and depth > 0:
                depth += {"{": 1, "}": -1}.get(tag[j], 0); j += 1
            inner = tag[m.end():j - 2]
            entries = [e.strip() for e in re.split(r",(?![^()]*\))(?=(?:[^\"']*[\"'][^\"']*[\"'])*[^\"']*$)", inner) if e.strip()]
            todo = {camel(k): v for k, v in props.items()}
            out = []
            for e in entries:
                km = re.match(r"""["']?([\w-]+)["']?\s*:""", e)
                key = camel(km.group(1)) if km else None
                if key in todo:
                    out.append(f"{key}: {jsx_value(kebab(key), todo.pop(key))}")
                else:
                    out.append(e)
            out += [f"{k}: {jsx_value(kebab(k), v)}" for k, v in todo.items()]
            return tag[:m.start()] + "style={{ " + ", ".join(out) + " }}" + tag[j:]
        if re.search(r"\bstyle\s*=\s*\{", tag):
            return None
        add = " style={{ " + ", ".join(f"{camel(k)}: {jsx_value(k, v)}" for k, v in props.items()) + " }}"
    else:
        m = re.search(r"""(?<![\w:.-])style\s*=\s*(["'])(.*?)\1""", tag, re.S)
        if m:
            decls = split_decls(m.group(2) + ";")
            body = set_decls(m.group(2), props, indent="")
            body = re.sub(r"\n\s*", " ", body).strip().rstrip(";").strip()
            return tag[:m.start()] + f"style={m.group(1)}{body}{m.group(1)}" + tag[m.end():]
        add = ' style="' + "; ".join(f"{kebab(k)}: {v}" for k, v in props.items()) + '"'
    cut = len(tag) - 2 if tag.endswith("/>") else len(tag) - 1
    head = tag[:cut].rstrip()
    return head + add + (" />" if tag.endswith("/>") else ">")


def inline_plan(root: Path, cand, props: dict) -> Plan | None:
    text = sm.read(cand.file)
    if text is None:
        return None
    t = find_tag(text, cand.pos)
    if not t:
        return None
    tag = text[t[0]:t[1]]
    jsx = cand.file.suffix.lower() in (".tsx", ".jsx", ".js", ".ts", ".mdx") or "className=" in tag
    new_tag = inline_edit_tag(tag, props, jsx)
    if new_tag is None:
        return None
    return Plan("inline", f"Inline-Style im Element ändern  ({cand.file.relative_to(root)}:{cand.line})", cand.file, text, text[:t[0]] + new_tag + text[t[1]:])


# --- Tailwind ----------------------------------------------------------------------------------------------------------
def uses_tailwind(root: Path) -> bool:
    try:
        pkg = (root / "package.json").read_text(encoding="utf-8")
        if "tailwindcss" in pkg:
            return True
    except OSError:
        pass
    return any((root / n).exists() for n in ("tailwind.config.js", "tailwind.config.ts", "tailwind.config.cjs", "tailwind.config.mjs"))


def hexcolor(v: str) -> str | None:
    v = v.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", v):
        return v.lower()
    m = re.fullmatch(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+%?))?\s*\)", v)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


COLOR_WORDS = r"(?:inherit|current|transparent|black|white|[a-z]+-\d{2,3}|\[[^\]]*\])"


def tw_token(prop: str, value: str):
    """(neues Token, Regex der zu ersetzenden alten Tokens) oder None, wenn sich die Eigenschaft nicht als Tailwind-Klasse ausdrücken lässt."""
    v = value.strip()
    px = re.fullmatch(r"-?\d+(\.\d+)?(px|rem|em|%)?", v)
    arb = v.replace(" ", "_")
    if prop == "color" and hexcolor(v):
        return f"text-[{hexcolor(v)}]", rf"text-{COLOR_WORDS}"
    if prop == "background-color" and hexcolor(v):
        return f"bg-[{hexcolor(v)}]", rf"bg-{COLOR_WORDS}"
    if prop == "font-size" and px:
        return f"text-[{arb}]", r"text-(?:xs|sm|base|lg|\d?xl|\[\d[^\]]*\])"
    if prop in ("width", "height") and px:
        return f"{'w' if prop == 'width' else 'h'}-[{arb}]", rf"{'w' if prop == 'width' else 'h'}-\S+"
    if prop in ("padding", "margin") and px:
        k = "p" if prop == "padding" else "m"
        return f"{k}-[{arb}]", rf"{k}-\S+"
    if prop == "border-radius" and px:
        return f"rounded-[{arb}]", r"rounded(?:-\S+)?"
    if prop == "opacity" and re.fullmatch(r"\d*\.?\d+", v):
        return f"opacity-[{v}]", r"opacity-\S+"
    if prop == "font-weight" and re.fullmatch(r"\d{3}", v):
        return f"font-[{v}]", r"font-(?:thin|extralight|light|normal|medium|semibold|bold|extrabold|black|\[\d+\])"
    if prop == "text-align" and v in ("left", "center", "right", "justify"):
        return f"text-{v}", r"text-(?:left|center|right|justify)"
    return None


def tailwind_plan(root: Path, cand, props: dict) -> Plan | None:
    if not uses_tailwind(root):
        return None
    text = sm.read(cand.file)
    t = find_tag(text, cand.pos) if text else None
    if not t:
        return None
    tag = text[t[0]:t[1]]
    m = re.search(r"""\b(class|className)\s*=\s*(["'])([^"'{}`$]*)\2""", tag)
    if not m:
        return None
    tokens = m.group(3).split()
    for prop, val in props.items():
        r = tw_token(kebab(prop), val)
        if r is None:
            return None
        new, pattern = r
        tokens = [x for x in tokens if not re.fullmatch(pattern, x)] + [new]
    new_tag = tag[:m.start(3)] + " ".join(tokens) + tag[m.end(3):]
    return Plan("tailwind", f"Tailwind-Klassen im Element ändern  ({cand.file.relative_to(root)}:{cand.line})", cand.file, text, text[:t[0]] + new_tag + text[t[1]:])


# --- Text ---------------------------------------------------------------------------------------------------------------
def text_plans(root: Path, old: str, new: str, cands: list) -> list:
    old, plans = old.strip(), []
    if not old or old == new.strip():
        return []
    files = list(dict.fromkeys([c.file for c in cands] + sm.project_files(root, sm.MARKUP_EXT)))
    for f in files:
        text = sm.read(f)
        if not text or text.count(old) != 1:
            continue
        i = text.index(old)
        plans.append(Plan("text", f"Text ändern  ({f.relative_to(root)}:{line_of_pos(text, i)})", f, text, text[:i] + new.strip() + text[i + len(old):]))
        if len(plans) >= 5:
            break
    return plans


# --- Laravel-Einstellungen (Text kommt aus der Datenbank) --------------------------------------------------------------
def _php(root: Path, code: str, timeout=30) -> str | None:
    """Führt PHP-Code mit gestarteter Laravel-Anwendung aus (ohne tinker). Wie der Startbefehl der IDE: .vds/php zusätzlich als ini-Ordner."""
    env = dict(os.environ)
    if (root / ".vds" / "php").is_dir():
        env["PHP_INI_SCAN_DIR"] = f":{root / '.vds' / 'php'}"
    boot = "require 'vendor/autoload.php'; $app = require 'bootstrap/app.php'; $app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap(); "
    try:
        r = subprocess.run(["php", "-r", boot + code], cwd=root, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def has_settings_model(root: Path) -> bool:
    f = Path(root) / "app" / "Models" / "Setting.php"
    text = sm.read(f) if f.is_file() else None
    return bool(text and "function put" in text and "function get" in text and (Path(root) / "artisan").is_file())


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def setting_values(root: Path) -> dict | None:
    """{Schlüssel: aktuell angezeigter Text} für alle Einstellungen (Standardwerte und Datenbank)."""
    out = _php(Path(root), "$k = array_keys(\\App\\Models\\Setting::definitions()); $o = []; foreach ($k as $x) { $o[$x] = \\App\\Models\\Setting::get($x); } echo json_encode($o);")
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def setting_put(root: Path, key: str, value: str | None) -> bool:
    """Wert setzen; None entfernt die Zeile (dann gilt wieder der Standardwert)."""
    arg = base64.b64encode(json.dumps([key, value]).encode()).decode()
    code = (f"[$k, $v] = json_decode(base64_decode('{arg}'), true); "
            "if ($v === null) { \\App\\Models\\Setting::where('key', $k)->delete(); } else { \\App\\Models\\Setting::put($k, $v); } echo 'ok';")
    return _php(Path(root), code) == "ok"


def setting_raw(root: Path, key: str):
    """Wert der Datenbankzeile (None = keine Zeile) für „Rückgängig“; Fehler → False."""
    arg = base64.b64encode(json.dumps(key).encode()).decode()
    out = _php(Path(root), f"$k = json_decode(base64_decode('{arg}')); $r = \\App\\Models\\Setting::where('key', $k)->first(); echo json_encode($r ? $r->value : null);")
    try:
        return json.loads(out) if out else False
    except ValueError:
        return False


def setting_plans(root: Path, old: str, new: str) -> list:
    """Text, der per `Setting::get('schluessel')` aus der Datenbank kommt: den Wert dort ändern, wo er herkommt."""
    root = Path(root).resolve()
    if _norm(old) == _norm(new) or not has_settings_model(root):
        return []
    values = setting_values(root) or {}
    keys = [k for k, v in values.items() if _norm(v) == _norm(old)]
    return [Plan("setting", f"Laravel-Einstellung „{k}“ in der Datenbank ändern", root / "app" / "Models" / "Setting.php", "", "",
                 run=("setting", root, k, values[k], new.strip())) for k in keys[:3]]


# --- Gesamtplan ------------------------------------------------------------------------------------------------------
def plan_style(root: Path, info: dict, props: dict, cands: list | None = None) -> list:
    """Alle Möglichkeiten, die geänderten Eigenschaften eines Elements in den Quellcode zu übernehmen – beste zuerst."""
    root = Path(root).resolve()
    cands = cands if cands is not None else sm.search(root, info)
    props = {k: v for k, v in props.items() if v != ""}
    if not props:
        return []
    plans = []
    best = next((c for c in cands if c.file.suffix.lower() in sm.MARKUP_EXT and c.kind in ("id", "klasse")), None) or next(iter(cands), None)
    if best:
        tw = tailwind_plan(root, best, props)
        tw and plans.append(tw)
    rules = css_plans(root, info, props)
    plans += [p for p in rules if not p.shared]
    if best:
        il = inline_plan(root, best, props)
        il and plans.append(il)
    plans += [p for p in rules if p.shared]                    # gemeinsame Regeln (.btn-lg …) ändern auch andere Elemente: nur als letzte Wahl
    if not any(p.kind == "css-regel" and not p.shared for p in plans):
        nr = new_rule_plan(root, info, props)
        nr and plans.insert(next((i for i, p in enumerate(plans) if p.shared), len(plans)), nr)
    return plans


def region(plan: Plan) -> tuple:
    """Die eine zusammenhängende Änderung eines Plans: (Anfang, Ende im alten Text, Ersatz)."""
    a, b = plan.old, plan.new
    pre = 0
    while pre < min(len(a), len(b)) and a[pre] == b[pre]:
        pre += 1
    suf = 0
    while suf < min(len(a), len(b)) - pre and a[len(a) - 1 - suf] == b[len(b) - 1 - suf]:
        suf += 1
    return pre, len(a) - suf, b[pre:len(b) - suf]


def merge(plans: list) -> tuple:
    """Pläne für dieselbe Datei zu einem zusammenfassen (z. B. Stil und Text im selben Element). -> (Pläne, übersprungene Pläne bei Überlappung)"""
    by_file: dict = {}
    out, skipped = [], []
    for p in plans:
        if p.run:
            out.append(p)
        else:
            by_file.setdefault(p.file, []).append(p)
    for f, ps in by_file.items():
        if len(ps) == 1:
            out.append(ps[0]); continue
        taken, edits = [], []
        for p in ps:
            r = region(p)
            if any(r[0] < e[1] and e[0] < r[1] or (r[0] == e[0] and r[1] == e[1]) for e in edits):
                skipped.append(p); continue
            edits.append(r); taken.append(p)
        text = ps[0].old
        for i1, i2, rep in sorted(edits, reverse=True):
            text = text[:i1] + rep + text[i2:]
        out.append(Plan(taken[0].kind, " + ".join(p.label for p in taken), f, ps[0].old, text))
    return out, skipped


def apply(plans: list) -> dict:
    """Schreibt die Pläne; gibt {Datei: alter Inhalt} für „Rückgängig“ zurück. Mehrere Pläne für dieselbe Datei werden nacheinander angewendet."""
    backup = {}
    for p in plans:
        if p.run:
            _, root, key, _old, new = p.run
            before = setting_raw(root, key)
            if before is not False and setting_put(root, key, new):
                backup[("setting", root, key)] = before
            continue
        backup.setdefault(p.file, p.old)
        p.file.write_text(p.new, encoding="utf-8")
    return backup


def undo(backup: dict):
    for f, old in backup.items():
        if isinstance(f, tuple):
            setting_put(f[1], f[2], old)
        else:
            f.write_text(old, encoding="utf-8")
