"""Erzeugt aus dem Formularmodell den Python-(PySide6-)Code und verwaltet Handler-Stubs."""
import json
import re
from pathlib import Path

from .controls import BY_TYPE, COLOR_KEYS, Raw, calls, prop_keys, style_for

HEADER = "# Automatisch von Visual Death Studio erzeugt – Änderungen gehen beim nächsten Speichern des Designers verloren.\n"


def new_form(name="Form1"):
    return {"name": name, "title": name, "width": 480, "height": 320, "controls": []}


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
    names = {"QWidget"}
    for c in model["controls"]:
        spec = BY_TYPE[c["type"]]
        names.add(spec.qt.__name__)
        names.update(spec.imports)
        if c["type"] == "Line":
            names.add("QFrame")
        if any(k in c["props"] for k in ("password",)):
            names.add("QLineEdit")
    from PySide6 import QtWidgets
    names.discard("QWidget")
    items = sorted(n for n in names if hasattr(QtWidgets, n))      # Klassen aus QtGui (z. B. QPixmap) sind bereits importiert
    if not items:
        return ""
    lines, cur = [], ""
    for n in items:
        piece = n + ", "
        if len(cur) + len(piece) > 100:
            lines.append(cur.rstrip()); cur = ""
        cur += piece
    lines.append(cur.rstrip().rstrip(","))
    return "from PySide6.QtWidgets import (" + ("\n" + " " * 31).join(lines) + ")\n"


def designer_source(model: dict, cls: str) -> str:
    L = [HEADER, "from PySide6.QtCore import Qt\nfrom PySide6.QtGui import QColor, QFont, QPalette, QPixmap\n",
         widget_imports(model), "\n\n",
         f"class Ui_{cls}:\n", "    def setup_ui(self, root):\n",
         f"        root.setObjectName({cls!r})\n", f"        root.setWindowTitle({model['title']!r})\n",
         f"        root.resize({model['width']}, {model['height']})\n"]
    L += font_lines("root", model)
    if model.get("back_color"):
        L.append(f"        _p = root.palette(); _p.setColor(QPalette.Window, QColor({model['back_color']!r})); root.setPalette(_p); root.setAutoFillBackground(True)\n")
    for c in model["controls"]:
        spec, v = BY_TYPE[c["type"]], f"self.{c['name']}"
        L.append(f"\n        {v} = {spec.qt.__name__}(root)\n")
        L.append(f"        {v}.setObjectName({c['name']!r})\n")
        if c["type"] == "Panel":
            L.append(f"        {v}.setFrameShape(QFrame.StyledPanel)\n")
        L.append(f"        {v}.setGeometry({c['x']}, {c['y']}, {c['w']}, {c['h']})\n")
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
    return "".join(L)


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
