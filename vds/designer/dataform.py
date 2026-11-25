"""Formular aus Tabelle: liest Spalten, Schlüssel und Beziehungen über Qt SQL und baut daraus ein fertiges Datenformular.

Typen werden zu passenden Steuerelementen (Text, Zahl, Datum, Häkchen, mehrzeilig), Fremdschlüssel zu Auswahllisten mit
Klartext, Tabellen mit Verweis auf diese Tabelle zu Unterformularen. Das Ergebnis ist ein gewöhnliches Designer-Modell:
alles bleibt verschieb- und änderbar.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtSql import QSqlDatabase, QSqlField, QSqlQuery

from . import codegen
from .vds_data import all_foreign_keys, display_column, ident

_INT = {"int", "uint", "qlonglong", "qulonglong", "short", "ushort", "long", "ulong", "char", "uchar"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}(:\d{2})?)?$")
_MEMO = re.compile(r"notes?|description|beschreibung|bemerkung|kommentar|comment|memo|text$", re.I)
_BOOL = re.compile(r"^(is|has|ist|hat)[A-Z_]|discontinued|active|aktiv|enabled|gesperrt|erledigt|deleted", re.I)
from .controls import BINDABLE  # noqa: E402  (eine Quelle)


def _beschriftung(col: str) -> str:
    """ShipPostalCode → Ship Postal Code, kunden_nr → Kunden Nr"""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", col.replace("_", " ")).strip()
    return s[:1].upper() + s[1:]


def _ident(text: str) -> str:
    n = re.sub(r"\W", "", re.sub(r"[\s_]+(\w)", lambda m: m.group(1).upper(), text))
    n = n[:1].upper() + n[1:]                         # txt + Name, cbo + KategorieId
    return n if n and not n[0].isdigit() else "F" + n


def _samples(db: QSqlDatabase, table: str, col: str) -> list:
    q = QSqlQuery(db)
    q.exec(f"SELECT DISTINCT {ident(db, col)} FROM {ident(db, table)} WHERE {ident(db, col)} IS NOT NULL LIMIT 5")
    out = []
    while q.next():
        out.append(q.value(0))
    return out


def columns(db: QSqlDatabase, table: str) -> list[dict]:
    """[{name, kind, required, pk, auto}] – kind: int, float, bool, date, datetime, memo, blob, text."""
    rec, idx = db.record(table), db.primaryIndex(table)
    pk = [idx.fieldName(i) for i in range(idx.count())]
    rows = QSqlQuery(db)
    total = 0
    if rows.exec(f"SELECT count(*) FROM {ident(db, table)}") and rows.next():
        total = int(rows.value(0) or 0)
    out = []
    for i in range(rec.count()):
        f: QSqlField = rec.field(i)
        t = f.metaType().name().lower()
        name = f.name()
        if t in _INT:
            kind = "int"
        elif t in ("double", "float"):
            kind = "float"
        elif t == "bool":
            kind = "bool"
        elif t == "qdate":
            kind = "date"
        elif t == "qdatetime":
            kind = "datetime"
        elif t == "qbytearray" and db.driverName() != "QSQLITE":
            kind = "blob"
        else:
            kind = "text"
        samples = _samples(db, table, name) if kind in ("int", "text", "float") else []
        if db.driverName() == "QSQLITE":       # SQLite: Typen sind nur Empfehlungen – die Werte entscheiden mit
            if any(isinstance(s, (bytes, bytearray)) for s in samples) or (samples and t == "qbytearray"):
                kind = "blob"
            elif kind == "text" and samples and all(isinstance(s, str) and _DATE_RE.match(s) for s in samples):
                kind = "datetime" if any(len(s) > 10 and not s.endswith("00:00:00") for s in samples) else "date"
            elif kind == "text" and samples and all(isinstance(s, (int, float)) for s in samples):
                kind = "float" if any(isinstance(s, float) and not s.is_integer() for s in samples) else "int"
            elif kind == "text" and re.search(r"price|preis|amount|betrag|freight|fracht|cost|kosten", name, re.I) and not samples:
                kind = "float"
        if kind == "int" and name not in pk and (_BOOL.search(name) or (total > 2 and samples and set(samples) <= {0, 1})) \
                and not re.search(r"id$|nr$|count|anzahl|level|quantity|menge", name, re.I):
            kind = "bool"
        if kind == "float" and samples and all(float(s).is_integer() for s in samples) and not re.search(
                r"price|preis|amount|betrag|freight|fracht|cost|kosten|rate|discount|rabatt", name, re.I):
            kind = "int"
        if kind == "text" and _MEMO.search(name):
            kind = "memo"
        auto = len(pk) == 1 and name == pk[0] and (bool(f.isAutoValue()) or kind == "int")   # Teil eines zusammengesetzten Schlüssels: nie automatisch
        out.append({"name": name, "kind": kind, "required": f.requiredStatus() == QSqlField.Required and not auto,
                    "pk": name in pk, "auto": auto})
    return out


def _control(kind: str, lookup: bool) -> tuple[str, int, int]:
    if lookup:
        return "ComboBox", 240, 26
    return {"bool": ("CheckBox", 240, 22), "date": ("DateEdit", 140, 26), "datetime": ("DateTimeEdit", 180, 26),
            "memo": ("RichTextBox", 620, 70), "int": ("TextBox", 120, 26), "float": ("TextBox", 140, 26)}.get(kind, ("TextBox", 240, 26))


def connection_dict(conn, form_dir: Path) -> dict:
    """Verbindungsangaben fürs Formular – nie mit Kennwort; SQLite-Dateien relativ zum Formular, wenn möglich."""
    d = {"name": conn.name, "driver": conn.driver, "database": conn.database}
    if conn.driver == "QSQLITE":
        try:
            rel = os.path.relpath(conn.database, form_dir)
            if not rel.startswith(".." + os.sep + ".." + os.sep + ".."):
                d["database"] = Path(rel).as_posix()
        except ValueError:
            pass
    else:
        d.update(host=conn.host, port=conn.port, user=conn.user)
    return d


def form_from_table(db: QSqlDatabase, conn, table: str, name: str, form_dir: Path, subforms: bool = True) -> dict:
    cols = [c for c in columns(db, table) if c["kind"] != "blob"]
    fks = all_foreign_keys(db)
    lookups = {}
    for f in fks:
        if f["table"] == table and len(f["columns"]) == 1:
            lookups[f["columns"][0]] = [f["ref_table"], f["ref_columns"][0], display_column(db, f["ref_table"])]
    idx = db.primaryIndex(table)
    key = [idx.fieldName(i) for i in range(idx.count())] or [cols[0]["name"]]

    model = codegen.new_form(name)
    model.update(title=_beschriftung(table), width=800)
    model["data"] = {"connection": connection_dict(conn, form_dir), "table": table, "key": key,
                     "columns": cols, "lookups": lookups}
    ctrls = model["controls"]
    used: set = set()

    def uniq(base):
        n, i = base, 2
        while n in used:
            n, i = f"{base}{i}", i + 1
        used.add(n)
        return n

    def add(ctype, x, y, w, h, **props):
        from .controls import BY_TYPE, new_props
        nm = uniq(props.pop("_name"))
        p = new_props(BY_TYPE[ctype], nm)
        p.update(props)
        ctrls.append({"type": ctype, "name": nm, "x": x, "y": y, "w": w, "h": h, "props": p})
        return nm

    add("DataNavigator", 16, 12, 768, 34, _name="navigator")
    y, col_x = 60, (16, 408)
    slot = 0
    short = [c for c in cols if c["kind"] != "memo"]
    memos = [c for c in cols if c["kind"] == "memo"]
    for c in short:
        ctype, w, h = _control(c["kind"], c["name"] in lookups)
        x = col_x[slot % 2]
        yy = y + (slot // 2) * 34
        text = _beschriftung(c["name"])
        if c["name"] in lookups:                        # CustomerID → Customer (die Liste zeigt ja den Namen)
            text = re.sub(r"\s*(ID|Id|id|Nr|nr)$", "", text) or text
        label = text + (" *" if c["required"] else "")
        if ctype == "CheckBox":
            add("CheckBox", x + 130, yy + 2, w, h, _name="chk" + _ident(c["name"]), text=_beschriftung(c["name"]), field=c["name"])
        else:
            add("Label", x, yy + 4, 124, 20, _name="lbl" + _ident(c["name"]), text=label)
            extra = {"items": []} if ctype == "ComboBox" else {}
            if ctype == "TextBox" and c["kind"] in ("int", "float"):
                extra["alignment"] = "Rechts"
            if c["auto"]:
                extra["readonly"] = True
                extra["placeholder"] = "(automatisch)"
            prefix = {"ComboBox": "cbo", "DateEdit": "dat", "DateTimeEdit": "dat", "TextBox": "txt"}[ctype]
            add(ctype, x + 130, yy, w, h, _name=prefix + _ident(c["name"]), field=c["name"], **extra)
        slot += 1
    y += ((slot + 1) // 2) * 34 + 6
    for c in memos:
        add("Label", 16, y + 4, 124, 20, _name="lbl" + _ident(c["name"]), text=_beschriftung(c["name"]) + (" *" if c["required"] else ""))
        add("RichTextBox", 146, y, 638, 70, _name="txt" + _ident(c["name"]), field=c["name"])
        y += 80
    if subforms:
        for f in fks:
            if f["ref_table"] != table or not set(f["ref_columns"]) <= set(key) | {c["name"] for c in cols}:
                continue
            titel = _beschriftung(f["table"]) + (f" (über {', '.join(f['columns'])})" if f["table"] == table or
                                                  sum(g["table"] == f["table"] and g["ref_table"] == table for g in fks) > 1 else "")
            add("Label", 16, y + 6, 768, 20, _name="lbl" + _ident(f["table"]) + "Sub", text=titel, font={"family": "", "size": 10,
                "weight": 700, "italic": False, "underline": False, "strike": False})
            add("SubForm", 16, y + 30, 768, 190, _name="sub" + _ident(f["table"]), sub_table=f["table"],
                link=", ".join(f["columns"]), master=", ".join(f["ref_columns"]))
            y += 230
    model["height"] = max(y + 16, 240)
    return model


def binding_lines(model: dict) -> list:
    """Python-Code (für setup_ui), der das Formular an die Datenbank bindet."""
    data = model.get("data")
    if not data:
        return []
    cols = {c["name"]: c for c in data.get("columns", [])}
    bound = [c for c in model["controls"] if c["type"] in BINDABLE and c["props"].get("field")]
    fields = ", ".join(f"{c['props']['field']!r}: self.{c['name']}" for c in bound)
    kinds = {c["props"]["field"]: cols.get(c["props"]["field"], {}).get("kind", "text") for c in bound}
    kinds = {k: ("text" if v == "memo" else v) for k, v in kinds.items()}
    required = sorted({c["props"]["field"] for c in bound if cols.get(c["props"]["field"], {}).get("required")})
    auto = sorted({n for n, c in cols.items() if c.get("auto")})
    lookups = {k: tuple(v) for k, v in data.get("lookups", {}).items() if k in kinds}
    labels = {}
    for c in model["controls"]:
        if c["type"] == "Label" and c["name"].startswith("lbl"):
            for b in bound:
                if b["name"][3:] == c["name"][3:]:
                    labels[b["props"]["field"]] = c["props"].get("text", "").rstrip(" *")
    for b in bound:
        if b["type"] == "CheckBox":
            labels[b["props"]["field"]] = b["props"].get("text", b["props"]["field"])
    subs = []
    for c in model["controls"]:
        if c["type"] == "SubForm" and c["props"].get("sub_table"):
            link = [s.strip() for s in c["props"].get("link", "").split(",") if s.strip()]
            master = [s.strip() for s in c["props"].get("master", "").split(",") if s.strip()]
            subs.append(f"(self.{c['name']}, {c['props']['sub_table']!r}, {link!r}, {master!r})")
    nav = next((f"self.{c['name']}" for c in model["controls"] if c["type"] == "DataNavigator"), "None")
    conn = {k: v for k, v in data["connection"].items() if k != "password"}
    return [
        "",
        "# --- Datenbindung (Tabelle " + repr(data["table"]) + "): self.binding.save(), .new(), .delete(), .values() …",
        f"self.binding = FormBinding(root, {conn!r}, {data['table']!r}, {data['key']!r},",
        f"    fields={{{fields}}},",
        f"    kinds={kinds!r},",
        f"    required={required!r}, auto={auto!r},",
        f"    lookups={lookups!r},",
        f"    labels={labels!r},",
        f"    subforms=[{', '.join(subs)}],",
        f"    navigator={nav})",
    ]
