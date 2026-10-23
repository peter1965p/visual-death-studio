"""Control-Katalog des Formular-Designers: Typen, Standardwerte, Eigenschaften, Events.
Eine Stelle beschreibt, wie ein Control live (Qt-Widget) und im erzeugten Python-Code gesetzt wird."""
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QCalendarWidget, QCheckBox, QComboBox, QCommandLinkButton, QDateEdit, QDateTimeEdit, QDial, QDialogButtonBox,
                               QDoubleSpinBox, QFontComboBox, QFrame, QGroupBox, QKeySequenceEdit, QLabel, QLCDNumber, QLineEdit, QListView,
                               QListWidget, QMenuBar, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QScrollBar, QSlider, QSpinBox, QStatusBar,
                               QTableView, QTableWidget, QTextBrowser, QTimeEdit, QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem)


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
    imports: tuple = ()                        # zusätzliche Klassen, die der erzeugte Code importieren muss


SPECS = [
    Spec("Button", QPushButton, (100, 32), "button", ["text", "flat"], {"text": "@name"}, ("clicked", "clicked", [])),
    Spec("Label", QLabel, (80, 20), "label", ["text", "word_wrap", "alignment"], {"text": "@name"}),
    Spec("TextBox", QLineEdit, (150, 26), "textBox", ["text", "placeholder", "readonly", "password", "alignment"], {"text": ""},
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
    Spec("ToolButton", QToolButton, (60, 28), "toolButton", ["text"], {"text": "…"}, ("clicked", "clicked", [])),
    Spec("CommandLinkButton", QCommandLinkButton, (220, 48), "commandLinkButton", ["text"], {"text": "@name"}, ("clicked", "clicked", [])),
    # --- Eingabe
    Spec("DateEdit", QDateEdit, (120, 26), "dateEdit", [], {}, ("dateChanged", "date_changed", ["date"]), "Eingabe"),
    Spec("TimeEdit", QTimeEdit, (100, 26), "timeEdit", [], {}, ("timeChanged", "time_changed", ["time"]), "Eingabe"),
    Spec("DateTimeEdit", QDateTimeEdit, (170, 26), "dateTimeEdit", [], {}, ("dateTimeChanged", "datetime_changed", ["value"]), "Eingabe"),
    Spec("DoubleSpinBox", QDoubleSpinBox, (90, 26), "doubleSpinBox", ["minimum", "maximum", "value"], {"minimum": 0, "maximum": 100, "value": 0},
         ("valueChanged", "value_changed", ["value"]), "Eingabe"),
    Spec("Dial", QDial, (80, 80), "dial", ["minimum", "maximum", "value"], {"minimum": 0, "maximum": 100, "value": 0},
         ("valueChanged", "value_changed", ["value"]), "Eingabe"),
    Spec("ScrollBar", QScrollBar, (150, 18), "scrollBar", ["minimum", "maximum", "value", "orientation"],
         {"minimum": 0, "maximum": 100, "value": 0, "orientation": "Horizontal"}, ("valueChanged", "value_changed", ["value"]), "Eingabe"),
    Spec("FontComboBox", QFontComboBox, (200, 26), "fontComboBox", [], {}, ("currentFontChanged", "font_changed", ["font"]), "Eingabe"),
    Spec("KeySequenceEdit", QKeySequenceEdit, (150, 26), "keySequenceEdit", [], {}, ("keySequenceChanged", "key_sequence_changed", ["sequence"]), "Eingabe"),
    # --- Anzeige
    Spec("LcdNumber", QLCDNumber, (100, 40), "lcdNumber", ["value"], {"value": 0}, None, "Anzeige"),
    Spec("CalendarWidget", QCalendarWidget, (260, 190), "calendarWidget", [], {}, ("selectionChanged", "selection_changed", []), "Anzeige"),
    Spec("TextBrowser", QTextBrowser, (200, 100), "textBrowser", ["text"], {"text": ""}, None, "Anzeige"),
    Spec("Line", QFrame, (150, 3), "line", ["orientation"], {"orientation": "Horizontal"}, None, "Anzeige"),
    # --- Daten
    Spec("TreeWidget", QTreeWidget, (200, 150), "treeWidget", ["items"], {"items": ["Eintrag 1", "Eintrag 2"]},
         ("itemSelectionChanged", "selection_changed", []), "Daten", ("QTreeWidgetItem",)),
    Spec("TableWidget", QTableWidget, (300, 150), "tableWidget", ["rows", "columns"], {"rows": 3, "columns": 3},
         ("itemSelectionChanged", "selection_changed", []), "Daten"),
    Spec("ListView", QListView, (150, 100), "listView", [], {}, None, "Daten"),
    Spec("TableView", QTableView, (300, 150), "tableView", [], {}, None, "Daten"),
    Spec("TreeView", QTreeView, (200, 150), "treeView", [], {}, None, "Daten"),
    Spec("PictureBox", QLabel, (120, 90), "pictureBox", ["image"], {"image": ""}, None, "Anzeige", ("QPixmap",)),
    # --- Menüs und Leisten
    Spec("MenuBar", QMenuBar, (300, 26), "menuBar", ["items"], {"items": ["Datei", "Bearbeiten", "Hilfe"]}, None, "Menüs und Leisten"),
    Spec("StatusBar", QStatusBar, (300, 24), "statusBar", ["text"], {"text": "Bereit"}, None, "Menüs und Leisten"),
    # --- Dialoge
    Spec("DialogButtonBox", QDialogButtonBox, (220, 32), "buttonBox", [], {}, ("accepted", "accepted", []), "Dialoge"),
    # --- Container
    Spec("GroupBox", QGroupBox, (200, 120), "groupBox", ["title"], {"title": "@name"}, category="Container"),
    Spec("Panel", QFrame, (200, 120), "panel", [], {}, category="Container"),
]
CATEGORIES = ["Allgemeine Steuerelemente", "Eingabe", "Anzeige", "Daten", "Menüs und Leisten", "Dialoge", "Container"]
BY_TYPE = {s.type: s for s in SPECS}

COMMON = ["enabled", "visible", "tooltip", "font", "back_color", "fore_color"]
COMMON_DEFAULTS = {"enabled": True, "visible": True, "tooltip": "", "font": "", "back_color": "", "fore_color": ""}
COLOR_KEYS = ("back_color", "fore_color")

# key -> (Anzeigename, Art, Kategorie)   Art: str | int | bool | items | choice
PROP_INFO = {
    "text": ("Text", "str", "Darstellung"), "title": ("Text", "str", "Darstellung"),
    "font_size": ("Schriftgröße", "int", "Darstellung"),
    "font": ("Font", "font", "Darstellung"), "back_color": ("BackColor", "color", "Darstellung"), "fore_color": ("ForeColor", "color", "Darstellung"), "placeholder": ("Platzhalter", "str", "Darstellung"),
    "orientation": ("Ausrichtung", "choice", "Darstellung"), "alignment": ("Textausrichtung", "choice", "Darstellung"),
    "flat": ("Flat", "bool", "Darstellung"), "word_wrap": ("WordWrap", "bool", "Darstellung"), "password": ("Passwort", "bool", "Verhalten"),
    "rows": ("Zeilen", "int", "Daten"), "columns": ("Spalten", "int", "Daten"), "image": ("Bilddatei", "str", "Darstellung"),
    "enabled": ("Enabled", "bool", "Verhalten"), "visible": ("Visible", "bool", "Verhalten"),
    "readonly": ("ReadOnly", "bool", "Verhalten"), "checked": ("Checked", "bool", "Verhalten"),
    "tooltip": ("ToolTip", "str", "Verhalten"), "items": ("Items (Komma-getrennt)", "items", "Daten"),
    "minimum": ("Minimum", "int", "Daten"), "maximum": ("Maximum", "int", "Daten"), "value": ("Value", "int", "Daten"),
}
CHOICES = {"orientation": ["Horizontal", "Vertical"], "alignment": ["Links", "Mitte", "Rechts"]}


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
        if ctype == "StatusBar":
            return [("showMessage", (val,))]
        return [("setPlainText" if ctype in ("RichTextBox", "TextBrowser") else "setText", (val,))]
    if key == "image":
        return [("setScaledContents", (True,)), ("setPixmap", (Raw(f"QPixmap({val!r})", QPixmap(val) if val else QPixmap()),))]
    if key == "items" and ctype == "MenuBar":
        return [("clear", ())] + [("addMenu", (t,)) for t in val]
    if key == "orientation" and ctype == "Line":
        shape = "HLine" if val == "Horizontal" else "VLine"
        return [("setFrameShape", (Raw(f"QFrame.{shape}", getattr(QFrame, shape)),)), ("setFrameShadow", (Raw("QFrame.Sunken", QFrame.Sunken),))]
    if key == "value" and ctype == "LcdNumber":
        return [("display", (val,))]
    if key == "items" and ctype == "TreeWidget":
        code = "[" + ", ".join(f"QTreeWidgetItem([{t!r}])" for t in val) + "]"
        return [("clear", ()), ("setHeaderHidden", (True,)), ("addTopLevelItems", (Raw(code, [QTreeWidgetItem([t]) for t in val]),))]
    if key == "password":
        mode = "Password" if val else "Normal"
        return [("setEchoMode", (Raw(f"QLineEdit.{mode}", getattr(QLineEdit, mode)),))]
    if key == "alignment":
        h = {"Links": "AlignLeft", "Mitte": "AlignHCenter", "Rechts": "AlignRight"}.get(val, "AlignLeft")
        return [("setAlignment", (Raw(f"Qt.{h} | Qt.AlignVCenter", getattr(Qt, h) | Qt.AlignVCenter),))]
    simple = {"title": "setTitle", "placeholder": "setPlaceholderText", "readonly": "setReadOnly",
              "checked": "setChecked", "enabled": "setEnabled", "visible": "setVisible", "tooltip": "setToolTip",
              "minimum": "setMinimum", "maximum": "setMaximum", "value": "setValue",
              "flat": "setFlat", "word_wrap": "setWordWrap", "rows": "setRowCount", "columns": "setColumnCount"}
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
