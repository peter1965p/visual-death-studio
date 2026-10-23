"""Control-Katalog des Formular-Designers: Typen, Standardwerte, Eigenschaften, Events.
Eine Stelle beschreibt, wie ein Control live (Qt-Widget) und im erzeugten Python-Code gesetzt wird."""
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGroupBox, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QSlider, QSpinBox)


class Raw:
    """Wert + zugehöriger Python-Quelltext (für Qt-Enums im generierten Code)."""
    def __init__(self, code, value):
        self.code, self.value = code, value


@dataclass
class Spec:
    type: str
    qt: type
    size: tuple
    base: str                                  # Namensstamm: button -> button1
    props: list = field(default_factory=list)  # zusätzliche Eigenschaften
    defaults: dict = field(default_factory=dict)
    event: tuple | None = None                 # (qt-signal, handler-suffix, [argnamen])
    category: str = "Allgemeine Steuerelemente"


SPECS = [
    Spec("Button", QPushButton, (100, 32), "button", ["text"], {"text": "@name"}, ("clicked", "clicked", [])),
    Spec("Label", QLabel, (80, 20), "label", ["text"], {"text": "@name"}),
    Spec("TextBox", QLineEdit, (150, 26), "textBox", ["text", "placeholder", "readonly"], {"text": ""},
         ("textChanged", "text_changed", ["text"])),
    Spec("RichTextBox", QPlainTextEdit, (200, 100), "richTextBox", ["text", "readonly"], {"text": ""}),
    Spec("CheckBox", QCheckBox, (110, 22), "checkBox", ["text", "checked"], {"text": "@name", "checked": False},
         ("toggled", "toggled", ["checked"])),
    Spec("RadioButton", QRadioButton, (110, 22), "radioButton", ["text", "checked"], {"text": "@name", "checked": False},
         ("toggled", "toggled", ["checked"])),
    Spec("ComboBox", QComboBox, (150, 26), "comboBox", ["items"], {"items": ["Eintrag 1", "Eintrag 2"]},
         ("currentIndexChanged", "index_changed", ["index"])),
    Spec("ListBox", QListWidget, (150, 100), "listBox", ["items"], {"items": ["Eintrag 1", "Eintrag 2", "Eintrag 3"]},
         ("itemSelectionChanged", "selection_changed", [])),
    Spec("NumericUpDown", QSpinBox, (80, 26), "numericUpDown", ["minimum", "maximum", "value"],
         {"minimum": 0, "maximum": 100, "value": 0}, ("valueChanged", "value_changed", ["value"])),
    Spec("TrackBar", QSlider, (150, 30), "trackBar", ["minimum", "maximum", "value", "orientation"],
         {"minimum": 0, "maximum": 100, "value": 0, "orientation": "Horizontal"}, ("valueChanged", "value_changed", ["value"])),
    Spec("ProgressBar", QProgressBar, (150, 22), "progressBar", ["minimum", "maximum", "value"],
         {"minimum": 0, "maximum": 100, "value": 40}),
    Spec("GroupBox", QGroupBox, (200, 120), "groupBox", ["title"], {"title": "@name"}, category="Container"),
    Spec("Panel", QFrame, (200, 120), "panel", [], {}, category="Container"),
]
BY_TYPE = {s.type: s for s in SPECS}

COMMON = ["enabled", "visible", "tooltip", "font", "back_color", "fore_color"]
COMMON_DEFAULTS = {"enabled": True, "visible": True, "tooltip": "", "font": "", "back_color": "", "fore_color": ""}
COLOR_KEYS = ("back_color", "fore_color")

# key -> (Anzeigename, Art, Kategorie)   Art: str | int | bool | items | choice
PROP_INFO = {
    "text": ("Text", "str", "Darstellung"), "title": ("Text", "str", "Darstellung"),
    "font_size": ("Schriftgröße", "int", "Darstellung"),
    "font": ("Font", "font", "Darstellung"), "back_color": ("BackColor", "color", "Darstellung"), "fore_color": ("ForeColor", "color", "Darstellung"), "placeholder": ("Platzhalter", "str", "Darstellung"),
    "orientation": ("Ausrichtung", "choice", "Darstellung"),
    "enabled": ("Enabled", "bool", "Verhalten"), "visible": ("Visible", "bool", "Verhalten"),
    "readonly": ("ReadOnly", "bool", "Verhalten"), "checked": ("Checked", "bool", "Verhalten"),
    "tooltip": ("ToolTip", "str", "Verhalten"), "items": ("Items (Komma-getrennt)", "items", "Daten"),
    "minimum": ("Minimum", "int", "Daten"), "maximum": ("Maximum", "int", "Daten"), "value": ("Value", "int", "Daten"),
}
CHOICES = {"orientation": ["Horizontal", "Vertical"]}


KIND_DEFAULT = {"str": "", "int": 0, "bool": False, "items": [], "choice": "", "color": "", "font": ""}


def new_props(spec: Spec, name: str) -> dict:
    d = {k: KIND_DEFAULT[PROP_INFO[k][1]] for k in prop_keys(spec)}
    d.update(COMMON_DEFAULTS); d.update(spec.defaults)
    return {k: (name if v == "@name" else (list(v) if isinstance(v, list) else v)) for k, v in d.items()}


def prop_keys(spec: Spec) -> list:
    return spec.props + COMMON


def calls(ctype: str, key: str, val):
    """Setter-Aufrufe für eine Eigenschaft: [(methodenname, args)]. '@font' ist ein Sonderfall."""
    if key == "text":
        return [("setPlainText" if ctype == "RichTextBox" else "setText", (val,))]
    simple = {"title": "setTitle", "placeholder": "setPlaceholderText", "readonly": "setReadOnly",
              "checked": "setChecked", "enabled": "setEnabled", "visible": "setVisible", "tooltip": "setToolTip",
              "minimum": "setMinimum", "maximum": "setMaximum", "value": "setValue"}
    if key in simple:
        return [(simple[key], (val,))]
    if key == "items":
        return [("clear", ()), ("addItems", (list(val),))]
    if key == "orientation":
        o = Qt.Horizontal if val == "Horizontal" else Qt.Vertical
        return [("setOrientation", (Raw(f"Qt.{val}", o),))]
    if key == "font_size":
        return [("@font", (val,))] if val else []
    return []


def font_decls(props: dict) -> str:
    """Schrift als QSS-Deklarationen. Nur für die Live-Ansicht im Designer: Das globale IDE-Stylesheet überstimmt setFont()."""
    f = props.get("font")
    if isinstance(f, dict) and f:
        deco = " ".join(n for k, n in (("underline", "underline"), ("strike", "line-through")) if f.get(k))
        return (f'font-family: "{f.get("family", "")}"; font-size: {int(f.get("size", 10))}pt; font-weight: {int(f.get("weight", 400))}; '
                f'font-style: {"italic" if f.get("italic") else "normal"};' + (f" text-decoration: {deco};" if deco else ""))
    if props.get("font_size"):
        return f"font-size: {int(props['font_size'])}pt;"
    return ""


def style_for(ctype: str, props: dict, live: bool = False) -> str:
    """QSS für BackColor/ForeColor eines Controls ('' wenn nichts gesetzt ist); live=True nimmt die Schrift mit auf."""
    rules = [font_decls(props)] if live and font_decls(props) else []
    if props.get("back_color"):
        rules.append(f"background-color: {props['back_color']};")
    if props.get("fore_color"):
        rules.append(f"color: {props['fore_color']};")
    return f"{BY_TYPE[ctype].qt.__name__} {{ {' '.join(rules)} }}" if rules else ""


def font_for(props: dict) -> QFont | None:
    """QFont aus dem Font-Dict (neu) bzw. der alten Schriftgröße; None = Standard (erbt vom Elternteil)."""
    from ..ui.font_dialog import dict_to_font
    f = props.get("font")
    if isinstance(f, dict) and f:
        return dict_to_font(f)
    if props.get("font_size"):
        legacy = QFont(); legacy.setPointSize(int(props["font_size"]))
        return legacy
    return None


def apply_prop(widget, ctype: str, key: str, val, props: dict | None = None):
    """Wendet eine Eigenschaft auf das Live-Widget an (visible bleibt im Designer sichtbar)."""
    if key == "visible":
        return
    if key in COLOR_KEYS or key in ("font", "font_size"):
        merged = {**(props or {}), key: val}
        # Nur per Stylesheet: setFont() zusätzlich würde sich mit der QSS-Schrift gegenseitig auslösen (Endlosschleife)
        widget.setStyleSheet(style_for(ctype, merged, live=True))
        return
    for m, args in calls(ctype, key, val):
        if m == "@font":
            f = widget.font(); f.setPointSize(args[0]); widget.setFont(f)
        else:
            getattr(widget, m)(*[a.value if isinstance(a, Raw) else a for a in args])


def make_widget(ctype: str, props: dict, parent):
    spec = BY_TYPE[ctype]
    w = spec.qt(parent)
    if ctype == "Panel":
        w.setFrameShape(QFrame.StyledPanel)
        w.setProperty("vdsPanel", True)
    order = ["minimum", "maximum", "value"]
    for k in [k for k in props if k not in order] + [k for k in order if k in props]:
        apply_prop(w, ctype, k, props[k], props)
    return w
