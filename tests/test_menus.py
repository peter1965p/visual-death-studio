"""Menüs Projekt, Erstellen, Hilfe: Build-Systeme, Projekteigenschaften, Dialoge – kein Platzhalter mehr."""
import json
import shutil

import pytest
from PySide6.QtWidgets import QMessageBox

from vds.app import MainWindow
from vds.build import projects
from vds.project import ProjectSettings
from vds.ui import dialogs
from conftest import needs


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    w = MainWindow()
    w.show()
    w.set_root(tmp_path)
    yield w
    w.docs.close_all(); w.close()


def wait_idle(w, pump):
    pump(lambda: w.runner.busy, 2)               # Start abwarten
    assert pump(lambda: not w.runner.busy, 30)


# --- Erkennung ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("marker,expect", [("CMakeLists.txt", "cmake"), ("Cargo.toml", "cargo"), ("go.mod", "go"), ("App.csproj", "dotnet"),
                                           ("pom.xml", "maven"), ("build.gradle", "gradle"), ("Makefile", "make"), ("pyproject.toml", "python")])
def test_detect_build_systems(tmp_path, marker, expect):
    (tmp_path / marker).write_text("x")
    bs = projects.detect(tmp_path)
    assert bs.id == expect and bs.build and all(cwd == tmp_path for _, cwd in bs.build)


def test_detect_npm_needs_build_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "x"}}))
    assert projects.detect(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))
    assert projects.detect(tmp_path).id == "npm"


def test_custom_command_beats_autodetection(tmp_path):
    (tmp_path / "Makefile").write_text("all:\n")
    bs = projects.detect(tmp_path, ProjectSettings(build_cmd="echo hi && echo ho", clean_cmd="rm -f x"))
    assert bs.id == "custom" and bs.build[0][0] == ["bash", "-c", "echo hi && echo ho"] and bs.clean


def test_missing_tool_is_reported(tmp_path):
    (tmp_path / "Cargo.toml").write_text("x")
    bs = projects.detect(tmp_path)
    bs.tool = "dieses-programm-gibt-es-nicht"
    assert bs.missing_tool() == "dieses-programm-gibt-es-nicht"


# --- Erstellen --------------------------------------------------------------------------------------------
@needs("make")
def test_build_project_with_makefile(win, pump, tmp_path):
    (tmp_path / "Makefile").write_text("all:\n\techo gebaut > ergebnis.txt\nclean:\n\trm -f ergebnis.txt\n")
    win.build_project()
    wait_idle(win, pump)
    assert (tmp_path / "ergebnis.txt").read_text().strip() == "gebaut"
    assert "Erstellen (Make)" in win.output.text.toPlainText()
    win.clean()
    wait_idle(win, pump)
    assert not (tmp_path / "ergebnis.txt").exists()
    win.rebuild_project()
    wait_idle(win, pump)
    assert (tmp_path / "ergebnis.txt").exists()


def test_custom_build_command_errors_land_in_error_list(win, pump, tmp_path):
    win.project.build_cmd = "echo 'prog.c:3:5: error: kaputt'; exit 1"
    win.build_project()
    wait_idle(win, pump)
    assert "Code 1" in win.output.text.toPlainText()
    rows = win.errors.sources["build"]
    assert rows[0][0] == "error" and rows[0][2] == str(tmp_path / "prog.c") and rows[0][3] == 3


def test_failed_step_stops_rebuild_chain(win, pump, tmp_path):
    win.project.build_cmd = "touch gebaut.txt"
    win.project.clean_cmd = "exit 3"
    win.rebuild_project()
    wait_idle(win, pump)
    assert not (tmp_path / "gebaut.txt").exists()


def test_cancel_build_kills_running_step(win, pump):
    win.project.build_cmd = "sleep 30"
    win.build_project()
    assert pump(lambda: win.runner.busy, 5) and win.a["cancelbuild"].isEnabled() and not win.a["build"].isEnabled()
    win.cancel_build()
    assert pump(lambda: not win.runner.busy, 10)
    assert "abgebrochen" in win.output.text.toPlainText() and win.a["build"].isEnabled()


def test_missing_toolchain_gives_install_hint(win, tmp_path):
    (tmp_path / "Cargo.toml").write_text("x")
    orig = shutil.which
    try:
        shutil.which = lambda n, *a, **k: None if n == "cargo" else orig(n, *a, **k)
        win.build_project()
    finally:
        shutil.which = orig
    assert "cargo" in win.output.text.toPlainText() and not win.runner.busy


# --- Projekt ----------------------------------------------------------------------------------------------
def test_set_startup_persists(win, tmp_path):
    (tmp_path / "app").mkdir()
    f = tmp_path / "app" / "main.py"; f.write_text("print(1)\n")
    win.docs.open(f)
    win.set_startup()
    assert json.loads((tmp_path / ".vds" / "project.json").read_text())["startup"] == "app/main.py"
    assert ProjectSettings.load(tmp_path).startup_path(tmp_path) == f


def test_project_properties_dialog_roundtrip(win, tmp_path):
    (tmp_path / "run.py").write_text("x")
    base = ProjectSettings(args="--a", env={"A": "1"})
    dlg = dialogs.ProjectPropertiesDialog(tmp_path, base)
    assert dlg.startup.findText("run.py") >= 0 and "A=1" in dlg.env.toPlainText()
    dlg.startup.setCurrentText("run.py"); dlg.args.setText("--b  x"); dlg.env.setPlainText("K=v\nkaputt\nL = 2")
    dlg.build.setText("make"); dlg.clean.setText("make clean")
    r = dlg.result_settings(base)
    assert (r.startup, r.args, r.env, r.build_cmd, r.clean_cmd) == ("run.py", "--b  x", {"K": "v", "L": "2"}, "make", "make clean")


def test_project_files_skip_build_and_dependency_dirs(tmp_path):
    for p in ("a.py", "src/b.py", "node_modules/x.js", ".venv/y.py", "target/z.rs"):
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True); (tmp_path / p).write_text("x")
    assert dialogs.project_files(tmp_path) == ["a.py", "src/b.py"]


def test_add_existing_item_copies_into_project(win, tmp_path, monkeypatch):
    src = tmp_path.parent / "fremd.txt"; src.write_text("hallo")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(src)], "")))
    win.add_existing_item()
    assert (tmp_path / "fremd.txt").read_text() == "hallo"


# --- Hilfe -------------------------------------------------------------------------------------------------
def test_menus_have_real_content(win):
    titles = {a.text().replace("&", ""): a.menu() for a in win.menuBar().actions()}
    for name, must in {"Projekt": ["Eigenschaften…", "Als Startdatei festlegen", "Neuer Ordner…", "Vorhandenes Element hinzufügen…"],
                       "Erstellen": ["Projekt erstellen", "Projekt neu erstellen", "Projekt bereinigen", "Erstellen abbrechen"],
                       "Hilfe": ["Erste Schritte", "Tastenkürzel…", "Installierte Werkzeuge prüfen…", "Lizenz anzeigen", "Fehler melden…"]}.items():
        have = [a.text() for a in titles[name].actions()]
        for m in must:
            assert m in have, (name, m)


def test_shortcut_dialog_lists_real_shortcuts(win):
    dlg = dialogs.ShortcutsDialog(win.menuBar())
    rows = {dlg.table.item(r, 1).text(): dlg.table.item(r, 2).text() for r in range(dlg.table.rowCount())}
    assert rows["Projekt erstellen"] == "Ctrl+Shift+B" and rows["Debugging starten"] == "F5" and len(rows) > 40
    dlg.search.setText("f5")
    assert sum(not dlg.table.isRowHidden(r) for r in range(dlg.table.rowCount())) >= 2


def test_tool_report_finds_python_and_flags_missing(monkeypatch):
    rep = {name: path for name, _, path, _ in dialogs.tool_report()}
    assert rep["python3"]
    monkeypatch.setattr(dialogs.dbg_tools, "find", lambda n: None)
    assert not any(p for n, p in {n: p for n, _, p, _ in dialogs.tool_report()}.items() if n == "go")


def test_dialogs_construct(win):
    for dlg in (dialogs.GettingStartedDialog(win), dialogs.ToolCheckDialog(win), dialogs.TextDialog("t", "x", win)):
        assert dlg.windowTitle()


def test_window_menu_cycles_documents(win, tmp_path):
    for n in ("a.py", "b.py"):
        (tmp_path / n).write_text("x\n")
        win.docs.open(tmp_path / n)
    start = win.docs.currentIndex()
    win._cycle_doc(1)
    assert win.docs.currentIndex() != start
    win.a["closeall"].trigger()
    assert win.docs.count() == 0
