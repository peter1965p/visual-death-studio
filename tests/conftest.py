"""Gemeinsame Test-Infrastruktur: Qt offscreen, isolierte Einstellungen, Hilfsfunktionen zum Warten auf asynchrone Ereignisse."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    # Einstellungen in ein Wegwerf-Verzeichnis legen, die echten des Nutzers bleiben unberührt
    QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("settings")))
    from vds.theme import apply_palette, stylesheet
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_palette(app)
    app.setStyleSheet(stylesheet())
    return app


@pytest.fixture
def pump(qapp):
    def _pump(cond, secs=30.0):
        end = time.time() + secs
        while not cond() and time.time() < end:
            qapp.processEvents()
            time.sleep(0.01)
        return cond()
    return _pump


def needs(tool: str):
    import shutil
    return pytest.mark.skipif(shutil.which(tool) is None, reason=f"'{tool}' ist nicht installiert")
