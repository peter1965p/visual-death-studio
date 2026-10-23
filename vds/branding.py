"""Name und Icon der Anwendung an einer Stelle."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

APP_NAME = "Visual Death Studio"
SETTINGS_ORG = SETTINGS_APP = "VisualDeathStudio"
DESKTOP_ID = "visual-death-studio"
ICON_SVG = Path(__file__).parent / "assets" / "icon.svg"


def app_icon() -> QIcon:
    """Icon in mehreren Größen aus dem SVG gerendert (scharf auf Titelleiste, Taskleiste und Dock)."""
    icon, renderer = QIcon(), QSvgRenderer(str(ICON_SVG))
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        icon.addPixmap(pm)
    return icon


def _data_home() -> Path:
    import os
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_entry_path() -> Path:
    return _data_home() / "applications" / f"{DESKTOP_ID}.desktop"


def desktop_entry_exists() -> bool:
    """Ohne passende .desktop-Datei lehnt das Desktop-Portal die Anmeldung der App-ID ab (Warnung beim Start)."""
    return desktop_entry_path().exists() or Path(f"/usr/share/applications/{DESKTOP_ID}.desktop").exists()


def install_desktop_entry() -> Path:
    """Legt Starter und Icon im Benutzerverzeichnis an (~/.local/share), damit die App im Anwendungsmenü erscheint."""
    import shutil
    import sys
    root = Path(__file__).resolve().parent.parent
    icon_dir = _data_home() / "icons" / "hicolor" / "scalable" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON_SVG, icon_dir / f"{DESKTOP_ID}.svg")
    entry = desktop_entry_path()
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "[Desktop Entry]\nType=Application\n"
        f"Name={APP_NAME}\nComment=IDE mit Formular-Designer, Paket-Manager und Claude-Anbindung\n"
        f"Exec={sys.executable} {root / 'run.py'}\nPath={root}\nIcon={DESKTOP_ID}\n"
        f"Terminal=false\nCategories=Development;IDE;\nStartupWMClass={DESKTOP_ID}\n", encoding="utf-8")
    return entry
