"""Web-Seite der Vorschau: spritzt inject.js ein, trennt IDE-Nachrichten (`__VDS__…`) von normalen Konsolenmeldungen."""
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript

PREFIX = "__VDS__"
SCRIPT = (Path(__file__).parent / "inject.js").read_text(encoding="utf-8")
LEVELS = {0: "info", 1: "warning", 2: "error"}


def install_script(profile_or_page):
    s = QWebEngineScript()
    s.setName("vds-inject"); s.setSourceCode(SCRIPT)
    s.setInjectionPoint(QWebEngineScript.DocumentReady)
    s.setWorldId(QWebEngineScript.MainWorld)
    s.setRunsOnSubFrames(False)
    profile_or_page.scripts().insert(s)


class PreviewPage(QWebEnginePage):
    toolMessage = Signal(str, dict)                 # Art (ready|pick|hover|changed|text), Daten
    consoleMessage = Signal(str, str, int, str)     # Stufe, Text, Zeile, Quelle

    def __init__(self, profile=None, parent=None):
        super().__init__(profile, parent) if profile else super().__init__(parent)
        install_script(self)

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith(PREFIX):
            try:
                m = json.loads(message[len(PREFIX):])
                self.toolMessage.emit(m["k"], m.get("d") or {})
            except (ValueError, KeyError):
                pass
            return
        self.consoleMessage.emit(LEVELS.get(int(getattr(level, "value", level)), "info"), message, line, source)

    def certificateError(self, error):                # lokale Dev-Server mit selbstsigniertem Zertifikat (https) zulassen
        error.acceptCertificate()
        return True
