"""Web-Ausgabe des Designers: React (TSX) und Vue 3 (Einzeldatei-Komponente). Ein gemeinsames Knotenmodell wird zu JSX bzw. Template gerendert.
Layouts werden zu CSS (Flex/Grid), freie Positionierung zu position:absolute; Ereignisse sind Props (React) bzw. emits (Vue)."""
import html
import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import layouts
from ..controls import BY_TYPE
from . import base

SUPPORTED = {"Button", "Label", "TextBox", "RichTextBox", "CheckBox", "RadioButton", "ComboBox", "ListBox", "NumericUpDown", "DoubleSpinBox", "TrackBar",
             "ProgressBar", "Line", "PictureBox", "DateEdit", "TimeEdit", "GroupBox", "Panel", "TabWidget",
             "ToolButton", "CommandLinkButton", "DateTimeEdit", "Dial", "ScrollBar", "LcdNumber", "TextBrowser", "TableWidget", "TableView", "TreeWidget",
             "TreeView", "ListView", "CalendarWidget", "FontComboBox", "KeySequenceEdit", "MenuBar", "StatusBar", "DialogButtonBox"}
COMPONENTS = {"MessageBox", "InputDialog", "OpenFileDialog", "FolderBrowserDialog", "ColorDialog", "PrintDialog", "PrintPreviewDialog"}
FONTS = ["Arial", "Courier New", "Georgia", "Helvetica", "Times New Roman", "Trebuchet MS", "Verdana"]
# (DOM-Ereignis, Argumentart) je Steuerelement-Ereignis
EVENT_DOM = {"Button": ("click", "none"), "TextBox": ("input", "value"), "CheckBox": ("change", "checked"), "RadioButton": ("change", "checked"),
             "ComboBox": ("change", "index"), "NumericUpDown": ("input", "number"), "DoubleSpinBox": ("input", "number"), "TrackBar": ("input", "number"),
             "DateEdit": ("change", "value"), "TimeEdit": ("change", "value"), "ListBox": ("change", "index"), "ToolButton": ("click", "none"),
             "CommandLinkButton": ("click", "none"), "DateTimeEdit": ("change", "value"), "Dial": ("input", "number"), "ScrollBar": ("input", "number"),
             "FontComboBox": ("change", "index"), "KeySequenceEdit": ("input", "value"), "CalendarWidget": ("change", "value")}
TAB_EVENT = ("TabWidget", "index")                 # wird an den Tab-Knöpfen ausgelöst
ARG_TS = {"none": "", "value": "value: string", "checked": "checked: boolean", "index": "index: number", "number": "value: number"}
JSX_ARG = {"none": "", "value": "e.currentTarget.value", "checked": "e.currentTarget.checked", "index": "e.currentTarget.selectedIndex",
           "number": "Number(e.currentTarget.value)"}
VUE_ARG = {"none": "", "value": "($event.target as HTMLInputElement).value", "checked": "($event.target as HTMLInputElement).checked",
           "index": "($event.target as HTMLSelectElement).selectedIndex", "number": "Number(($event.target as HTMLInputElement).value)"}
UNITLESS = {"flex", "opacity", "zIndex", "lineHeight", "fontWeight"}


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    style: dict = field(default_factory=dict)
    children: list = field(default_factory=list)       # Node oder str
    events: list = field(default_factory=list)         # {"dom", "kind": emit|state, "name", "arg", "value"}
    cond: str = ""                                     # Sichtbarkeitsbedingung (Tab-Seiten): "name:index"


# --- Modell -> Knoten ---------------------------------------------------------------------------------
def text_style(p: dict) -> dict:
    st, f = {}, base.font_of(p)
    if f:
        if f["family"]:
            st["fontFamily"] = f'"{f["family"]}", sans-serif'
        st["fontSize"] = f"{f['size']}pt"
        if f["bold"]:
            st["fontWeight"] = 700
        if f["italic"]:
            st["fontStyle"] = "italic"
        deco = " ".join(n for k, n in (("underline", "underline"), ("strike", "line-through")) if f[k])
        if deco:
            st["textDecoration"] = deco
    if p.get("back_color"):
        st["backgroundColor"] = p["back_color"]
    if p.get("fore_color"):
        st["color"] = p["fore_color"]
    return st


def container_style(src: dict) -> dict:
    mode, spacing, margin, cols = layouts.cfg(src)
    if mode == "Keine":
        return {"position": "relative"}
    st = {"display": "grid" if mode == "Raster" else "flex", "gap": spacing, "padding": margin}
    if mode == "Raster":
        st["gridTemplateColumns"] = f"repeat({cols}, 1fr)"
    else:
        st["flexDirection"] = "column" if mode == "Vertikal" else "row"
    return st


def geometry(c: dict, in_layout: bool) -> dict:
    if in_layout:
        return {"minWidth": c["w"], "minHeight": c["h"], "boxSizing": "border-box"}
    return {"position": "absolute", "left": c["x"], "top": c["y"], "width": c["w"], "height": c["h"], "boxSizing": "border-box"}


def ev(c: dict):
    spec = BY_TYPE[c["type"]]
    dom = EVENT_DOM.get(c["type"])
    if c["type"] == "DialogButtonBox" or not spec.event or not dom:
        return []
    return [{"dom": dom[0], "kind": "emit", "name": base.event_name(c["name"], spec.event[1]), "arg": dom[1]}]


def make_node(model: dict, c: dict, in_layout: bool, tabs: list) -> Node:
    t, p, name = c["type"], c["props"], c["name"]
    st = {**geometry(c, in_layout), **text_style(p)}
    a: dict = {}
    if p.get("tooltip"):
        a["title"] = p["tooltip"]
    if p.get("enabled") is False:
        a["disabled"] = True
    al = base.ALIGN.get(p.get("alignment", ""), "")
    n = Node("div", a, st, events=ev(c))
    if t in ("Button", "ToolButton", "CommandLinkButton"):
        n.tag = "button"; n.children = [str(p.get("text", ""))]
    elif t == "Label":
        n.children = [str(p.get("text", ""))]
        st.update({"whiteSpace": "normal" if p.get("word_wrap") else "nowrap", "overflow": "hidden"})
        if al:
            st["textAlign"] = al
    elif t in ("TextBox", "KeySequenceEdit", "DateEdit", "TimeEdit", "DateTimeEdit", "CalendarWidget", "NumericUpDown", "DoubleSpinBox", "TrackBar", "Dial",
               "ScrollBar"):
        n.tag = "input"
        n.attrs["type"] = {"TextBox": "password" if p.get("password") else "text", "KeySequenceEdit": "text", "DateEdit": "date", "CalendarWidget": "date",
                           "TimeEdit": "time", "DateTimeEdit": "datetime-local", "TrackBar": "range", "Dial": "range", "ScrollBar": "range"}.get(t, "number")
        if t == "TextBox":
            n.attrs["value"] = str(p.get("text", ""))
            if p.get("placeholder"):
                n.attrs["placeholder"] = p["placeholder"]
            if p.get("readonly"):
                n.attrs["readonly"] = True
            if al:
                st["textAlign"] = al
        elif t in ("NumericUpDown", "DoubleSpinBox", "TrackBar", "Dial", "ScrollBar"):
            n.attrs.update(min=p.get("minimum", 0), max=p.get("maximum", 100), value=p.get("value", 0))
            if t == "DoubleSpinBox":
                n.attrs["step"] = "0.1"
    elif t == "RichTextBox":
        n.tag = "textarea"; n.attrs["value"] = str(p.get("text", ""))
        if p.get("readonly"):
            n.attrs["readonly"] = True
    elif t in ("CheckBox", "RadioButton"):
        n.tag = "label"; st["display"] = "flex"; st["alignItems"] = "center"; st["gap"] = 6
        box = Node("input", {"type": "checkbox" if t == "CheckBox" else "radio", **({"name": c.get("parent") or "radios"} if t == "RadioButton" else {}),
                             **({"checked": True} if p.get("checked") else {}), **({"disabled": True} if p.get("enabled") is False else {})}, events=n.events)
        n.attrs.pop("disabled", None); n.events = []
        n.children = [box, str(p.get("text", ""))]
    elif t == "FontComboBox":
        n.tag = "select"; n.children = [Node("option", {"value": str(i)}, children=[f]) for i, f in enumerate(FONTS)]
    elif t == "LcdNumber":
        n.children = [str(p.get("value", 0))]
        st.update({"fontFamily": "monospace", "fontSize": max(14, c["h"] - 10), "textAlign": "right", "background": "#101010", "color": "#7CFC00", "padding": "0 8px"})
    elif t == "TextBrowser":
        n.children = [str(p.get("text", ""))]; st.update({"overflow": "auto", "border": "1px solid #7a7a7a", "background": "#fff", "whiteSpace": "pre-wrap"})
    elif t in ("TableWidget", "TableView"):
        rows, cols = (int(p.get("rows", 3)), int(p.get("columns", 3))) if t == "TableWidget" else (3, 3)
        head = Node("tr", children=[Node("th", style={"border": "1px solid #a0a0a0", "background": "#e6e6e6"}, children=[str(i + 1)]) for i in range(cols)])
        body = [Node("tr", children=[Node("td", style={"border": "1px solid #d0d0d0", "height": 22}, children=[""]) for _ in range(cols)]) for _ in range(rows)]
        n.tag = "table"; st.update({"borderCollapse": "collapse", "background": "#fff", "tableLayout": "fixed"})
        n.children = [Node("thead", children=[head]), Node("tbody", children=body)]
    elif t in ("TreeWidget", "TreeView", "ListView"):
        n.tag = "ul"
        st.update({"overflow": "auto", "border": "1px solid #7a7a7a", "background": "#fff", "margin": 0, "listStyle": "none" if t != "TreeWidget" else "disc",
                   "padding": "4px 4px 4px 20px" if t == "TreeWidget" else 4})
        n.children = [Node("li", children=[str(x)]) for x in (p.get("items", []) if t == "TreeWidget" else [])]
    elif t == "MenuBar":
        n.tag = "nav"
        st.update({"display": "flex", "gap": 4, "background": "#f0f0f0", "borderBottom": "1px solid #a0a0a0"})
        n.children = [Node("button", {"type": "button"}, {"border": "none", "background": "transparent", "padding": "2px 8px"}, [str(x)]) for x in p.get("items", [])]
    elif t == "StatusBar":
        n.tag = "footer"; n.children = [str(p.get("text", ""))]
        st.update({"background": "#f0f0f0", "borderTop": "1px solid #a0a0a0", "padding": "2px 8px", "display": "flex", "alignItems": "center"})
    elif t == "DialogButtonBox":
        st.update({"display": "flex", "gap": 6, "justifyContent": "flex-end", "alignItems": "center"})
        n.children = [Node("button", {"type": "button"}, children=["OK"], events=[{"dom": "click", "kind": "emit", "name": base.event_name(name, "accepted"), "arg": "none"}]),
                      Node("button", {"type": "button"}, children=["Abbrechen"])]
        n.events = []
    elif t in ("ComboBox", "ListBox"):
        n.tag = "select"
        if t == "ListBox":
            n.attrs.update(multiple=True, size=max(2, c["h"] // 20))
        n.children = [Node("option", {"value": str(i)}, children=[str(x)]) for i, x in enumerate(p.get("items", []))]
    elif t == "ProgressBar":
        n.tag = "progress"; n.attrs.update(value=p.get("value", 0), max=p.get("maximum", 100))
    elif t == "Line":
        st.pop("height", None); st.pop("minHeight", None)
        horizontal = p.get("orientation", "Horizontal") == "Horizontal"
        st.update({"borderTop": "1px solid #a0a0a0"} if horizontal else {"borderLeft": "1px solid #a0a0a0"})
        if horizontal:
            st["height"] = 0
        else:
            st["width"] = 0
    elif t == "PictureBox":
        n.tag = "img"; n.attrs.update(src=p.get("image", ""), alt=name); st["objectFit"] = "fill"
    elif t in ("GroupBox", "Panel"):
        src = p
        st.update(container_style(src)); st["border"] = "1px solid #a0a0a0"
        if t == "GroupBox":
            n.tag = "fieldset"
            n.children = [Node("legend", children=[str(p.get("title", ""))])]
            st.update({"margin": 0, "padding": 0, **({"padding": container_style(src).get("padding", 0)} if layouts.cfg(src)[0] != "Keine" else {})})
        n.children += build(model, name, None)
    elif t == "TabWidget":
        titles = layouts.tab_titles(p)
        st.update({"display": "flex", "flexDirection": "column", "border": "1px solid #a0a0a0"})
        bar = Node("div", style={"display": "flex", "gap": 2, "borderBottom": "1px solid #a0a0a0", "background": "#e6e6e6"})
        for i, title in enumerate(titles):
            bar.children.append(Node("button", {"type": "button"}, {"border": "none", "padding": "4px 12px", "cursor": "pointer"}, [title],
                                     events=[{"dom": "click", "kind": "tab", "name": name + "Tab", "value": i, "emit": base.event_name(name, "tab_changed")}]))
        n.children = [bar]
        for i in range(len(titles)):
            page = Node("div", style={"position": "relative", "flex": 1, **container_style(p)}, cond=f"{name}Tab:{i}")
            page.children = build(model, name, i)
            n.children.append(page)
        tabs.append((name + "Tab", min(max(int(p.get("current", 0)), 0), len(titles) - 1)))
    return n


def build(model: dict, parent_name, tab, tabs=None) -> list:
    src = model if parent_name is None else layouts.by_name(model)[parent_name]["props"]
    in_layout = layouts.cfg(src)[0] != "Keine"
    tabs = _TABS if tabs is None else tabs
    return [make_node(model, c, in_layout, tabs) for c in base.kids(model, parent_name, tab) if c["type"] in SUPPORTED]


_TABS: list = []


def build_form(model: dict) -> tuple:
    """-> (Wurzelknoten, [(Tab-Zustandsname, Startindex)], [Ereignisse (name, arg)])"""
    _TABS.clear()
    st = {"position": "relative", "width": model["width"], "height": model["height"], "boxSizing": "border-box",
          "background": model.get("back_color") or "#f0f0f0", "fontFamily": '"Segoe UI", system-ui, sans-serif', "fontSize": 13, **container_style(model), **text_style(model)}
    root = Node("div", {"aria-label": model.get("title", "")}, st, build(model, None, None))
    events = []
    walk(root, lambda n: events.extend((e["name"], e["arg"]) for e in n.events if e["kind"] == "emit"))
    walk(root, lambda n: events.extend((e["emit"], "index") for e in n.events if e["kind"] == "tab"))
    return root, list(_TABS), events


def walk(n, fn):
    fn(n)
    for ch in n.children:
        if isinstance(ch, Node):
            walk(ch, fn)


# --- Renderer -----------------------------------------------------------------------------------------
def kebab(k: str) -> str:
    return "".join("-" + ch.lower() if ch.isupper() else ch for ch in k)


def css_value(k: str, v) -> str:
    return f"{v}px" if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in UNITLESS and v != 0 else str(v)


def render_vue(n: Node, depth: int) -> str:
    pad = "  " * depth
    attrs = []
    for k, v in n.attrs.items():
        if v is True:
            attrs.append(k)
        elif isinstance(v, (int, float)):
            attrs.append(f':{k}="{v}"')
        else:
            attrs.append(f'{k}="{html.escape(str(v), quote=True)}"')
    if n.cond:
        name, i = n.cond.split(":")
        attrs.append(f'v-if="{name} === {i}"')
    if n.style:
        attrs.append('style="' + html.escape(";".join(f"{kebab(k)}:{css_value(k, v)}" for k, v in n.style.items()), quote=True) + '"')
    for e in n.events:
        if e["kind"] == "tab":
            attrs.append(f'@{e["dom"]}="{e["name"]} = {e["value"]}; emit(\'{e["emit"]}\', {e["value"]})"')
        else:
            arg = VUE_ARG[e["arg"]]
            attrs.append(f'@{e["dom"]}="emit(\'{e["name"]}\'{", " + arg if arg else ""})"')
    head = f"{pad}<{n.tag}" + ("".join(" " + a for a in attrs))
    if n.tag in ("input", "img") and not n.children:
        return head + " />\n"
    out = head + ">\n"
    for ch in n.children:
        out += render_vue(ch, depth + 1) if isinstance(ch, Node) else f"{pad}  " + (("{{ " + json.dumps(ch, ensure_ascii=False) + " }}") if "{" in ch or "}" in ch else html.escape(ch)) + "\n"
    return out + f"{pad}</{n.tag}>\n"


def jsx_attr(k: str, v, tag: str) -> str:
    name = {"class": "className", "for": "htmlFor", "readonly": "readOnly"}.get(k, k)
    if k == "value" and tag in ("input", "textarea"):
        name = "defaultValue"
    elif k == "checked":
        name = "defaultChecked"
    if v is True:
        return name
    return f"{name}={{{json.dumps(v, ensure_ascii=False)}}}" if not isinstance(v, str) or name in ("min", "max", "size") else f"{name}={json.dumps(v, ensure_ascii=False)}"


def render_jsx(n: Node, depth: int) -> str:
    pad = "  " * depth
    attrs = []
    for k, v in n.attrs.items():
        if isinstance(v, str) and k in ("min", "max", "size", "value") and n.tag in ("input", "progress"):
            attrs.append(f"{k}={{{v}}}" if v.lstrip("-").isdigit() else jsx_attr(k, v, n.tag))
        else:
            attrs.append(jsx_attr(k, v, n.tag))
    if n.style:
        attrs.append("style={{ " + ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in n.style.items()) + " }}")
    for e in n.events:
        react = {"click": "onClick", "change": "onChange", "input": "onChange"}[e["dom"]]
        if e["kind"] == "tab":
            attrs.append(f'{react}={{() => {{ set{base.cap(e["name"])}({e["value"]}); props.on{base.cap(e["emit"])}?.({e["value"]}); }}}}')
        else:
            arg = JSX_ARG[e["arg"]]
            attrs.append(f'{react}={{{"(e) => " if arg else "() => "}props.on{base.cap(e["name"])}?.({arg})}}')
    head = f"{pad}<{n.tag}" + "".join(" " + a for a in attrs)
    if n.tag in ("input", "img") and not n.children:
        body = head + " />\n"
        return body
    out = head + ">\n"
    for ch in n.children:
        out += render_jsx(ch, depth + 1) if isinstance(ch, Node) else f"{pad}  {{{json.dumps(ch, ensure_ascii=False)}}}\n"
    out += f"{pad}</{n.tag}>\n"
    if n.cond:
        name, i = n.cond.split(":")
        out = f"{pad}{{{name} === {i} && (\n" + "".join("  " + line + "\n" for line in out.splitlines()) + f"{pad})}}\n"
    return out


# --- Dateien --------------------------------------------------------------------------------------------
def stem_of(form_path: Path) -> str:
    return form_path.name[: -len(".form.json")]


def comp_name(stem: str) -> str:
    n = "".join(ch if ch.isalnum() else "_" for ch in stem)
    return ("C" + n if not n or not n[0].isalpha() else n[0].upper() + n[1:])


def component_functions(model: dict, lang: str) -> str:
    """Nicht visuelle Komponenten (Dialoge) als exportierte Hilfsfunktionen: Aufruf z. B. `await openFileDialog1()`."""
    out = []
    for c in model.get("components", []):
        t, n, p = c["type"], c["name"], c["props"]
        q = lambda k: json.dumps(str(p.get(k, "")), ensure_ascii=False)
        if t == "MessageBox":
            if p.get("buttons") == "Ok":
                out.append(f"export function {n}(): void {{\n  window.alert({q('text')});\n}}")
            else:
                out.append(f"/** true = bestätigt */\nexport function {n}(): boolean {{\n  return window.confirm({q('text')});\n}}")
        elif t == "InputDialog":
            out.append(f"/** null = abgebrochen */\nexport function {n}(): string | null {{\n  return window.prompt({q('label')}, {q('text')});\n}}")
        elif t in ("OpenFileDialog", "FolderBrowserDialog"):
            extra = ("input.multiple = true;\n  " if p.get("multiselect") else "") if t == "OpenFileDialog" else "(input as any).webkitdirectory = true;\n  "
            out.append(f"/** Liefert die gewählten Dateien (leer = abgebrochen). */\nexport function {n}(): Promise<File[]> {{\n  return new Promise((resolve) => {{\n"
                       f"    const input = document.createElement(\"input\");\n    input.type = \"file\";\n    {extra}input.onchange = () => resolve(Array.from(input.files ?? []));\n"
                       f"    input.oncancel = () => resolve([]);\n    input.click();\n  }});\n}}")
        elif t == "ColorDialog":
            out.append(f"/** Liefert die Farbe als #rrggbb. */\nexport function {n}(): Promise<string> {{\n  return new Promise((resolve) => {{\n"
                       f"    const input = document.createElement(\"input\");\n    input.type = \"color\";\n    input.value = {q('color')};\n"
                       f"    input.onchange = () => resolve(input.value);\n    input.click();\n  }});\n}}")
        elif t in ("PrintDialog", "PrintPreviewDialog"):
            out.append(f"export function {n}(): void {{\n  window.print();\n}}")
    return ("\n\n" + "\n\n".join(out) + "\n") if out else ""


def react_source(model: dict, comp: str) -> str:
    root, tabs, events = build_form(model)
    props = "".join(f"  on{base.cap(n)}?: ({ARG_TS[a]}) => void;\n" for n, a in dict.fromkeys(events))
    states = "".join(f"  const [{n}, set{base.cap(n)}] = useState({i});\n" for n, i in tabs)
    imp = 'import React, { useState } from "react";' if tabs else 'import React from "react";'
    return (f'"use client";\n// {base.HEADER_LINE}\n{imp}\n\nexport interface {comp}Props {{\n{props}}}\n\n'
            f"export default function {comp}(props: {comp}Props) {{\n{states}  return (\n" + render_jsx(root, 2) + "  );\n}\n" + component_functions(model, "ts"))


def vue_source(model: dict, comp: str) -> str:
    root, tabs, events = build_form(model)
    em = "".join(f'  (e: "{n}"{", " + ARG_TS[a] if a != "none" else ""}): void;\n' for n, a in dict.fromkeys(events))
    script = '<script setup lang="ts">\n' + (('import { ref } from "vue";\n' if tabs else "")
                                              + ("const emit = defineEmits<{\n" + em + "}>();\n" if events else "")
                                              + "".join(f"const {n} = ref({i});\n" for n, i in tabs)) + "</script>\n"
    funcs = component_functions(model, "ts")
    extra = f'\n<script lang="ts">{funcs}</script>\n' if funcs else ""
    return f"<!-- {base.HEADER_LINE} -->\n{script}{extra}\n<template>\n" + render_vue(root, 1) + "</template>\n"


def write(form_path: Path, model: dict, target: str) -> Path:
    stem = stem_of(form_path)
    comp = comp_name(stem)
    ext = ".tsx" if target == "react" else ".vue"
    out = form_path.parent / f"{stem}{ext}"
    out.write_text(react_source(model, comp) if target == "react" else vue_source(model, comp), encoding="utf-8")
    return out
