"""Selbsttest nach dem Bauen: Syntax- und Importfehler finden, Ablauf im Assistenten (Claude korrigiert bis zu zweimal)."""
import shutil
import time

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from vds.projects import selftest as st
from vds.projects.templates import BY_ID
from vds.projects.wizard import NewProjectDialog


def write(root, rel, text):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def test_python_syntax_and_skipped_folders(tmp_path):
    write(tmp_path, "ok.py", "x = 1\n")
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/kaputt.py", "def f(:\n    pass\n")
    write(tmp_path, ".venv/lib/fremd.py", "def f(:\n")                  # fremder Code wird nie geprüft
    errs = st.check_project(tmp_path, "python")
    assert len(errs) == 1 and errs[0].startswith("pkg/kaputt.py:1: Syntaxfehler")


def test_import_errors_are_found_grouped_and_missing_packages_ignored(tmp_path):
    write(tmp_path, "app/__init__.py", "")
    write(tmp_path, "app/win.py", "from PySide6.QtGui import QFileSystemModel\n")                 # der echte Fehler vom Dateimanager
    write(tmp_path, "app/main.py", "from . import win\n")
    write(tmp_path, "main.py", "from app import main\n")
    write(tmp_path, "tool.py", "import gibt_es_garantiert_nicht_paket\n")                        # nicht installiertes Fremdpaket: kein Projektfehler
    errs = st.check_project(tmp_path, "python")
    assert len(errs) == 1                                                                         # eine Ursache, einmal gemeldet
    assert "cannot import name 'QFileSystemModel'" in errs[0] and "app/win.py:1" in errs[0] and "betrifft" in errs[0]
    assert not any("gibt_es_garantiert" in e for e in errs)


def test_clean_project_passes_and_tests_are_not_imported(tmp_path):
    write(tmp_path, "main.py", "import os\n\ndef main():\n    return os.getcwd()\n\nif __name__ == '__main__':\n    main()\n")
    write(tmp_path, "tests/test_x.py", "import pytest_gibt_es_nicht\n")
    assert st.check_project(tmp_path, "python") == []
    assert st.module_names(tmp_path) == ["main"]


def test_hanging_module_is_not_an_error(tmp_path, monkeypatch):
    write(tmp_path, "main.py", "import time\ntime.sleep(30)\n")                                   # startet beim Import die Anwendung
    assert st.python_imports(tmp_path, st.sys.executable, timeout=2) == []


@pytest.mark.skipif(not shutil.which("php"), reason="php fehlt")
def test_php_syntax_ignores_vendor(tmp_path):
    write(tmp_path, "composer.json", "{}")
    write(tmp_path, "app/Ok.php", "<?php\necho 1;\n")
    write(tmp_path, "app/Bad.php", "<?php\nfunction f( {\n")
    write(tmp_path, "vendor/x/Bad.php", "<?php\nfunction f( {\n")
    errs = st.check_project(tmp_path, "php")
    assert len(errs) == 1 and errs[0].startswith("app/Bad.php:") and "Syntaxfehler" in errs[0]


@pytest.mark.skipif(not shutil.which("javac"), reason="javac fehlt")
def test_swing_compile_errors(tmp_path):
    write(tmp_path, "Form1.java", "public class Form1 { void f() { int x = \"text\"; } }\n")
    errs = st.check_project(tmp_path, "java", "java-swing")
    assert errs and "Form1.java:1" in errs[0]
    write(tmp_path, "Form1.java", "public class Form1 { void f() { int x = 1; } }\n")
    assert st.check_project(tmp_path, "java", "java-swing") == []


def test_unknown_project_type_and_fix_prompt(tmp_path):
    write(tmp_path, "readme.txt", "nix")
    assert st.check_project(tmp_path) == [] and st.detect(tmp_path) == ""
    p = st.fix_prompt("Demo", ["a.py:3: Syntaxfehler: x", "Import schlägt fehl: y"])
    assert "'Demo'" in p and "- a.py:3: Syntaxfehler: x" in p and "MAIN:" in p


# --- Ablauf im Assistenten ------------------------------------------------------------------------------
BAD = "from PySide6.QtGui import QFileSystemModel\n"
GOOD = "from PySide6.QtWidgets import QFileSystemModel\n"


@pytest.fixture
def dlg(qapp, tmp_path, monkeypatch):
    from vds.ai import backend
    monkeypatch.setattr(backend, "available", lambda: True)
    d = NewProjectDialog(None, tmp_path)
    d.tpl = BY_ID["app"]; d.name.setText("Demo"); d.location.setText(str(tmp_path))
    d._go(2); d.app.setCurrentIndex(d.app.findData("filemanager")); d.tech.setCurrentIndex(d.tech.findData("py-qt"))
    d.checks["venv"].setChecked(False)
    d.prompts = []
    return d


def fake_claude(d, tmp_path, texts):
    """Claude schreibt nacheinander die Fassungen aus 'texts' nach demo_mod.py; ist die Liste leer, ändert er nichts mehr."""
    def run(prompt, root, **kw):
        d.prompts.append(prompt)
        if texts:
            (root / "demo_mod.py").write_text(texts.pop(0), encoding="utf-8")
        QTimer.singleShot(0, lambda: d._ai_finished(True, "fertig\nMAIN: demo_mod.py", ""))
    d.claude.run = run


def wait(cond, ms=30000):
    end = time.time() + ms / 1000
    while not cond() and time.time() < end:
        QTest.qWait(30)
    return cond()


def test_wizard_sends_found_errors_back_to_claude_and_finishes(dlg, tmp_path):
    fake_claude(dlg, tmp_path, [BAD, GOOD])
    dlg._create()
    assert wait(lambda: dlg.prog_title.text() == "Projekt erstellt")
    assert len(dlg.prompts) == 2 and "QFileSystemModel" in dlg.prompts[1] and "Selbsttest" in dlg.prompts[1]
    assert dlg._fix_rounds == 1 and dlg.next.isEnabled() and dlg.bar.value() == 1
    assert "✗" in dlg.ai_log.toPlainText() and "✓ Selbsttest bestanden" in dlg.ai_log.toPlainText()
    assert any("nach 1 Korrektur" in l for l in dlg.result_data[2])


def test_wizard_gives_up_after_two_rounds_but_project_stays_openable(dlg, tmp_path):
    fake_claude(dlg, tmp_path, [BAD, BAD, BAD])
    dlg._create()
    assert wait(lambda: "meldet noch Fehler" in dlg.prog_title.text())
    assert len(dlg.prompts) == 3 and dlg._fix_rounds == 2 and dlg.next.isEnabled() and dlg.result_data is not None
    assert any("noch offene Fehler" in l for l in dlg.result_data[2])


def test_wizard_clean_build_needs_no_fix_round(dlg, tmp_path):
    fake_claude(dlg, tmp_path, [GOOD])
    dlg._create()
    assert wait(lambda: dlg.prog_title.text() == "Projekt erstellt")
    assert len(dlg.prompts) == 1 and dlg._fix_rounds == 0


def test_check_can_be_skipped(dlg, tmp_path, monkeypatch):
    monkeypatch.setattr("vds.projects.wizard.selftest.check_project", lambda *a, **k: (time.sleep(1.0), [])[1])
    fake_claude(dlg, tmp_path, [GOOD])
    dlg._create()
    assert wait(lambda: dlg._check_token != 0)
    dlg._cancel()
    assert dlg.cancel.text() == "Schließen" and "übersprungen" in dlg.prog_sub.text() and dlg.next.isEnabled()
    QTest.qWait(1300)                                                                           # spätes Ergebnis darf nichts mehr ändern
    assert "übersprungen" in dlg.prog_sub.text() and len(dlg.prompts) == 1
