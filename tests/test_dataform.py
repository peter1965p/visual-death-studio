"""Datenformulare: Formular aus Tabelle, erzeugter Code mit Datenbindung, Navigationsleiste, Folgen-Analyse, Unterformulare."""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QMessageBox, QStyleOptionViewItem

from vds.designer import codegen, dataform
from vds.docks import database as D

SCHEMA = """
create table kategorien(kategorie_id integer primary key, bezeichnung text not null);
create table artikel(artikel_id integer primary key, name text not null, kategorie_id integer references kategorien(kategorie_id),
                     preis numeric, ausgelaufen integer, angelegt text, notes text);
create table bestellungen(bestell_nr integer primary key, kunde text not null, datum text);
create table "Bestell Positionen"(bestell_nr integer not null references bestellungen(bestell_nr),
                                  artikel_id integer not null references artikel(artikel_id), menge integer,
                                  primary key (bestell_nr, artikel_id));
insert into kategorien values (1, 'Getränke'), (2, 'Gewürze');
insert into artikel values (1, 'Chai', 1, 18, 0, '2024-01-02 00:00:00', 'Tee'), (2, 'Chang', 1, 19.5, 1, '2024-02-03 00:00:00', null),
                           (3, 'Aniseed Syrup', 2, 10, 0, '2024-03-04 00:00:00', null);
insert into bestellungen values (10, 'Anna', '2024-05-01'), (11, 'Bert', '2024-05-02');
insert into "Bestell Positionen" values (10, 1, 5), (10, 2, 3), (11, 3, 1);
"""


@pytest.fixture
def northwind_mini(qapp, tmp_path):
    p = tmp_path / "app" / "shop.db"
    p.parent.mkdir()
    c = sqlite3.connect(p); c.executescript(SCHEMA); c.commit(); c.close()
    conn = D.Connection("Shop", "QSQLITE", str(p))
    db, err = D.open_db(conn)
    assert db is not None, err
    yield db, conn, p
    D.close_db(db)


def _form(db, conn, table, name, folder):
    model = dataform.form_from_table(db, conn, table, name, folder)
    codegen.write_files(folder / f"{name}.form.json", model)
    return model


def _load(folder, name):
    sys.path.insert(0, str(folder))
    try:
        for mod in (name, f"{name}_designer", "vds_data"):
            sys.modules.pop(mod, None)
        cls = getattr(importlib.import_module(name), name)
    finally:
        sys.path.remove(str(folder))
    w = cls()
    w.binding.start()                         # sonst per Timer – im Test direkt
    return w


def test_columns_infer_kinds_from_types_and_values(northwind_mini):
    db, _, _ = northwind_mini
    k = {c["name"]: c for c in dataform.columns(db, "artikel")}
    assert k["artikel_id"]["kind"] == "int" and k["artikel_id"]["auto"] and k["artikel_id"]["pk"]
    assert k["name"]["required"] and k["preis"]["kind"] == "float"
    assert k["ausgelaufen"]["kind"] == "bool" and k["angelegt"]["kind"] == "date" and k["notes"]["kind"] == "memo"
    pos = {c["name"]: c for c in dataform.columns(db, "Bestell Positionen")}
    assert not pos["bestell_nr"]["auto"] and pos["bestell_nr"]["pk"] and pos["artikel_id"]["pk"]


def test_form_from_table_builds_lookups_subforms_and_relative_connection(northwind_mini):
    db, conn, p = northwind_mini
    m = dataform.form_from_table(db, conn, "artikel", "ArtikelForm", p.parent)
    types = {c["name"]: c["type"] for c in m["controls"]}
    assert types["navigator"] == "DataNavigator" and types["cboKategorieId"] == "ComboBox"
    assert types["chkAusgelaufen"] == "CheckBox" and types["datAngelegt"] == "DateEdit" and types["txtNotes"] == "RichTextBox"
    assert m["data"]["lookups"]["kategorie_id"] == ["kategorien", "kategorie_id", "bezeichnung"]
    assert m["data"]["connection"] == {"name": "Shop", "driver": "QSQLITE", "database": "shop.db"}
    assert "password" not in str(m["data"])
    label = next(c for c in m["controls"] if c["name"] == "lblKategorieId")
    assert label["props"]["text"] == "Kategorie"                         # Auswahlliste: ohne „Id“
    sub = next(c for c in m["controls"] if c["type"] == "SubForm")
    assert sub["props"]["sub_table"] == "Bestell Positionen" and sub["props"]["link"] == "artikel_id"


def test_generated_form_navigates_saves_and_validates(northwind_mini, monkeypatch):
    db, conn, p = northwind_mini
    _form(db, conn, "artikel", "ArtikelForm", p.parent)
    src = (p.parent / "ArtikelForm_designer.py").read_text()
    assert "from vds_data import DataNavigator, FormBinding" in src and (p.parent / "vds_data.py").is_file()
    compile(src, "ArtikelForm_designer.py", "exec")
    w = _load(p.parent, "ArtikelForm")
    b = w.binding
    assert len(b.keys) == 3 and w.navigator.pos.text() == "1 / 3"
    assert w.txtName.text() == "Chai" and w.cboKategorieId.currentText() == "Getränke" and w.txtPreis.text() == "18"
    assert w.datAngelegt.date() == QDate(2024, 1, 2) and not w.chkAusgelaufen.isChecked()
    assert w.txtArtikelId.isReadOnly()
    b.next()
    assert w.txtPreis.text() == "19.5" and w.chkAusgelaufen.isChecked()
    w.txtPreis.setText("21,75"); w.txtPreis.textEdited.emit("21,75")
    assert b.dirty and "✎" in w.navigator.pos.text()
    assert b.save()
    c = sqlite3.connect(p)
    assert c.execute("select preis, angelegt from artikel where artikel_id = 2").fetchone() == (21.75, "2024-02-03 00:00:00")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: warned.append(a[2])))
    b.new(); w.txtName.setText(""); w.txtPreis.setText("abc"); b.dirty = True
    assert not b.save() and "keine gültige Zahl" in warned[-1] and "Name ist ein Pflichtfeld" in warned[-1]
    w.txtName.setText("Ikura"); w.txtPreis.setText("31"); w.cboKategorieId.setCurrentIndex(w.cboKategorieId.findText("Gewürze"))
    assert b.save() and len(b.keys) == 4
    assert c.execute("select name, kategorie_id, preis from artikel where artikel_id = ?", (b.keys[b.pos][0],)).fetchone() == ("Ikura", 2, 31)
    b.search("an"); assert len(b.keys) == 2 and "🔍" in w.navigator.pos.text()          # Chang, Aniseed Syrup


def test_delete_shows_consequences_and_can_cascade(northwind_mini, monkeypatch):
    db, conn, p = northwind_mini
    _form(db, conn, "bestellungen", "BestellForm", p.parent)
    w = _load(p.parent, "BestellForm")
    b = w.binding
    asked = []
    b.ask = lambda title, text, buttons: (asked.append((text, buttons)) or "Abbrechen")
    assert not b.delete()
    assert "2 Zeile(n) in „Bestell Positionen“" in asked[0][0] and asked[0][1][-1] == "Mit abhängigen Zeilen löschen"
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a: asked.append(("CRIT", a[2]))))
    b.ask = lambda *a: "Nur Datensatz"
    assert not b.delete() and "FOREIGN KEY" in asked[-1][1]                            # Fremdschlüssel greift
    b.ask = lambda *a: "Mit abhängigen Zeilen löschen"
    assert b.delete()
    c = sqlite3.connect(p)
    assert c.execute("select count(*) from bestellungen").fetchone() == (1,)
    assert c.execute('select count(*) from "Bestell Positionen" where bestell_nr = 10').fetchone() == (0,)


def test_subform_shows_lookup_text_edits_and_inserts(northwind_mini):
    db, conn, p = northwind_mini
    _form(db, conn, "bestellungen", "BestellForm", p.parent)
    w = _load(p.parent, "BestellForm")
    b, view = w.binding, w.subBestellPositionen
    m = view.model()
    assert m.rowCount() == 2 and m.headerData(1, Qt.Horizontal) == "Artikel"
    o = QStyleOptionViewItem(); view.itemDelegate().initStyleOption(o, m.index(0, 1))
    assert o.text == "Chai"
    m.setData(m.index(0, 2), 9)
    b.next(); b.previous()                                              # Blättern speichert offene Änderungen
    c = sqlite3.connect(p)
    assert c.execute('select menge from "Bestell Positionen" where bestell_nr = 10 and artikel_id = 1').fetchone() == (9,)
    row = b._sub_add(m, view)
    m.setData(m.index(row, 1), 3); m.setData(m.index(row, 2), 2)
    assert b.submit_subforms()
    assert c.execute('select count(*) from "Bestell Positionen" where bestell_nr = 10').fetchone() == (3,)


def test_bound_fields_only_offered_in_data_forms(qapp):
    from vds.designer.controls import BY_TYPE, new_props
    assert "field" in new_props(BY_TYPE["TextBox"], "t1") and "field" not in new_props(BY_TYPE["Button"], "b1")
    plain = codegen.designer_source(codegen.new_form("F"), "F")
    assert "vds_data" not in plain


def test_database_panel_requests_form_for_tables_only(qapp, tmp_path):
    p = tmp_path / "a.db"
    c = sqlite3.connect(p); c.executescript("create table t(id integer primary key); create view v as select * from t;"); c.commit(); c.close()
    panel = D.DatabasePanel(); panel.set_root(tmp_path)
    assert panel.connect_to(D.Connection("", "QSQLITE", str(p)))
    got = []
    panel.formRequested.connect(got.append)
    items = {panel.tree.topLevelItem(i).text(0): panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())}
    panel._form_for(items["v"]); panel._form_for(items["t"].child(0))
    assert got == ["t"]
    panel.tree.setCurrentItem(items["t"])
    assert panel.b_form.isEnabled()
    panel.disconnect()


# --- „In DB Studio bearbeiten“ ----------------------------------------------------------------------------------------

def test_dbstudio_arguments_never_contain_password(qapp, tmp_path):
    import json
    from vds.docks import dbstudio
    lite = D.Connection("Shop", "QSQLITE", str(tmp_path / "shop.db"))
    args = dbstudio.argumente(lite, "Orders")
    assert args[0] == "--verbindung" and args[2:] == ["--tabelle", "Orders"]
    assert json.loads(args[1]) == {"art": "sqlite", "datei": str((tmp_path / "shop.db").resolve()), "name": "Shop"}
    pg = D.Connection("", "QPSQL", "shop", "db.local", 5432, "app", "geheim")
    d = dbstudio.verbindung(pg)
    assert d == {"art": "postgresql", "host": "db.local", "datenbank": "shop", "benutzer": "app", "port": 5432}
    assert "geheim" not in " ".join(dbstudio.argumente(pg))
    assert dbstudio.verbindung(D.Connection("", "QODBC", "dsn")) is None


def test_dbstudio_starts_detached_with_connection(qapp, tmp_path, monkeypatch, pump):
    import json
    from vds.docks import dbstudio
    out = tmp_path / "args.json"
    script = tmp_path / "fake_dbstudio.py"
    script.write_text(f"import json, sys\nopen({str(out)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    monkeypatch.setenv("VDS_DBSTUDIO", f"{sys.executable} {script}")
    p = tmp_path / "a.db"
    c = sqlite3.connect(p); c.execute("create table t(id integer primary key)"); c.commit(); c.close()
    panel = D.DatabasePanel(); panel.set_root(tmp_path)
    assert not panel.b_dbs.isEnabled()
    assert panel.connect_to(D.Connection("", "QSQLITE", str(p))) and panel.b_dbs.isEnabled()
    assert panel.open_in_dbstudio("t") and "geöffnet" in panel.info.text()
    pump(out.exists, 15)
    args = json.loads(out.read_text())
    assert args[-2:] == ["--tabelle", "t"] and json.loads(args[1])["datei"] == str(p.resolve())
    panel.disconnect()
    assert not panel.b_dbs.isEnabled()
