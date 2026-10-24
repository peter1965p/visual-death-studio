"""Ausgabeziele des Formular-Designers. Das Modell ist für alle gleich; `model["target"]` wählt, welcher Code erzeugt wird."""
from pathlib import Path

from ..controls import BY_TYPE
from . import base, swing, web

DEFAULT = "python-qt"
# id -> (Anzeigename, Endung der Benutzerdatei, unterstützte Controls | None = alle)
TARGETS = {
    "python-qt": ("Python – Qt (PySide6)", ".py", None),
    "java-swing": ("Java – Swing", ".java", swing.SUPPORTED),
    "react": ("React + TypeScript (.tsx)", ".tsx", web.SUPPORTED),
    "vue": ("Vue 3 (.vue)", ".vue", web.SUPPORTED),
    "angular": ("Angular (eigenständige Komponente, .ts)", ".component.ts", web.SUPPORTED),
}
LABELS = {i: t[0] for i, t in TARGETS.items()}
WEB = ("react", "vue", "angular")


def target_of(model: dict) -> str:
    return model.get("target") if model.get("target") in TARGETS else DEFAULT


def stem_of(form_path: Path) -> str:
    return form_path.name[: -len(".form.json")]


def user_file(form_path: Path, model: dict) -> Path:
    """Die Datei, in der der Benutzer den Code schreibt (und die „Code anzeigen“ öffnet)."""
    t, stem = target_of(model), stem_of(form_path)
    if t == "java-swing":
        return form_path.parent / f"{swing.names(stem)[0]}.java"
    if t == "angular":
        return form_path.parent / web.angular_names(stem)[0]
    return form_path.parent / f"{stem}{TARGETS[t][1]}"


def unsupported(model: dict) -> list:
    """Controls und Komponenten, die das Ziel nicht erzeugt (für den Hinweis beim Speichern)."""
    t = target_of(model)
    sup = TARGETS[t][2]
    if sup is None:
        return []
    comps = web.COMPONENTS if t in WEB else swing.COMPONENTS
    return base.unsupported(model, sup) + [f"{c['name']} ({c['type']})" for c in model.get("components", []) if c["type"] not in comps]


def supports(model: dict, ctype: str) -> bool:
    t = target_of(model)
    sup = TARGETS[t][2]
    if sup is None:
        return True
    return ctype in (web.COMPONENTS if t in WEB else swing.COMPONENTS) if BY_TYPE[ctype].component else ctype in sup


def write(form_path: Path, model: dict) -> Path:
    t = target_of(model)
    if t == "java-swing":
        return swing.write(form_path, model)
    return web.write(form_path, model, t)


def handler(model: dict, control: dict):
    """(Name, Parameter) des Standardereignisses eines Controls im Zielcode oder None."""
    t, spec = target_of(model), BY_TYPE[control["type"]]
    if not spec.event:
        return None
    name = base.event_name(control["name"], spec.event[1])
    if t == "java-swing":
        probe = {"Button": "", "CheckBox": "boolean checked", "RadioButton": "boolean checked", "ComboBox": "int index", "NumericUpDown": "int value",
                 "TrackBar": "int value", "TabWidget": "int index", "TextBox": "String text", "ListBox": ""}
        return (name, probe[control["type"]]) if control["type"] in probe else None
    if t in WEB:
        return (name, "") if control["type"] in web.EVENT_DOM else None
    return None


def add_handler(user_file: Path, model: dict, name: str, params: str) -> int:
    return swing.add_handler(user_file, name, params) if target_of(model) == "java-swing" else 1
