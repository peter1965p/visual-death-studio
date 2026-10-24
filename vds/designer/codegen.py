"""Erzeugt aus dem Formularmodell den Python-(PySide6-)Code und verwaltet Handler-Stubs."""
import json
import re
from pathlib import Path

from . import layouts
from .controls import BY_TYPE, COLOR_KEYS, Raw, calls, component_lines, prop_keys, style_for
from .layouts import CONTAINERS

HEADER = "# Automatisch von Visual Death Studio erzeugt – Änderungen gehen beim nächsten Speichern des Designers verloren.\n"


def new_form(name="Form1"):
    return {"name": name, "title": name, "width": 480, "height": 320, "controls": [], "components": []}


def class_name(stem: str) -> str:
    n = re.sub(r"\W", "_", stem)
    return n if n and not n[0].isdigit() else "_" + n


def _arg(a):
    return a.code if isinstance(a, Raw) else repr(a)


def font_lines(var: str, props: dict) -> list:
    """Python-Code für die Font-Eigenschaft (neu: Dict; alt: nur Schriftgröße)."""
    f = props.get("font")
    if isinstance(f, dict) and f:
        return [f"        _f = QFont({f.get('family', '')!r}); _f.setPointSize({int(f.get('size', 10))}); _f.setWeight(QFont.Weight({int(f.get('weight', 400))})); "
                f"_f.setItalic({bool(f.get('italic'))}); _f.setUnderline({bool(f.get('underline'))}); _f.setStrikeOut({bool(f.get('strike'))}); {var}.setFont(_f)\n"]
    if props.get("font_size"):
        return [f"        _f = {var}.font(); _f.setPointSize({int(props['font_size'])}); {var}.setFont(_f)\n"]
    return []


def widget_imports(model: dict) -> str:
    """`from PySide6.QtWidgets import (...)` nur mit den Klassen, die das Formular wirklich benutzt (mehrzeilig, sortiert)."""
    names = set()
    for c in model["controls"]:
        spec = BY_TYPE[c["type"]]
        names.add(spec.qt.__name__)
        names.update(spec.imports)
        if c["type"] == "Line":
            names.add("QFrame")
        if c["type"] == "TabWidget":
            names.add("QWidget")
        if any(k in c["props"] for k in ("password",)):
            names.add("QLineEdit")
    for c in model.get("components", []):
        spec = BY_TYPE[c["type"]]
        names.add(spec.qt.__name__); names.update(spec.imports)
    for src in [model] + [c["props"] for c in model["controls"] if c["type"] in CONTAINERS]:
        mode = layouts.cfg(src)[0]
        if mode != "Keine":
            names.add(layouts.LAYOUT_CLASS[mode])
    from PySide6 import QtPrintSupport, QtWidgets
    out = ""
    for mod, label in ((QtWidgets, "QtWidgets"), (QtPrintSupport, "QtPrintSupport")):      # QtGui-Klassen (z. B. QPixmap) sind bereits importiert
        items = sorted(n for n in names if hasattr(mod, n) and (mod is QtPrintSupport or not hasattr(QtPrintSupport, n)))
        if not items:
            continue
        lines, cur = [], ""
        for n in items:
            piece = n + ", "
            if len(cur) + len(piece) > 100:
                lines.append(cur.rstrip()); cur = ""
            cur += piece
        lines.append(cur.rstrip().rstrip(","))
        out += f"from PySide6.{label} import (" + ("\n" + " " * (len(label) + 20)).join(lines) + ")\n"
    return out


def _layout_lines(holder: str, src: dict, kids: list) -> list:
    """Layout für eine Fläche (Formular, Container, Tab-Seite) samt addWidget-Aufrufen in Positionsreihenfolge."""
    mode, spacing, margin, cols = layouts.cfg(src)
    if mode == "Keine" or not kids:
        return []
    L = [f"        _l = {layouts.LAYOUT_CLASS[mode]}({holder})\n", f"        _l.setSpacing({spacing})\n",
         f"        _l.setContentsMargins({margin}, {margin}, {margin}, {margin})\n"]
    for n, c in enumerate(layouts.ordered(kids, mode)):
        L.append(f"        _l.addWidget(self.{c['name']}, {n // cols}, {n % cols})\n" if mode == "Raster" else f"        _l.addWidget(self.{c['name']})\n")
    return L


def _emit_control(L: list, model: dict, c: dict, parent_var: str, in_layout: bool):
    spec, v = BY_TYPE[c["type"]], f"self.{c['name']}"
    L.append(f"\n        {v} = {spec.qt.__name__}({parent_var})\n")
    L.append(f"        {v}.setObjectName({c['name']!r})\n")
    if c["type"] == "Panel":
        L.append(f"        {v}.setFrameShape(QFrame.StyledPanel)\n")
    L.append(f"        {v}.setMinimumSize({c['w']}, {c['h']})\n" if in_layout else f"        {v}.setGeometry({c['x']}, {c['y']}, {c['w']}, {c['h']})\n")
    if c["type"] == "TabWidget":
        for i, title in enumerate(layouts.tab_titles(c["props"])):
            L.append(f"        {v}_page{i} = QWidget()\n        {v}.addTab({v}_page{i}, {title!r})\n")
    order = ["minimum", "maximum", "value"]
    keys = [k for k in prop_keys(spec) if k not in order] + [k for k in order if k in prop_keys(spec)]
    for k in keys:
        if k not in c["props"] or k in COLOR_KEYS or k in ("font", "font_size"):
            continue
        for m, args in calls(c["type"], k, c["props"][k]):
            if m == "@font":
                L.append(f"        _f = {v}.font(); _f.setPointSize({args[0]}); {v}.setFont(_f)\n")
            else:
                L.append(f"        {v}.{m}({', '.join(_arg(a) for a in args)})\n")
    L += font_lines(v, c["props"])
    style = style_for(c["type"], c["props"])
    if style:
        L.append(f"        {v}.setStyleSheet({style!r})\n")
    if spec.event:
        sig, suffix, _ = spec.event
        h = f"{c['name']}_{suffix}"
        L.append(f"        if hasattr(root, {h!r}):\n            {v}.{sig}.connect(root.{h})\n")


def _emit_level(L: list, model: dict, parent: dict | None, root_var: str):
    """Erzeugt alle Kinder von `parent` (None = Formular) rekursiv: Container zuerst, dann ihr Inhalt, dann deren Layout."""
    key = parent["name"] if parent else None
    src = parent["props"] if parent else model
    pages = layouts.tab_titles(parent["props"]) if parent and parent["type"] == "TabWidget" else [None]
    for tab, _ in enumerate(pages):
        kids = layouts.children(model, key, tab if parent and parent["type"] == "TabWidget" else None)
        holder = root_var if parent is None else (f"self.{key}_page{tab}" if pages[0] is not None else f"self.{key}")
        in_layout = layouts.cfg(src)[0] != "Keine"
        for c in kids:
            _emit_control(L, model, c, holder, in_layout)
            if c["type"] in CONTAINERS:
                _emit_level(L, model, c, root_var)
        if kids:
            L.append("\n")
        L += _layout_lines(holder, src, kids)


def designer_source(model: dict, cls: str) -> str:
    layouts.normalize(model)
    L = [HEADER, "from PySide6.QtCore import Qt\nfrom PySide6.QtGui import QColor, QFont, QPalette, QPixmap\n",
         widget_imports(model), "\n\n",
         f"class Ui_{cls}:\n", "    def setup_ui(self, root):\n",
         f"        root.setObjectName({cls!r})\n", f"        root.setWindowTitle({model['title']!r})\n",
         f"        root.resize({model['width']}, {model['height']})\n"]
    L += font_lines("root", model)
    if model.get("back_color"):
        L.append(f"        _p = root.palette(); _p.setColor(QPalette.Window, QColor({model['back_color']!r})); root.setPalette(_p); root.setAutoFillBackground(True)\n")
    _emit_level(L, model, None, "root")
    comps = model.get("components", [])
    if comps:
        L.append("\n        # --- Komponenten (nicht sichtbar): mit exec() anzeigen\n")
        for c in comps:
            L += ["        " + line + "\n" for line in component_lines(c)] + ["\n"]
    return "".join(L).rstrip("\n") + "\n"


def user_source(stem: str, cls: str) -> str:
    return f'''import sys

from PySide6.QtWidgets import QApplication, QWidget

from {stem}_designer import Ui_{cls}


class {cls}(QWidget, Ui_{cls}):
    def __init__(self):
        super().__init__()
        self.setup_ui(self)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = {cls}()
    window.show()
    sys.exit(app.exec())
'''


def write_files(form_path: Path, model: dict) -> Path:
    """Schreibt <Name>_designer.py (immer neu) und <Name>.py (nur wenn nicht vorhanden). Gibt die Benutzerdatei zurück."""
    stem = form_path.name[: -len(".form.json")]
    cls = class_name(stem)
    form_path.write_text(json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    (form_path.parent / f"{stem}_designer.py").write_text(designer_source(model, cls), encoding="utf-8")
    user = form_path.parent / f"{stem}.py"
    if not user.exists():
        user.write_text(user_source(stem, cls), encoding="utf-8")
    return user


def add_handler(user_file: Path, handler: str, args: list) -> int:
    """Fügt einen Handler-Stub in die Formularklasse ein, falls er fehlt. Gibt die Zeilennummer (1-basiert) zurück."""
    pattern = re.compile(rf"^[ \t]+def {re.escape(handler)}\(", re.M)
    text = user_file.read_text(encoding="utf-8")
    if not pattern.search(text):
        stub = f"\n    def {handler}({', '.join(['self'] + args)}):\n        pass\n"
        marker = re.search(r"\n\nif __name__ ==", text)
        if marker:
            text = text[: marker.start()].rstrip("\n") + "\n" + stub + text[marker.start():]
        else:
            text = text.rstrip("\n") + "\n" + stub
        user_file.write_text(text, encoding="utf-8")
    return text[: pattern.search(text).start()].count("\n") + 1
