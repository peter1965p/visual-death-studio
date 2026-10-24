"""API-Schlüssel für den Anthropic-API-Modus. Er liegt nie in den Optionen, sondern in einer eigenen Datei (nur für den Benutzer lesbar);
alternativ gilt die Umgebungsvariable ANTHROPIC_API_KEY."""
import os
from pathlib import Path

from PySide6.QtCore import QSettings

from ..branding import SETTINGS_APP, SETTINGS_ORG


def key_file() -> Path:
    return Path(QSettings(SETTINGS_ORG, SETTINGS_APP).fileName()).parent / "api_key"


def saved() -> str:
    try:
        return key_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load() -> str:
    """Ein in der IDE gespeicherter Schlüssel hat Vorrang vor der Umgebungsvariablen."""
    return saved() or os.environ.get("ANTHROPIC_API_KEY", "").strip()


def source() -> str:
    return "gespeichert" if saved() else ("Umgebungsvariable ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY", "").strip() else "")


def save(key: str):
    key = key.strip()
    p = key_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)      # nie für andere lesbar, auch nicht kurz
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    os.chmod(p, 0o600)


def clear():
    try:
        key_file().unlink()
    except OSError:
        pass


def mask(key: str) -> str:
    return "" if not key else (key[:7] + "…" + key[-4:] if len(key) > 14 else "…" + key[-3:])
