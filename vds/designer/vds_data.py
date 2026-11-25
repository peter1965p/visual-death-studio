"""vds_data – Datenbindung für Formulare aus Visual Death Studio (nur PySide6 mit Qt SQL nötig).

Automatisch von Visual Death Studio geschrieben – Änderungen gehen beim nächsten Speichern des Designers verloren.
Das Formular verbindet sich selbst mit der Datenbank; Kennwörter stehen nie im Code: Sie kommen aus der Umgebungsvariable
VDS_DB_PASSWORD oder werden beim Start abgefragt. VDS_DB_DATABASE / VDS_DB_HOST / VDS_DB_USER überschreiben die Angaben.
"""
from __future__ import annotations

import itertools
import os
import re
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtSql import QSqlDatabase, QSqlDriver, QSqlQuery, QSqlTableModel
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDoubleSpinBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QSpinBox, QStyledItemDelegate, QTableView, QToolButton,
                               QWidget)

NULL_DATE = QDate(1752, 9, 14)          # kleinstes Datum = „leer“ (QDateEdit kennt kein NULL)
_ids = itertools.count(1)
_DISPLAY = re.compile(r"name|title|titel|bezeichnung|beschreibung|company|firma|label", re.I)


# --- Verbindung und Schema ----------------------------------------------------------------------------------------------

def connect(conn: dict, parent=None, base: Path | None = None) -> QSqlDatabase:
    """Öffnet die Verbindung aus dem Formular. RuntimeError mit lesbarem Text, wenn es nicht klappt."""
    driver = conn.get("driver", "QSQLITE")
    if driver not in QSqlDatabase.drivers():
        raise RuntimeError(f"Der Qt-Treiber {driver} ist nicht installiert.")
    database = os.environ.get("VDS_DB_DATABASE") or conn.get("database", "")
    if driver == "QSQLITE":
        p = Path(database)
        if not p.is_absolute():
            p = (base or Path(__file__).parent) / p
        if not p.is_file():
            raise RuntimeError(f"Die Datenbankdatei {p} gibt es nicht.")
        database = str(p)
    db = QSqlDatabase.addDatabase(driver, f"vds-form-{next(_ids)}")
    db.setDatabaseName(database)
    if driver != "QSQLITE":
        db.setHostName(os.environ.get("VDS_DB_HOST") or conn.get("host", ""))
        user = os.environ.get("VDS_DB_USER") or conn.get("user", "")
        db.setUserName(user)
        if conn.get("port"):
            db.setPort(int(conn["port"]))
        pw = os.environ.get("VDS_DB_PASSWORD")
        if pw is None:
            pw, ok = QInputDialog.getText(parent, "Anmeldung", f"Kennwort für {user}@{db.hostName()}:", QLineEdit.Password)
            if not ok:
                raise RuntimeError("Anmeldung abgebrochen.")
        db.setPassword(pw)
    if not db.open():
        raise RuntimeError(db.lastError().text() or "Verbindung fehlgeschlagen.")
    if driver == "QSQLITE":
        QSqlQuery(db).exec("PRAGMA foreign_keys = ON")
    return db


def ident(db: QSqlDatabase, name: str) -> str:
    return db.driver().escapeIdentifier(name, QSqlDriver.IdentifierType.TableName)


def all_foreign_keys(db: QSqlDatabase) -> list[dict]:
    """Alle Fremdschlüssel: [{table, columns, ref_table, ref_columns}] (SQLite, PostgreSQL, MySQL/MariaDB)."""
    drv, out = db.driverName(), []
    if drv == "QSQLITE":
        for t in db.tables():
            q = QSqlQuery(db)
            q.exec(f"PRAGMA foreign_key_list({ident(db, t)})")
            groups: dict[int, dict] = {}
            while q.next():
                g = groups.setdefault(q.value(0), {"table": t, "columns": [], "ref_table": q.value(2), "ref_columns": []})
                g["columns"].append(q.value(3)); g["ref_columns"].append(q.value(4))
            out += list(groups.values())
        return out
    if drv == "QPSQL":
        sql = """SELECT kcu.constraint_name, kcu.table_name, kcu.column_name, ccu.table_name, ccu.column_name
                 FROM information_schema.key_column_usage kcu
                 JOIN information_schema.referential_constraints rc
                   ON rc.constraint_name = kcu.constraint_name AND rc.constraint_schema = kcu.constraint_schema
                 JOIN information_schema.key_column_usage ccu
                   ON ccu.constraint_name = rc.unique_constraint_name AND ccu.constraint_schema = rc.unique_constraint_schema
                  AND ccu.ordinal_position = kcu.position_in_unique_constraint
                 WHERE kcu.table_schema = current_schema() ORDER BY kcu.constraint_name, kcu.ordinal_position"""
    elif drv == "QMYSQL":
        sql = """SELECT constraint_name, table_name, column_name, referenced_table_name, referenced_column_name
                 FROM information_schema.key_column_usage
                 WHERE table_schema = DATABASE() AND referenced_table_name IS NOT NULL ORDER BY constraint_name, ordinal_position"""
    else:
        return []
    q = QSqlQuery(db)
    q.exec(sql)
    groups: dict[tuple, dict] = {}
    while q.next():
        g = groups.setdefault((q.value(0), q.value(1)), {"table": q.value(1), "columns": [], "ref_table": q.value(3), "ref_columns": []})
        g["columns"].append(q.value(2)); g["ref_columns"].append(q.value(4))
    return list(groups.values())


def foreign_keys(db: QSqlDatabase, table: str) -> list[dict]:
    return [f for f in all_foreign_keys(db) if f["table"] == table]


def referencing(db: QSqlDatabase, table: str) -> list[dict]:
    """Fremdschlüssel anderer Tabellen (und der eigenen), die auf `table` zeigen."""
    return [f for f in all_foreign_keys(db) if f["ref_table"] == table]


def display_column(db: QSqlDatabase, table: str) -> str:
    """Spalte mit Klartext für Auswahllisten: Name/Titel/Bezeichnung …, sonst die erste Textspalte, sonst der Schlüssel."""
    rec, pk = db.record(table), [db.primaryIndex(table).fieldName(i) for i in range(db.primaryIndex(table).count())]
    names = [rec.fieldName(i) for i in range(rec.count())]
    texts = [n for n in names if n not in pk and rec.field(n).metaType().name() in ("QString", "QByteArray")]
    for n in texts:
        if _DISPLAY.search(n):
            return n
    return texts[0] if texts else (pk[0] if pk else names[0])


# --- Steuerelemente lesen und schreiben -----------------------------------------------------------------------------------

def _zahl_text(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:.10g}"
    return str(v)


class FormBinding(QObject):
    """Bindet Steuerelemente an eine Tabelle: blättern, suchen, neu, speichern, löschen mit Folgen-Analyse, Unterformulare."""
    changed = Signal()                  # Position oder Zustand hat sich geändert
    saved = Signal(object)              # Schlüssel des gespeicherten Datensatzes

    def __init__(self, root, conn: dict, table: str, key: list, fields: dict, kinds: dict | None = None, required=(),
                 lookups: dict | None = None, subforms=(), navigator=None, labels: dict | None = None, auto=(), start=True):
        super().__init__(root)
        self.root, self.conn, self.table, self.key = root, conn, table, list(key)
        self.fields, self.kinds = dict(fields), dict(kinds or {})
        self.required, self.auto = set(required), set(auto)
        self.lookups, self.subforms, self.nav = dict(lookups or {}), list(subforms), navigator
        self.labels = labels or {}
        self.db: QSqlDatabase | None = None
        self.keys: list[tuple] = []
        self.pos, self.is_new, self.dirty, self._loading = -1, False, False, False
        self.search_text = ""
        self._formats: dict[str, str] = {}
        self._models: list = []
        self.ask = self._ask                # in Tests ersetzbar
        if start:
            QTimer.singleShot(0, self.start)

    # --- Start
    def start(self, base: Path | None = None) -> bool:
        try:
            self.db = connect(self.conn, self.root, base)
        except RuntimeError as e:
            QMessageBox.critical(self.root, "Datenbank", str(e))
            if self.nav:
                self.nav.setEnabled(False)
            return False
        self._fill_lookups()
        self._wire()
        for view, *_ in self.subforms:
            self._setup_subform(view, *_)
        if self.nav:
            self.nav.bind(self)
        self.reload()
        return True

    def _fill_lookups(self):
        for col, (t, k, disp) in self.lookups.items():
            w = self.fields.get(col)
            if not isinstance(w, QComboBox):
                continue
            w.blockSignals(True)
            w.clear()
            w.addItem("", None)
            q = QSqlQuery(self.db)
            q.exec(f"SELECT {ident(self.db, k)}, {ident(self.db, disp)} FROM {ident(self.db, t)} ORDER BY 2")
            while q.next():
                w.addItem(str(q.value(1)) if q.value(1) is not None else f"({q.value(0)})", q.value(0))
            w.blockSignals(False)

    def _wire(self):
        for w in self.fields.values():
            sig = {QLineEdit: "textEdited", QPlainTextEdit: "textChanged", QCheckBox: "toggled", QComboBox: "currentIndexChanged",
                   QDateTimeEdit: "dateTimeChanged", QSpinBox: "valueChanged", QDoubleSpinBox: "valueChanged"}
            for cls, name in sig.items():
                if isinstance(w, cls):
                    getattr(w, name).connect(self._touched)
                    break
            if isinstance(w, QDateTimeEdit):          # QDateEdit erbt von QDateTimeEdit
                w.setCalendarPopup(True)
                w.setDisplayFormat("dd.MM.yyyy" if type(w) is QDateEdit else "dd.MM.yyyy HH:mm")
                w.setMinimumDate(NULL_DATE)
                w.setSpecialValueText(" ")

    def _touched(self, *_):
        if not self._loading and not self.dirty:
            self.dirty = True
            self.changed.emit()

    # --- Werte
    def _set(self, col, w, v):
        if isinstance(w, QComboBox):
            i = w.findData(v)
            if i < 0 and v is not None:
                w.addItem(f"({v})", v); i = w.count() - 1
            w.setCurrentIndex(max(i, 0))
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(v) and v not in ("0", "false", "False"))
        elif isinstance(w, (QDateEdit, QDateTimeEdit)):
            if isinstance(v, str) and v:
                self._formats[col] = "yyyy-MM-dd HH:mm:ss" if len(v) > 10 else "yyyy-MM-dd"
                d = QDateTime.fromString(v[:19], "yyyy-MM-dd HH:mm:ss")
                if not d.isValid():
                    d = QDateTime(QDate.fromString(v[:10], "yyyy-MM-dd"), d.time())
                v = d
            if isinstance(v, QDate):
                v = QDateTime(v, QDateTime().time())
            if not v or not v.isValid():
                w.setDate(NULL_DATE)
            elif type(w) is QDateEdit:
                w.setDate(v.date())
            else:
                w.setDateTime(v)
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            w.setValue(v or 0)
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText("" if v is None else str(v))
        else:
            w.setText(_zahl_text(v) if self.kinds.get(col) in ("int", "float") else ("" if v is None else str(v)))

    def _get(self, col, w):
        kind = self.kinds.get(col, "text")
        if isinstance(w, QComboBox):
            return w.currentData()
        if isinstance(w, QCheckBox):
            return w.isChecked() if kind == "bool" else int(w.isChecked())
        if isinstance(w, (QDateEdit, QDateTimeEdit)):
            if w.date() == NULL_DATE:
                return None
            d = QDateTime(w.date(), w.time() if type(w) is not QDateEdit else QDateTime().time())
            if self.db.driverName() == "QSQLITE" or col in self._formats:
                return d.toString(self._formats.get(col, "yyyy-MM-dd HH:mm:ss" if kind == "datetime" else "yyyy-MM-dd"))
            return d if kind == "datetime" else d.date()
        if isinstance(w, (QSpinBox, QDoubleSpinBox)):
            return w.value()
        text = (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip()
        if text == "":
            return None
        if kind == "int":
            return int(text.replace(".", "").replace(" ", ""))
        if kind == "float":
            t = text.replace(" ", "")
            t = t.replace(".", "").replace(",", ".") if "," in t else t
            return float(t)
        return text

    def values(self) -> dict:
        return {c: self._get(c, w) for c, w in self.fields.items()}

    # --- Datensätze
    def _where(self):
        return " AND ".join(f"{ident(self.db, k)} = ?" for k in self.key)

    def reload(self, keep=None):
        order = ", ".join(ident(self.db, k) for k in self.key)
        sql, params = f"SELECT {order} FROM {ident(self.db, self.table)}", []
        texts = [c for c, w in self.fields.items() if self.kinds.get(c, "text") == "text" and not isinstance(w, QComboBox)]
        if self.search_text and texts:
            sql += " WHERE " + " OR ".join(f"{ident(self.db, c)} LIKE ?" for c in texts)
            params = [f"%{self.search_text}%"] * len(texts)
            if self.db.driverName() == "QPSQL":
                sql = sql.replace(" LIKE ?", " ILIKE ?")
        q = QSqlQuery(self.db)
        q.prepare(sql + f" ORDER BY {order}")
        for p in params:
            q.addBindValue(p)
        q.exec()
        self.keys = []
        while q.next():
            self.keys.append(tuple(q.value(i) for i in range(len(self.key))))
        target = self.keys.index(keep) if keep in self.keys else 0
        self.go(target if self.keys else -1, force=True)

    def go(self, i, force=False) -> bool:
        if not force and not self.confirm_leave():
            return False
        self.is_new = False
        if not self.keys or i < 0:
            self.pos = -1
            self._clear()
        else:
            self.pos = max(0, min(i, len(self.keys) - 1))
            q = QSqlQuery(self.db)
            cols = list(self.fields)
            q.prepare(f"SELECT {', '.join(ident(self.db, c) for c in cols)} FROM {ident(self.db, self.table)} WHERE {self._where()}")
            for v in self.keys[self.pos]:
                q.addBindValue(v)
            q.exec()
            self._loading = True
            if q.next():
                for n, c in enumerate(cols):
                    self._set(c, self.fields[c], q.value(n))
            self._loading = False
        self.dirty = False
        self._lock_keys()
        self._refresh_subforms()
        self.changed.emit()
        return True

    def first(self): return self.go(0)
    def previous(self): return self.go(self.pos - 1) if self.pos > 0 else False
    def next(self): return self.go(self.pos + 1) if 0 <= self.pos < len(self.keys) - 1 else False
    def last(self): return self.go(len(self.keys) - 1)

    def search(self, text: str):
        if not self.confirm_leave():
            return
        self.search_text = text.strip()
        self.reload()

    def _clear(self):
        self._loading = True
        for c, w in self.fields.items():
            self._set(c, w, None)
        self._loading = False

    def _lock_keys(self):
        """Automatisch vergebene Schlüssel sind nie, andere nur bei neuen Datensätzen änderbar."""
        for k in self.key:
            w = self.fields.get(k)
            if w is not None and hasattr(w, "setReadOnly"):
                w.setReadOnly(k in self.auto or not self.is_new)
            elif w is not None:
                w.setEnabled(k not in self.auto and self.is_new)

    def new(self) -> bool:
        if not self.confirm_leave():
            return False
        self.is_new, self.dirty = True, False
        self._clear()
        self._lock_keys()
        self._refresh_subforms()
        first = next((w for c, w in self.fields.items() if c not in self.auto), None)
        if first:
            first.setFocus()
        self.changed.emit()
        return True

    def validate(self) -> tuple[dict, list]:
        vals, errors = {}, []
        for c, w in self.fields.items():
            if c in self.auto:
                continue
            label = self.labels.get(c, c)
            try:
                vals[c] = self._get(c, w)
            except ValueError:
                errors.append((c, f"{label}: keine gültige Zahl"))
                continue
            if c in self.required and (vals[c] is None or vals[c] == ""):
                errors.append((c, f"{label} ist ein Pflichtfeld"))
        return vals, errors

    def save(self) -> bool:
        if self.pos < 0 and not self.is_new:
            return False
        vals, errors = self.validate()
        if errors:
            QMessageBox.warning(self.root, "Speichern", "Bitte prüfen:\n\n• " + "\n• ".join(e for _, e in errors))
            self.fields[errors[0][0]].setFocus()
            return False
        q = QSqlQuery(self.db)
        if self.is_new:
            cols = [c for c, v in vals.items() if not (c in self.key and v is None)]
            q.prepare(f"INSERT INTO {ident(self.db, self.table)} ({', '.join(ident(self.db, c) for c in cols)}) "
                      f"VALUES ({', '.join('?' for _ in cols)})")
            for c in cols:
                q.addBindValue(vals[c])
        else:
            cols = list(vals)
            q.prepare(f"UPDATE {ident(self.db, self.table)} SET {', '.join(f'{ident(self.db, c)} = ?' for c in cols)} WHERE {self._where()}")
            for c in cols:
                q.addBindValue(vals[c])
            for v in self.keys[self.pos]:
                q.addBindValue(v)
        if not q.exec():
            QMessageBox.critical(self.root, "Speichern", "Die Datenbank hat abgelehnt:\n\n" + q.lastError().text())
            return False
        if self.is_new:
            key = tuple(vals.get(k) for k in self.key)
            if None in key and len(self.key) == 1:
                key = (q.lastInsertId(),)
        else:
            old = self.keys[self.pos]
            key = tuple(vals.get(k, o) for k, o in zip(self.key, old))
        self.dirty, self.is_new = False, False
        self.reload(keep=key)
        if key not in self.keys:                       # Suche passt nicht mehr: ohne Filter neu laden
            self.search_text = ""
            self.reload(keep=key)
        self.saved.emit(key)
        return True

    def consequences(self) -> list[dict]:
        """Was am aktuellen Datensatz hängt: [{table, columns, count, deeper}] – deeper: diese Tabelle hat selbst Abhängige."""
        if self.pos < 0:
            return []
        rec = dict(zip(self.key, self.keys[self.pos]))
        out, fks = [], all_foreign_keys(self.db)
        for f in [f for f in fks if f["ref_table"] == self.table]:
            if not all(rc in rec or rc in self.fields for rc in f["ref_columns"]):
                continue
            vals = [rec[rc] if rc in rec else self._get(rc, self.fields[rc]) for rc in f["ref_columns"]]
            q = QSqlQuery(self.db)
            q.prepare(f"SELECT count(*) FROM {ident(self.db, f['table'])} WHERE "
                      + " AND ".join(f"{ident(self.db, c)} = ?" for c in f["columns"]))
            for v in vals:
                q.addBindValue(v)
            q.exec()
            n = q.value(0) if q.next() else 0
            if n:
                deeper = any(g["ref_table"] == f["table"] for g in fks) and f["table"] != self.table
                out.append({"table": f["table"], "columns": f["columns"], "values": vals, "count": n, "deeper": deeper})
        return out

    def delete(self) -> bool:
        if self.is_new:
            return self.go(self.pos if self.pos >= 0 else 0, force=True)
        if self.pos < 0:
            return False
        folgen = self.consequences()
        cascade = False
        if folgen:
            lines = "\n".join(f"• {f['count']} Zeile(n) in „{f['table']}“ über {', '.join(f['columns'])}"
                              + (" – die haben selbst Abhängige" if f["deeper"] else "") for f in folgen)
            text = (f"An diesem Datensatz hängen:\n\n{lines}\n\nNur den Datensatz löschen: Mit Fremdschlüssel lehnt die Datenbank das ab, "
                    f"ohne bleiben diese Zeilen ohne Bezug zurück.")
            can_cascade = not any(f["deeper"] for f in folgen)
            answer = self.ask("Löschen – Folgen", text, ["Abbrechen", "Nur Datensatz"] + (["Mit abhängigen Zeilen löschen"] if can_cascade else []))
            if answer in (None, "Abbrechen"):
                return False
            cascade = answer == "Mit abhängigen Zeilen löschen"
        elif self.ask("Löschen", "Diesen Datensatz löschen?", ["Abbrechen", "Löschen"]) != "Löschen":
            return False
        self.db.transaction()
        try:
            if cascade:
                for f in folgen:
                    q = QSqlQuery(self.db)
                    q.prepare(f"DELETE FROM {ident(self.db, f['table'])} WHERE " + " AND ".join(f"{ident(self.db, c)} = ?" for c in f["columns"]))
                    for v in f["values"]:
                        q.addBindValue(v)
                    if not q.exec():
                        raise RuntimeError(q.lastError().text())
            q = QSqlQuery(self.db)
            q.prepare(f"DELETE FROM {ident(self.db, self.table)} WHERE {self._where()}")
            for v in self.keys[self.pos]:
                q.addBindValue(v)
            if not q.exec():
                raise RuntimeError(q.lastError().text())
            self.db.commit()
        except RuntimeError as e:
            self.db.rollback()
            QMessageBox.critical(self.root, "Löschen", "Die Datenbank hat abgelehnt:\n\n" + str(e))
            return False
        pos = self.pos
        self.reload()
        self.go(min(pos, len(self.keys) - 1), force=True)
        return True

    def confirm_leave(self) -> bool:
        if not self.dirty:
            return True
        a = self.ask("Änderungen", "Der Datensatz wurde geändert. Speichern?", ["Speichern", "Verwerfen", "Abbrechen"])
        if a == "Speichern":
            return self.save()
        if a == "Verwerfen":
            self.dirty = False
            return True
        return False

    def _ask(self, title, text, buttons) -> str | None:
        box = QMessageBox(QMessageBox.Question, title, text, parent=self.root)
        knoepfe = {box.addButton(b, QMessageBox.RejectRole if b == "Abbrechen" else QMessageBox.AcceptRole): b for b in buttons}
        box.exec()
        return knoepfe.get(box.clickedButton())

    # --- Unterformulare
    def _setup_subform(self, view: QTableView, table: str, link: list, master: list):
        m = QSqlTableModel(view, self.db)
        m.setTable(table)
        m.setEditStrategy(QSqlTableModel.OnRowChange)      # neue Zeilen erst speichern, wenn sie vollständig sind
        rec = self.db.record(table)
        lookups = {}
        for f in foreign_keys(self.db, table):
            i = rec.indexOf(f["columns"][0])
            if len(f["columns"]) == 1 and f["columns"][0] not in link and i >= 0:
                disp = display_column(self.db, f["ref_table"])
                q = QSqlQuery(self.db)
                q.exec(f"SELECT {ident(self.db, f['ref_columns'][0])}, {ident(self.db, disp)} FROM {ident(self.db, f['ref_table'])} ORDER BY 2")
                items = []
                while q.next():
                    items.append((q.value(0), "" if q.value(1) is None else str(q.value(1))))
                lookups[i] = items
        for i in range(rec.count()):
            m.setHeaderData(i, Qt.Horizontal, _beschriftung(rec.fieldName(i), i in lookups))
        view.setModel(m)
        view.setItemDelegate(_LookupDelegate(view, lookups))
        view.setSelectionBehavior(QAbstractItemView.SelectRows)
        view.horizontalHeader().setStretchLastSection(True)
        for c in link:
            view.setColumnHidden(rec.indexOf(c), True)
        view.setContextMenuPolicy(Qt.ActionsContextMenu)
        add, rem = QAction("Zeile hinzufügen", view), QAction("Zeile löschen", view)
        add.triggered.connect(lambda: self._sub_add(m, view))
        rem.triggered.connect(lambda: self._sub_remove(m, view))
        view.addActions([add, rem])
        self._models.append((m, view, link, master, table))

    def submit_subforms(self) -> bool:
        """Offene Änderungen in Unterformularen speichern (passiert auch beim Blättern im Hauptformular)."""
        ok = True
        for m, view, *_ in self._models:
            if m.isDirty() and not m.submitAll():
                QMessageBox.critical(self.root, "Unterformular", "Die Datenbank hat abgelehnt:\n\n" + m.lastError().text())
                ok = False
        return ok

    def _master_value(self, col):
        if self.pos >= 0 and col in self.key:
            return self.keys[self.pos][self.key.index(col)]
        return self._get(col, self.fields[col]) if col in self.fields else None

    def _refresh_subforms(self):
        self.submit_subforms()
        for m, view, link, master, table in self._models:
            if self.is_new or self.pos < 0:
                m.setFilter("1 = 0")
            else:
                drv = self.db.driver()
                parts = []
                for c, mc in zip(link, master):
                    v = self._master_value(mc)
                    field = self.db.record(table).field(c)
                    field.setValue(v)
                    parts.append(f"{ident(self.db, table)}.{ident(self.db, c)} = {drv.formatValue(field)}")
                m.setFilter(" AND ".join(parts))
            m.select()
            view.setEnabled(not self.is_new and self.pos >= 0)
            view.resizeColumnsToContents()

    def _sub_add(self, m, view):
        if self.dirty and not self.save():
            return
        entry = next(e for e in self._models if e[0] is m)
        m.submitAll()
        row = m.rowCount()
        m.insertRow(row)
        for c, mc in zip(entry[2], entry[3]):              # Verknüpfung zum Hauptdatensatz setzen
            m.setData(m.index(row, m.fieldIndex(c)), self._master_value(mc))
        view.scrollToBottom()
        first = next((i for i in range(m.columnCount()) if not view.isColumnHidden(i)), 0)
        view.setCurrentIndex(m.index(row, first))
        return row

    def _sub_remove(self, m, view):
        rows = sorted({i.row() for i in view.selectionModel().selectedIndexes()}, reverse=True)
        if rows and self.ask("Zeilen löschen", f"{len(rows)} Zeile(n) löschen?", ["Abbrechen", "Löschen"]) == "Löschen":
            for r in rows:
                m.removeRow(r)
            m.select()


def _beschriftung(col: str, lookup: bool = False) -> str:
    """ShipPostalCode → Ship Postal Code; bei Auswahllisten ohne „ID“ (ProductID → Product)."""
    t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", col.replace("_", " ")).strip()
    if lookup:
        t = re.sub(r"\s*(ID|Id|id|Nr|nr)$", "", t) or t
    return t[:1].upper() + t[1:]


class _LookupDelegate(QStyledItemDelegate):
    """Fremdschlüssel im Unterformular: Klartext anzeigen, Auswahlliste zum Bearbeiten, gespeichert wird der Schlüssel."""

    def __init__(self, parent, lookups: dict):
        super().__init__(parent)
        self.lookups = lookups
        self.texts = {i: dict(items) for i, items in lookups.items()}

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.column() in self.texts:
            v = index.data(Qt.EditRole)
            option.text = self.texts[index.column()].get(v, "" if v is None else f"({v})")

    def createEditor(self, parent, option, index):
        if index.column() not in self.lookups:
            return super().createEditor(parent, option, index)
        cb = QComboBox(parent)
        for k, t in self.lookups[index.column()]:
            cb.addItem(t, k)
        return cb

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox) and index.column() in self.lookups:
            editor.setCurrentIndex(max(editor.findData(index.data(Qt.EditRole)), 0))
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox) and index.column() in self.lookups:
            model.setData(index, editor.currentData())
        else:
            super().setModelData(editor, model, index)


# --- Navigationsleiste ----------------------------------------------------------------------------------------------------

class DataNavigator(QWidget):
    """⏮ ◀ 3 / 830 ▶ ⏭ · Neu · Speichern · Löschen · Suche – ohne Bindung (im Designer) nur Anzeige."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.binding: FormBinding | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        def knopf(text, tip):
            b = QToolButton(self); b.setText(text); b.setToolTip(tip); b.setAutoRaise(True); lay.addWidget(b)
            return b
        self.b_first, self.b_prev = knopf("⏮", "Erster Datensatz"), knopf("◀", "Vorheriger Datensatz")
        self.pos = QLabel("– / –", self); self.pos.setMinimumWidth(80); self.pos.setAlignment(Qt.AlignCenter); lay.addWidget(self.pos)
        self.b_next, self.b_last = knopf("▶", "Nächster Datensatz"), knopf("⏭", "Letzter Datensatz")
        self.b_new, self.b_save, self.b_del = knopf("＋ Neu", "Neuer Datensatz"), knopf("💾 Speichern", "Speichern (Strg+S)"), knopf("🗑 Löschen", "Löschen mit Folgen-Analyse")
        self.find = QLineEdit(self); self.find.setPlaceholderText("🔍 Suchen …"); self.find.setClearButtonEnabled(True)
        lay.addWidget(self.find, 1)

    def bind(self, binding: FormBinding):
        self.binding = b = binding
        self.b_first.clicked.connect(b.first); self.b_prev.clicked.connect(b.previous)
        self.b_next.clicked.connect(b.next); self.b_last.clicked.connect(b.last)
        self.b_new.clicked.connect(b.new); self.b_save.clicked.connect(b.save); self.b_del.clicked.connect(b.delete)
        self.find.returnPressed.connect(lambda: b.search(self.find.text()))
        self.find.textChanged.connect(lambda t: t or b.search(""))
        save = QAction(self); save.setShortcut("Ctrl+S"); save.setShortcutContext(Qt.WindowShortcut); save.triggered.connect(b.save)
        self.window().addAction(save)
        b.changed.connect(self.update_state)
        self.update_state()

    def update_state(self):
        b = self.binding
        n = len(b.keys)
        if b.is_new:
            text = f"Neu · {n}"
        else:
            text = f"{b.pos + 1} / {n}" if n else "0 / 0"
        self.pos.setText(text + (" ✎" if b.dirty else "") + (" 🔍" if b.search_text else ""))
        self.b_first.setEnabled(b.pos > 0 or b.is_new); self.b_prev.setEnabled(b.pos > 0 and not b.is_new)
        self.b_next.setEnabled(0 <= b.pos < n - 1 and not b.is_new); self.b_last.setEnabled(n > 0)
        self.b_save.setEnabled(b.dirty or b.is_new); self.b_del.setEnabled(b.pos >= 0 or b.is_new)
