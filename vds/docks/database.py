"""Datenbank-Explorer: SQLite-Dateien, MySQL/MariaDB, PostgreSQL und ODBC über Qt SQL – Tabellen und Spalten, SQL ausführen, Ergebnisse ansehen."""
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtSql import QSql, QSqlDatabase, QSqlQuery, QSqlQueryModel
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QSplitter, QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

DRIVERS = {"SQLite": "QSQLITE", "MySQL / MariaDB": "QMYSQL", "PostgreSQL": "QPSQL", "ODBC": "QODBC"}
DEFAULT_PORT = {"QMYSQL": 3306, "QPSQL": 5432}
DB_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db3")
_ids = itertools.count(1)


@dataclass
class Connection:
    name: str = ""
    driver: str = "QSQLITE"
    database: str = ""
    host: str = ""
    port: int = 0
    user: str = ""
    password: str = ""          # wird nie gespeichert

    def label(self) -> str:
        return self.name or (Path(self.database).name if self.driver == "QSQLITE" else f"{self.user}@{self.host}/{self.database}")


def open_db(c: Connection) -> tuple:
    """(QSqlDatabase | None, Fehlertext)."""
    if c.driver not in QSqlDatabase.drivers():
        return None, f"Der Qt-Treiber {c.driver} ist nicht installiert."
    if c.driver == "QSQLITE" and not Path(c.database).is_file():
        return None, f"Die Datei {c.database} gibt es nicht."          # sonst würde SQLite leise eine leere Datei anlegen
    db = QSqlDatabase.addDatabase(c.driver, f"vds-db-{next(_ids)}")
    db.setDatabaseName(c.database)
    if c.driver != "QSQLITE":
        db.setHostName(c.host); db.setUserName(c.user); db.setPassword(c.password)
        if c.port:
            db.setPort(c.port)
    if not db.open():
        err = db.lastError().text()
        name = db.connectionName()
        db = None
        QSqlDatabase.removeDatabase(name)
        return None, err or "Verbindung fehlgeschlagen."
    return db, ""


def close_db(db: QSqlDatabase):
    name = db.connectionName()
    db.close()
    del db
    QSqlDatabase.removeDatabase(name)


def schema(db: QSqlDatabase) -> list:
    """[(Name, 'Tabelle'|'Sicht', [(Spalte, Typ, Primärschlüssel)])]"""
    out = []
    for kind, flag in (("Tabelle", QSql.Tables), ("Sicht", QSql.Views)):
        for t in db.tables(flag):
            pk = {db.primaryIndex(t).fieldName(i) for i in range(db.primaryIndex(t).count())}
            rec = db.record(t)
            q = QSqlQuery(db)
            types = {}
            if db.driverName() == "QSQLITE" and q.exec(f'PRAGMA table_info("{t}")'):
                while q.next():
                    types[q.value(1)] = q.value(2)
            cols = [(rec.fieldName(i), types.get(rec.fieldName(i)) or rec.field(i).metaType().name(), rec.fieldName(i) in pk) for i in range(rec.count())]
            out.append((t, kind, cols))
    return out


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def find_databases(root: Path) -> list:
    found = []
    for p in sorted(Path(root).rglob("*")):
        if p.suffix.lower() in DB_SUFFIXES and p.is_file() and not any(x in p.parts for x in ("venv", ".venv", "node_modules", ".git")):
            found.append(p)
        if len(found) >= 50:
            break
    return found


class ConnectDialog(QDialog):
    def __init__(self, parent=None, start: Connection | None = None):
        super().__init__(parent)
        self.setWindowTitle("Mit Datenbank verbinden")
        c = start or Connection()
        self.driver = QComboBox()
        for label, drv in DRIVERS.items():
            self.driver.addItem(label, drv)
        self.driver.setCurrentIndex(max(0, self.driver.findData(c.driver)))
        self.database, self.host, self.user, self.password = QLineEdit(c.database), QLineEdit(c.host or "localhost"), QLineEdit(c.user), QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.port = QSpinBox(); self.port.setRange(0, 65535); self.port.setSpecialValueText("Standard"); self.port.setValue(c.port)
        browse = QPushButton("…"); browse.setFixedWidth(32); browse.clicked.connect(self._browse)
        row = QHBoxLayout(); row.addWidget(self.database, 1); row.addWidget(browse)
        f = QFormLayout(self)
        f.addRow("Typ", self.driver); f.addRow("Datenbank / Datei", row); f.addRow("Server", self.host); f.addRow("Port", self.port)
        f.addRow("Benutzer", self.user); f.addRow("Kennwort", self.password)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.driver.currentIndexChanged.connect(self._toggle); self._toggle()

    def _toggle(self):
        sqlite = self.driver.currentData() == "QSQLITE"
        for w in (self.host, self.port, self.user, self.password):
            w.setEnabled(not sqlite)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "SQLite-Datei", self.database.text(), "SQLite (*.db *.sqlite *.sqlite3 *.db3);;Alle Dateien (*)")
        if p:
            self.database.setText(p)

    def connection(self) -> Connection:
        return Connection("", self.driver.currentData(), self.database.text().strip(), self.host.text().strip(), self.port.value(), self.user.text().strip(), self.password.text())


class DatabasePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.db: QSqlDatabase | None = None
        self.conn: Connection | None = None
        self.combo = QComboBox(); self.combo.setMinimumWidth(220)
        self.b_connect, self.b_close, self.b_run = QPushButton("Verbinden…"), QPushButton("Trennen"), QPushButton("Ausführen (Strg+Enter)")
        self.b_connect.clicked.connect(self.connect_dialog); self.b_close.clicked.connect(self.disconnect)
        self.b_run.clicked.connect(self.execute)
        self.combo.activated.connect(self._pick)
        self.info = QLabel("Nicht verbunden."); self.info.setObjectName("sub"); self.info.setWordWrap(True)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Objekte", "Typ"]); self.tree.itemDoubleClicked.connect(self._select_all)
        self.sql = QPlainTextEdit(); self.sql.setPlaceholderText("SQL eingeben – Strg+Enter führt den markierten Text bzw. alles aus")
        self.sql.setFixedHeight(90)
        self.sql.keyPressEvent = self._sql_key(self.sql.keyPressEvent)
        self.table = QTableView(); self.table.setAlternatingRowColors(True); self.table.setSortingEnabled(True)
        self.model = QSqlQueryModel(self); self.proxy = QSortFilterProxyModel(self); self.proxy.setSourceModel(self.model); self.table.setModel(self.proxy)
        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.sql); rl.addWidget(self.b_run); rl.addWidget(self.table, 1)
        sp = QSplitter(); sp.addWidget(self.tree); sp.addWidget(right); sp.setStretchFactor(1, 3)
        top = QHBoxLayout(); top.addWidget(self.combo, 1); top.addWidget(self.b_connect); top.addWidget(self.b_close)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(top); lay.addWidget(self.info); lay.addWidget(sp, 1)
        self._fill_combo()

    def _sql_key(self, orig):
        def handler(ev):
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ControlModifier:
                return self.execute()
            orig(ev)
        return handler

    # --- Verbindungen ---------------------------------------------------------------
    def set_root(self, root: Path):
        self.root = Path(root)
        self._fill_combo()

    def _saved_path(self) -> Path:
        return self.root / ".vds" / "db.json"

    def _saved(self) -> list:
        try:
            return [Connection(**d) for d in json.loads(self._saved_path().read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def _remember(self, c: Connection):
        if self.root == Path(".") or not self.root.is_dir():
            return
        items = [x for x in self._saved() if (x.driver, x.database, x.host) != (c.driver, c.database, c.host)]
        items.insert(0, Connection(**{**asdict(c), "password": ""}))
        self._saved_path().parent.mkdir(parents=True, exist_ok=True)
        self._saved_path().write_text(json.dumps([asdict(i) for i in items[:20]], indent=2), encoding="utf-8")

    def _fill_combo(self):
        self.combo.clear()
        self._entries: list = []
        for c in self._saved():
            self._entries.append(c); self.combo.addItem(c.label())
        known = {c.database for c in self._entries}
        if self.root.is_dir() and self.root != Path("."):
            for p in find_databases(self.root):
                if str(p) not in known:
                    self._entries.append(Connection("", "QSQLITE", str(p))); self.combo.addItem(f"{p.relative_to(self.root)}  (im Projekt)")
        self.combo.setCurrentIndex(-1)

    def _pick(self, i):
        if 0 <= i < len(self._entries):
            c = self._entries[i]
            if c.driver != "QSQLITE" and not c.password:
                d = ConnectDialog(self, c)
                if d.exec() != QDialog.Accepted:
                    return
                c = d.connection()
            self.connect_to(c)

    def connect_dialog(self):
        d = ConnectDialog(self, self.conn)
        if d.exec() == QDialog.Accepted:
            self.connect_to(d.connection())

    def connect_to(self, c: Connection) -> bool:
        self.disconnect()
        db, err = open_db(c)
        if db is None:
            self.info.setText(f"Verbindung fehlgeschlagen: {err}")
            QMessageBox.warning(self, "Datenbank", err)
            return False
        self.db, self.conn = db, c
        self._remember(c)
        self.refresh()
        return True

    def disconnect(self):
        self.model.clear()
        self.tree.clear()
        if self.db is not None:
            close_db(self.db)
        self.db = self.conn = None
        self.info.setText("Nicht verbunden.")

    # --- Anzeige ----------------------------------------------------------------------
    def refresh(self):
        self.tree.clear()
        if self.db is None:
            return
        objs = schema(self.db)
        for name, kind, cols in objs:
            top = QTreeWidgetItem(self.tree, [name, kind])
            top.setData(0, Qt.UserRole, name)
            for cn, ct, pk in cols:
                QTreeWidgetItem(top, [("🔑 " if pk else "") + cn, ct])
        self.info.setText(f"Verbunden mit {self.conn.label()} · {len(objs)} Tabellen/Sichten (Doppelklick zeigt den Inhalt)")

    def _select_all(self, item, _col=0):
        name = item.data(0, Qt.UserRole)
        if name:
            self.sql.setPlainText(f"SELECT * FROM {quote(name)} LIMIT 200;")
            self.execute()

    def execute(self) -> bool:
        if self.db is None:
            self.info.setText("Erst mit einer Datenbank verbinden.")
            return False
        cur = self.sql.textCursor()
        text = (cur.selectedText().replace(" ", "\n") if cur.hasSelection() else self.sql.toPlainText()).strip().rstrip(";")
        if not text:
            return False
        q = QSqlQuery(self.db)
        if not q.exec(text):
            self.model.clear()
            self.info.setText("Fehler: " + q.lastError().text())
            return False
        if q.isSelect():
            self.model.setQuery(q)
            while self.model.canFetchMore():
                self.model.fetchMore()
            self.info.setText(f"{self.model.rowCount()} Zeile(n)")
        else:
            self.model.clear()
            self.info.setText(f"Erledigt, {max(q.numRowsAffected(), 0)} Zeile(n) betroffen.")
            self.refresh_keep_info()
        return True

    def refresh_keep_info(self):
        msg = self.info.text()
        self.refresh()
        self.info.setText(msg)
