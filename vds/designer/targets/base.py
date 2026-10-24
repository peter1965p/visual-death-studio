"""Gemeinsame Bausteine der Designer-Ziele (Java Swing, React, Vue): Namen, Schrift, Reihenfolge."""
import re

from .. import layouts

HEADER_LINE = "Automatisch von Visual Death Studio erzeugt – Änderungen gehen beim nächsten Speichern des Designers verloren."
ALIGN = {"Links": "left", "Mitte": "center", "Rechts": "right"}


def camel(s: str) -> str:
    """text_changed -> TextChanged"""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\W]+", s) if p)


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def event_name(cid: str, suffix: str) -> str:
    """Name des Ereignisses/Handlers in Java, React (onXxx) und Vue (emit): button1 + clicked -> button1Clicked"""
    return cid + camel(suffix)


def font_of(props: dict) -> dict:
    """Schrift als {family,size(pt),bold,italic,underline,strike} oder {} (Standard)."""
    f = props.get("font")
    if isinstance(f, dict) and f:
        return {"family": f.get("family", ""), "size": int(f.get("size", 10)), "bold": int(f.get("weight", 400)) >= 600,
                "italic": bool(f.get("italic")), "underline": bool(f.get("underline")), "strike": bool(f.get("strike"))}
    if props.get("font_size"):
        return {"family": "", "size": int(props["font_size"]), "bold": False, "italic": False, "underline": False, "strike": False}
    return {}


def kids(model: dict, parent_name, tab=None):
    """Kinder eines Containers in Ausgabereihenfolge: im Layout nach Position, sonst Modellreihenfolge."""
    src = model if parent_name is None else layouts.by_name(model)[parent_name]["props"]
    kid_list = layouts.children(model, parent_name, tab)
    mode = layouts.cfg(src)[0]
    return layouts.ordered(kid_list, mode) if mode != "Keine" else kid_list


def unsupported(model: dict, supported) -> list:
    return [f"{c['name']} ({c['type']})" for c in model["controls"] if c["type"] not in supported]


def components_note(model: dict) -> list:
    return [f"{c['name']} ({c['type']})" for c in model.get("components", [])]
