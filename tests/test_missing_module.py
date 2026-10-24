"""Fehlende Python-Pakete: Assistent installiert requirements.txt ins neue .venv; Debugger bietet bei ModuleNotFoundError die Installation an."""
import os
import subprocess
import time
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from vds import options
from vds.app import MainWindow
from vds.projects import templates
from vds.projects.templates import BY_ID
from vds.projects.wizard import NewProjectDialog

FAKE_PY = """#!/bin/sh
echo "FAKE-PIP $@"
[ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"
exit ${FAKE_EXIT:-0}
"""


@pytest.fixture
def fake_venv(monkeypatch):
    """Statt eines echten venv (Netz, Minuten) legt 'python -m venv' ein Skript als .venv/bin/python an."""
    real = subprocess.run

    def run(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[1:3] == ["-m", "venv"]:
            exe = Path(kw["cwd"]) / ".venv/bin/python"
            exe.parent.mkdir(parents=True); exe.write_text(FAKE_PY); exe.chmod(0o755)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real(cmd, *a, **kw)
    monkeypatch.setattr(templates.subprocess, "run", run)


def dialog(tmp_path, tid="py-fastapi"):
    d = NewProjectDialog(None, tmp_path)
    d.tpl = BY_ID[tid]; d.name.setText("Proj"); d.location.setText(str(tmp_path))
    d._go(2)
    d.checks["venv"].setChecked(True)
    return d


def wait(cond, ms=10000):
    end = time.time() + ms / 1000
    while not cond() and time.time() < end:
        QTest.qWait(30)
    return cond()


def test_wizard_installs_requirements_into_new_venv(qapp, tmp_path, fake_venv):
    d = dialog(tmp_path)
    d._create()
    assert d.pip is not None and "installiert" in d.prog_title.text() and not d.next.isEnabled()
    assert wait(lambda: d.pip is None)
    assert "FAKE-PIP -m pip install --disable-pip-version-check -r requirements.txt" in d.ai_log.toPlainText()
    assert d.prog_title.text() == "Projekt erstellt" and d.next.isEnabled() and d.bar.value() == 1
    assert any("Python-Pakete" in l and "installiert" in l for l in d.result_data[2])


def test_wizard_install_failure_keeps_project_openable(qapp, tmp_path, fake_venv, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    d = dialog(tmp_path)
    d._create()
    assert wait(lambda: d.pip is None)
    assert "Pakete fehlen" in d.prog_title.text() and d.next.isEnabled() and d.result_data is not None
    assert any("nicht installiert werden" in l for l in d.result_data[2])


def test_wizard_install_can_be_skipped(qapp, tmp_path, fake_venv, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "20")
    d = dialog(tmp_path)
    d._create()
    assert d.pip is not None and d.cancel.text() == "Überspringen"
    t0 = time.time(); d._cancel()
    assert time.time() - t0 < 5 and d.pip is None and d.next.isEnabled() and "übersprungen" in d.result_data[2][-1]


def test_no_install_without_requirements_or_venv(qapp, tmp_path, fake_venv):
    d = dialog(tmp_path, "py-console")                      # requirements.txt ist leer
    d._create()
    assert d.pip is None and d.result() == QDialog.Accepted
    d2 = dialog(tmp_path, "py-fastapi")
    d2.checks["venv"].setChecked(False)                      # ohne .venv-Option wird nichts installiert
    d2.name.setText("Proj2"); d2._create()
    assert d2.pip is None and d2.result() == QDialog.Accepted


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    options.reset()
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    yield w
    w.docs.close_all(); w.close(); options.reset()


def test_debugger_reports_missing_module_and_offers_install(win, monkeypatch):
    got, offered, stopped = [], [], []
    win.dbg.moduleMissing.connect(got.append)
    win.dbg._on_paused("exception", "ModuleNotFoundError: No module named 'PySide6.QtFoo'")
    win.dbg._on_paused("exception", "ValueError: kaputt")
    win.dbg._on_paused("breakpoint", "")
    assert got == ["PySide6"]
    monkeypatch.setattr(win.dbg, "stop", lambda: stopped.append(1))
    monkeypatch.setattr(win, "_offer_install", offered.append)
    win._debug_module_missing("PySide6")
    assert stopped == [1] and offered == ["PySide6"]
