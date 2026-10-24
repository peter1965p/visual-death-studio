"""Verschachtelung und Layouts im Formularmodell: Container, Kinder je Elternteil/Tab, Reihenfolge in Layouts.
Das Modell bleibt eine flache Liste; ein Control verweist per "parent" (und bei TabWidget per "tab") auf seinen Container."""

LAYOUTS = ["Keine", "Vertikal", "Horizontal", "Raster"]
LAYOUT_CLASS = {"Vertikal": "QVBoxLayout", "Horizontal": "QHBoxLayout", "Raster": "QGridLayout"}
CONTAINERS = ("GroupBox", "Panel", "TabWidget")
LAYOUT_KEYS = ("layout", "spacing", "margin", "grid_columns")
LAYOUT_DEFAULTS = {"layout": "Keine", "spacing": 6, "margin": 9, "grid_columns": 2}


def cfg(src: dict) -> tuple:
    """(Modus, Abstand, Rand, Rasterspalten) aus Formularmodell bzw. Container-Eigenschaften; fehlende Werte → Standard."""
    mode = src.get("layout") if src.get("layout") in LAYOUTS else "Keine"
    return (mode, int(src.get("spacing", 6)), int(src.get("margin", 9)), max(1, int(src.get("grid_columns", 2))))


def tab_titles(props: dict) -> list:
    return [str(t) for t in props.get("tabs") or []] or ["Tab 1"]


def tab_of(c: dict, parent: dict | None) -> int:
    """Seitenindex eines Kindes (nur bei TabWidget-Eltern relevant, auf vorhandene Seiten begrenzt)."""
    if not parent or parent["type"] != "TabWidget":
        return 0
    return min(max(int(c.get("tab", 0)), 0), len(tab_titles(parent["props"])) - 1)


def by_name(model: dict) -> dict:
    return {c["name"]: c for c in model["controls"]}


def children(model: dict, parent: str | None, tab: int | None = None) -> list:
    names = by_name(model)
    p = names.get(parent)
    return [c for c in model["controls"] if c.get("parent") == parent and (tab is None or tab_of(c, p) == tab)]


def with_descendants(model: dict, roots) -> list:
    """Die Controls samt aller Nachkommen, in Modellreihenfolge."""
    keep = set(roots)
    grew = True
    while grew:
        grew = False
        for c in model["controls"]:
            if c["name"] not in keep and c.get("parent") in keep:
                keep.add(c["name"]); grew = True
    return [c["name"] for c in model["controls"] if c["name"] in keep]


def ordered(kids: list, mode: str) -> list:
    """Reihenfolge der Kinder im Layout, abgeleitet aus ihren Positionen."""
    if mode == "Vertikal":
        return sorted(kids, key=lambda c: (c["y"], c["x"]))
    if mode == "Horizontal":
        return sorted(kids, key=lambda c: (c["x"], c["y"]))
    rows, out = [], []                                   # Raster: Zeilen nach y bilden, darin nach x sortieren
    for c in sorted(kids, key=lambda c: (c["y"], c["x"])):
        if rows and c["y"] <= rows[-1][0]["y"] + max(rows[-1][0]["h"] // 2, 4):
            rows[-1].append(c)
        else:
            rows.append([c])
    for r in rows:
        out += sorted(r, key=lambda c: c["x"])
    return out


def normalize(model: dict):
    """Repariert Verweise: unbekannte oder zyklische Eltern werden zu 'direkt im Formular'."""
    names = by_name(model)
    for c in model["controls"]:
        p, seen = c.get("parent"), {c["name"]}
        while p is not None:
            if p not in names or p in seen or names[p]["type"] not in CONTAINERS:
                c.pop("parent", None); c.pop("tab", None)
                break
            seen.add(p); p = names[p].get("parent")
    # Eltern vor Kindern, sonst Reihenfolge (Z-Ordnung) unverändert
    order, placed, pending = [], set(), list(model["controls"])
    while pending:
        progress = False
        for c in list(pending):
            if c.get("parent") is None or c["parent"] in placed:
                order.append(c); placed.add(c["name"]); pending.remove(c); progress = True
        if not progress:
            order += pending; break
    model["controls"][:] = order
