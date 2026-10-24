"""Benutzer-Optionen (Extras → Optionen): ein Ort für Schlüssel, Standardwerte und Typumwandlung. Änderungen werden über `bus.changed` gemeldet."""
from PySide6.QtCore import QObject, QSettings, Signal

from .branding import SETTINGS_APP, SETTINGS_ORG

DEFAULTS = {
    # Editor
    "editor/tab_width": 4, "editor/use_spaces": True, "editor/word_wrap": False, "editor/whitespace": False,
    "editor/autosave_seconds": 0, "editor/autosave_on_focus_loss": False,
    # IntelliSense
    "intellisense/auto": True, "intellisense/min_chars": 2, "intellisense/delay_ms": 60,
    # Designer
    "designer/grid": 8, "designer/snap": True, "designer/show_grid": True,
    # Claude: Anbieter "cli" (lokale Claude-Code-Anmeldung) oder "api" (eigener API-Schlüssel)
    "claude/provider": "cli",
    "claude/api_model": "claude-opus-5-5", "claude/api_completion_model": "claude-haiku-5-5", "claude/api_base_url": "",
    "claude/api_max_tokens": 32000, "claude/api_effort": "", "claude/api_fallbacks": True,
    "ai/completion_model": "haiku",                 # Modell der Claude-CLI für die Vervollständigung
}
CHOICES = {"claude/provider": ("cli", "api"), "claude/api_effort": ("", "low", "medium", "high", "xhigh", "max")}
LIMITS = {"editor/tab_width": (1, 16), "editor/autosave_seconds": (0, 3600), "intellisense/min_chars": (1, 6), "intellisense/delay_ms": (0, 2000),
          "designer/grid": (2, 64), "claude/api_max_tokens": (256, 128000)}


class _Bus(QObject):
    changed = Signal(str)


bus = _Bus()


def _store() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def _coerce(key: str, value):
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return value in (True, "true", "True", "1", 1)
    if isinstance(default, int):
        try:
            v = int(value)
        except (TypeError, ValueError):
            return default
        lo, hi = LIMITS.get(key, (v, v))
        return min(max(v, lo), hi)
    v = str(value if value is not None else default)
    return v if key not in CHOICES or v in CHOICES[key] else default


def get(key: str):
    return _coerce(key, _store().value(key, DEFAULTS[key]))


def set(key: str, value):                                   # noqa: A001 – bewusst wie QSettings.setValue
    value = _coerce(key, value)
    s = _store()
    if s.contains(key) and _coerce(key, s.value(key)) == value:
        return
    s.setValue(key, value)
    s.sync()
    bus.changed.emit(key)


def reset(keys=None):
    s = _store()
    for k in list(keys or DEFAULTS):
        if s.contains(k):
            s.remove(k)
            bus.changed.emit(k)


def export_all() -> dict:
    """Alle Optionen als Wörterbuch (ohne Geheimnisse – der API-Schlüssel liegt nie in den Optionen)."""
    out = {k: get(k) for k in DEFAULTS}
    ef = _store().value("editor_font")
    if ef:
        out["editor_font"] = str(ef)
    return out


def import_all(data: dict) -> int:
    n = 0
    for k, v in data.items():
        if k in DEFAULTS:
            set(k, v); n += 1
        elif k == "editor_font" and isinstance(v, str):
            _store().setValue("editor_font", v); bus.changed.emit(k); n += 1
    return n
