"""Datenbank-Explorer (SQLite über Qt SQL)."""
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt

from vds.app import MainWindow
from vds.docks import database as D


def make_db(p: Path) -> Path:
    c = sqlite3.connect(p)
    c.executescript("create table kunden(id integer primary key, name text not null, ort text);"
                    "insert into kunden(name, ort) values ('Anna','Köln'),('Bert','Bonn');"
                    "create view orte as select distinct ort from kunden;")
    c.commit(); c.close()
    return p


def test_schema_lists_tables_views_columns_and_keys(qapp, tmp_path):
    db, err = D.open_db(D.Connection("", "QSQLITE", str(make_db(tmp_path / "a.db"))))
    assert db is not None and err == ""
    s = {n: (k, cols) for n, k, cols in D.schema(db)}
    assert s["kunden"][0] == "Tabelle" and s["orte"][0] == "Sicht"
    assert s["kunden"][1][0] == ("id", "INTEGER", True) and s["kunden"][1][1] == ("name", "TEXT", False)
    D.close_db(db)


def test_missing_sqlite_file_is_not_created(qapp, tmp_path):
    db, err = D.open_db(D.Connection("", "QSQLITE", str(tmp_path / "nein.db")))
    assert db is None and "gibt es nicht" in err and not (tmp_path / "nein.db").exists()


def test_panel_runs_select_and_modifications(qapp, tmp_path):
    p = D.DatabasePanel(); p.set_root(tmp_path)
    assert p.connect_to(D.Connection("", "QSQLITE", str(make_db(tmp_path / "a.db"))))
    p._select_all(p.tree.topLevelItem(0))
    assert p.model.rowCount() == 2 and "2 Zeile" in p.info.text()
    p.sql.setPlainText("insert into kunden(name, ort) values ('Cora','Bonn')")
    assert p.execute() and "1 Zeile(n) betroffen" in p.info.text()
    p.sql.setPlainText("select count(*) from kunden"); p.execute()
    assert p.model.data(p.model.index(0, 0)) == 3
    p.sql.setPlainText("select * from gibtsnicht")
    assert p.execute() is False and p.info.text().startswith("Fehler")
    p.disconnect()
    assert p.db is None


def test_project_databases_are_offered_and_connection_is_remembered_without_password(qapp, tmp_path):
    (tmp_path / "data").mkdir()
    make_db(tmp_path / "data" / "x.sqlite")
    p = D.DatabasePanel(); p.set_root(tmp_path)
    assert "x.sqlite" in p.combo.itemText(0) and "im Projekt" in p.combo.itemText(0)
    p._pick(0)
    assert p.db is not None
    p.set_root(tmp_path)
    assert p.combo.count() == 1 and "password" in (tmp_path / ".vds/db.json").read_text() and '"password": ""' in (tmp_path / ".vds/db.json").read_text()
    p.disconnect()


def test_double_click_on_db_file_opens_the_explorer(qapp, tmp_path):
    make_db(tmp_path / "shop.db")
    win = MainWindow()
    try:
        win.set_root(tmp_path)
        win._open_file(tmp_path / "shop.db")
        assert win.dbpanel.db is not None and win.dbpanel.tree.topLevelItemCount() == 2
        win.dbpanel.disconnect()
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()
