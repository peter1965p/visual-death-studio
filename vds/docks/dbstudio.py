"""„In DB Studio bearbeiten“: die aktuelle Verbindung (optional mit Tabelle) in Pi DB Studio öffnen.

VDS baut die Anwendung, Pi DB Studio pflegt die Datenbank (Schema, ER-Diagramm mit Folgen-Analyse, Import, REST-API).
Übergeben werden nur Verbindungsangaben, nie ein Kennwort – das liegt in DB Studio im Schlüsselbund bzw. wird dort abgefragt.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
from pathlib import Path

PROJEKT = "https://github.com/peter1965p/pi-db-studio"
_ARTEN = {"QSQLITE": "sqlite", "QPSQL": "postgresql", "QMYSQL": "mysql"}


def verbindung(conn) -> dict | None:
    """VDS-Verbindung → Angaben für `dbstudio --verbindung` (None: Treiber kennt DB Studio nicht, z. B. ODBC)."""
    art = _ARTEN.get(conn.driver)
    if not art:
        return None
    if art == "sqlite":
        return {"art": art, "datei": str(Path(conn.database).expanduser().resolve()), "name": conn.name or Path(conn.database).name}
    d = {"art": art, "host": conn.host or "localhost", "datenbank": conn.database, "benutzer": conn.user}
    if conn.port:
        d["port"] = conn.port
    if conn.name:
        d["name"] = conn.name
    return d


def befehl() -> list[str] | None:
    """Wie DB Studio gestartet wird: VDS_DBSTUDIO, Programm im PATH, Desktop-Eintrag oder Quellordner ~/Dev/db-studio."""
    eigen = os.environ.get("VDS_DBSTUDIO")
    if eigen:
        return shlex.split(eigen)
    for name in ("db-studio", "pi-db-studio", "dbstudio"):
        p = shutil.which(name)
        if p:
            return [p]
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    for eintrag in (data / "applications" / "db-studio.desktop", Path("/usr/share/applications/db-studio.desktop")):
        try:
            for zeile in eintrag.read_text(encoding="utf-8").splitlines():
                if zeile.startswith("Exec="):
                    teile = [t for t in shlex.split(zeile[5:]) if not t.startswith("%")]
                    if teile and Path(teile[0]).exists():
                        return teile
        except OSError:
            pass
    quelle = Path.home() / "Dev" / "db-studio"
    py = quelle / "venv" / "bin" / "python"
    if (quelle / "dbstudio" / "__main__.py").is_file() and py.exists():
        return [str(py), "-m", "dbstudio"]
    return None


def argumente(conn, tabelle: str | None = None) -> list[str] | None:
    d = verbindung(conn)
    if d is None:
        return None
    out = ["--verbindung", json.dumps(d, ensure_ascii=False)]
    if tabelle:
        out += ["--tabelle", tabelle]
    return out


def starten(conn, tabelle: str | None = None) -> tuple[bool, str]:
    """(ok, Meldung). Startet DB Studio losgelöst von VDS."""
    from PySide6.QtCore import QProcess
    args = argumente(conn, tabelle)
    if args is None:
        return False, "Diese Verbindung (ODBC) kann Pi DB Studio nicht öffnen – unterstützt werden SQLite, PostgreSQL und MySQL/MariaDB."
    cmd = befehl()
    if not cmd:
        return False, f"Pi DB Studio wurde nicht gefunden. Installieren: {PROJEKT}\n(oder den Startbefehl in VDS_DBSTUDIO eintragen)"
    ok, _pid = QProcess.startDetached(cmd[0], cmd[1:] + args, str(Path.home()))
    return (True, "Pi DB Studio wird geöffnet …") if ok else (False, f"Start fehlgeschlagen: {' '.join(cmd)}")
