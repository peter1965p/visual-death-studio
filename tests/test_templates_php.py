"""Projektvorlagen (React, Vue, Next, Nuxt, Java Swing, PHP), Start-Befehl der Projekteigenschaften und PHP-Unterstützung."""
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import needs
from vds.app import MainWindow
from vds.build.languages import lang_for, parse_problems
from vds.designer import targets
from vds.project import ProjectSettings
from vds.projects.templates import BY_ID, TEMPLATES, create_project
from vds.ui import dialogs

WEB = {"react-vite": ("src", "react", ".tsx"), "vue-vite": ("src", "vue", ".vue"), "next": ("components", "react", ".tsx"), "nuxt": ("components", "vue", ".vue")}


def make(tid, tmp_path, name="Mein App", **opts):
    return create_project(BY_ID[tid], name, tmp_path, {"git": False, "readme": True, **opts})


@pytest.mark.parametrize("tid", list(WEB))
def test_web_templates_create_designer_form_run_command_and_valid_package_json(tid, tmp_path):
    folder, target, ext = WEB[tid]
    root, main, log = make(tid, tmp_path)
    pkg = json.loads((root / "package.json").read_text())
    assert pkg["name"] == "mein-app" and "dev" in pkg["scripts"]                         # npm-tauglicher Name aus "Mein App"
    form = json.loads((root / folder / "Form1.form.json").read_text())
    assert form["target"] == target and form["title"] == "Mein App" and [c["type"] for c in form["controls"]] == ["Label", "Button"]
    assert (root / folder / f"Form1{ext}").exists() and main == root / folder / "Form1.form.json"
    assert ProjectSettings.load(root).run_cmd == "[ -d node_modules ] || npm install; npm run dev"
    assert "Mein App" in (root / ("app.vue" if tid == "nuxt" else "app/page.tsx" if tid == "next" else f"src/App{ext}")).read_text()


def test_java_swing_template_compiles_and_has_a_working_handler(tmp_path):
    root, main, log = make("java-swing", tmp_path, name="Fenster")
    assert main.name == "Form1.form.json" and {p.name for p in root.glob("*.java")} == {"Form1.java", "Form1Base.java"}
    user = (root / "Form1.java").read_text()
    assert "protected void button1Clicked()" in user and 'label1.setText("Button geklickt!");' in user
    if subprocess.run(["which", "javac"], capture_output=True).returncode == 0:
        r = subprocess.run(["javac", "-d", str(tmp_path / "out"), "Form1.java", "Form1Base.java"], cwd=root, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_template_catalog_has_all_new_entries_and_unique_ids():
    ids = [t.id for t in TEMPLATES]
    assert len(ids) == len(set(ids))
    assert {"react-vite", "vue-vite", "next", "nuxt", "java-swing", "php-console", "php-web"} <= set(ids)
    assert all(BY_ID[i].form_target for i in ("react-vite", "vue-vite", "next", "nuxt", "java-swing"))


def test_gitignore_for_web_and_php(tmp_path):
    root, *_ = make("react-vite", tmp_path, git=True)
    assert "node_modules/" in (root / ".gitignore").read_text() and "dist/" in (root / ".gitignore").read_text()
    root, *_ = make("php-web", tmp_path, git=True, name="Web")
    assert "vendor/" in (root / ".gitignore").read_text()


def test_wizard_lists_and_filters_new_templates(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from vds.projects.wizard import NewProjectDialog
    dlg = NewProjectDialog(None, tmp_path)
    ids = lambda: [dlg.list.item(i).data(Qt.UserRole).id for i in range(dlg.list.count())]
    assert {"react-vite", "vue-vite", "next", "nuxt", "java-swing", "php-web", "php-console"} <= set(ids())
    dlg.f_lang.setCurrentText("PHP")
    assert set(ids()) == {"php-console", "php-web"}
    dlg.f_lang.setCurrentIndex(0); dlg.search.setText("nuxt")
    assert ids() == ["nuxt"]


# --- PHP --------------------------------------------------------------------------------------------------
def test_php_language_and_problem_parsing():
    assert lang_for("index.php").id == "php" and lang_for("x.php").run == ["php", "{file}"]
    rows = parse_problems("PHP Parse error:  syntax error, unexpected end of file in /p/a.php on line 4\nWarning: Undefined variable $x in /p/b.php on line 7\n"
                          "Fatal error: Uncaught Error: Call to undefined function foo() in /p/c.php:3")
    assert rows[0] == ("error", "syntax error, unexpected end of file", "/p/a.php", 4, 1) and rows[1][0] == "warning" and rows[1][3] == 7


@needs("php")
def test_php_templates_are_valid_php_and_console_template_runs(tmp_path):
    root, main, _ = make("php-console", tmp_path, name="Hallo")
    assert subprocess.run(["php", "-l", str(main)], capture_output=True).returncode == 0
    assert subprocess.run(["php", str(main)], capture_output=True, text=True).stdout.strip() == "Hallo, Hallo!"
    web, *_ = make("php-web", tmp_path, name="Seite")
    for f in web.rglob("*.php"):
        assert subprocess.run(["php", "-l", str(f)], capture_output=True).returncode == 0, f


@needs("php")
def test_php_file_runs_through_the_ide_and_syntax_errors_reach_the_error_list(qapp, pump, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    ok, bad = tmp_path / "ok.php", tmp_path / "bad.php"
    ok.write_text("<?php echo 'fertig', PHP_EOL;\n"); bad.write_text("<?php\necho 'x'\n$y = ;\n")
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    try:
        w.docs.open(ok); w.run("buildrun")
        assert pump(lambda: "fertig" in w.output.text.toPlainText() and not w.runner.busy, 20)
        w.docs.open(bad); w.run("buildrun")
        assert pump(lambda: bool(w.errors.sources.get("build")) and not w.runner.busy, 20)
        row = w.errors.sources["build"][0]
        assert row[0] == "error" and row[2].endswith("bad.php") and row[3] >= 2
    finally:
        w.docs.close_all(); w.close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@needs("php")
def test_php_web_template_serves_through_the_start_command_and_stop_frees_the_port(qapp, pump, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    root, *_ = make("php-web", tmp_path, name="Seite")
    port = free_port()
    ProjectSettings(run_cmd=f"php -S 127.0.0.1:{port} -t public").save(root)
    w = MainWindow(); w.show(); w.set_root(root)
    try:
        w.dbg.start()                                                  # F5: Start-Befehl statt Debugger
        assert pump(lambda: w.runner.busy, 10)

        def page():
            try:
                return urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read().decode()
            except OSError:
                return ""
        assert pump(lambda: "Begrüßen" in page(), 20)
        w.stop_any()
        assert pump(lambda: not w.runner.busy, 20)
        time.sleep(0.5)
        assert page() == ""                                            # Server (Kindprozess) ist wirklich beendet
    finally:
        w.docs.close_all(); w.close()


# --- Start-Befehl --------------------------------------------------------------------------------------------
def test_run_command_replaces_file_run_and_ignores_build_only(qapp, pump, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    (tmp_path / "x.py").write_text("print('Datei')\n")
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    try:
        w.docs.open(tmp_path / "x.py")
        w.project.run_cmd = "echo Projektstart; pwd"
        w.run("buildrun")
        assert pump(lambda: "Projektstart" in w.output.text.toPlainText() and not w.runner.busy, 20)
        assert "Datei" not in w.output.text.toPlainText().replace("Projektstart", "") and str(tmp_path) in w.output.text.toPlainText()
        w.output.clear(); w.run("build")                               # nur Erstellen: kein Start-Befehl
        assert "Projektstart" not in w.output.text.toPlainText()
    finally:
        w.docs.close_all(); w.close()


def test_project_properties_dialog_has_run_command(qapp, tmp_path):
    base = ProjectSettings(run_cmd="npm run dev")
    dlg = dialogs.ProjectPropertiesDialog(tmp_path, base)
    assert dlg.run.text() == "npm run dev"
    dlg.run.setText("php -S 127.0.0.1:8000 -t public")
    assert dlg.result_settings(base).run_cmd == "php -S 127.0.0.1:8000 -t public"
