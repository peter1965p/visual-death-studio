"""Web-Vorschau im Hauptfenster: Docks, Dev-Server-Adresse, Konsolenfehler, Neuladen, Designer-Verknüpfung und ein kompletter Durchlauf mit PHP."""
import json
import socket
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import needs
from vds import options
from vds.app import MainWindow
from vds.designer import codegen
from vds.project import ProjectSettings
from vds.web.inspector import WriteDialog


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    options.reset()
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    yield w
    w.docs.close_all(); w.close()
    options.reset()


def test_docks_menu_and_shortcuts(win):
    assert win.d_preview.windowTitle() == "Web-Vorschau" and win.d_inspector.windowTitle() == "Web-Element"
    assert win.d_preview in win.all_docks and win.d_inspector in win.all_docks
    view = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Ansicht")
    texts = [a.text() for a in view.actions()]
    for t in ("Web-Vorschau öffnen", "Web-Element auswählen", "Web-Seite visuell bearbeiten", "Web-Änderungen in den Quellcode übernehmen…"):
        assert t in texts
    assert win.a["webopen"].shortcut().toString() == "Ctrl+Alt+W"
    win.a["webopen"].trigger()
    assert win.d_preview.isVisible() and win.d_inspector.isVisible()
    win.a["webpick"].trigger(); assert win.preview.mode == "pick" and win.preview.btn_pick.isChecked()
    win.a["webedit"].trigger(); assert win.preview.mode == "edit" and not win.preview.btn_pick.isChecked()
    win.preview.set_mode("off")


def test_dev_server_url_in_the_output_opens_the_preview_once_per_run(win, monkeypatch):
    urls = []
    monkeypatch.setattr(win.preview, "set_url", lambda u: urls.append(u))
    win.runner.output.emit("> npm run dev\n", "info")
    win.runner.output.emit("  VITE v6  ready in 300 ms\n  ➜  Local:   http://localhost:5173/\n", "stdout")
    win.runner.output.emit("  ➜  Local:   http://localhost:9999/\n", "stdout")
    assert urls == ["http://localhost:5173/"] and win.d_preview.isVisible()
    win.runner.busyChanged.emit(True)                                              # neuer Lauf
    win.runner.output.emit("Server on http://127.0.0.1:8000\n", "stdout")
    assert urls == ["http://localhost:5173/", "http://127.0.0.1:8000"]
    options.set("web/auto_open", False)
    win.runner.busyChanged.emit(True)
    win.runner.output.emit("Server on http://127.0.0.1:7000\n", "stdout")
    assert len(urls) == 2                                                          # Option aus → nichts öffnen


def test_url_split_across_output_chunks_is_still_found(win, monkeypatch):
    urls = []
    monkeypatch.setattr(win.preview, "set_url", lambda u: urls.append(u))
    win.runner.output.emit("  ➜  Local:   http://local", "stdout")
    win.runner.output.emit("host:5173/\n", "stdout")
    assert urls == ["http://localhost:5173/"]


def test_browser_errors_land_in_the_error_list_with_project_files(win, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("x")
    win._web_console("info", "nur Info", 1, "http://localhost:5173/src/main.js")
    assert "web" not in win.errors.sources
    win._web_console("error", "Uncaught TypeError: x is undefined\n    at foo", 7, "http://localhost:5173/src/main.js?t=123")
    win._web_console("warning", "veraltet", 2, "http://localhost:5173/index.html")
    rows = win.errors.sources["web"]
    assert rows[0] == ("error", "Uncaught TypeError: x is undefined", str(tmp_path / "src" / "main.js"), 7, 1) and rows[1][0] == "warning"
    assert "[Browser] Uncaught TypeError" in win.output.text.toPlainText()
    win.preview.view.loadStarted.emit()                                            # neue Seite → alte Fehler weg
    assert "web" not in win.errors.sources


def test_saving_reloads_unless_there_are_unwritten_visual_changes(win, monkeypatch):
    calls = []
    monkeypatch.setattr(win.preview, "schedule_reload", lambda **k: calls.append(k))
    win.d_preview.show()
    win._web_saved(None)
    assert calls == [{"mode": "ohne-hmr"}]
    options.set("web/auto_reload", "nie"); win._web_saved(None); assert calls[-1] == {"mode": "nie"}
    win.inspector.pending["x"] = {"info": {}, "props": {"color": "red"}}
    n = len(calls); win._web_saved(None)
    assert len(calls) == n                                                         # ungeschriebene Änderungen werden nie weggeladen
    win.inspector.pending.clear()
    win.d_preview.hide(); win._web_saved(None); assert len(calls) == n               # unsichtbare Vorschau lädt nicht


def test_picking_a_designer_generated_element_selects_the_control(win, tmp_path):
    m = codegen.new_form("Seite", "react")
    codegen.write_files(tmp_path / "src" / "Seite.form.json", m) if (tmp_path / "src").mkdir() is None else None
    doc = win.docs.open(tmp_path / "src" / "Seite.form.json")
    doc.view.canvas.add_control("Button"); doc.view.canvas.add_control("Label"); doc.save()
    win.docs.close_all()
    win._select_designer_control("label1")
    cur = win.docs.current_doc()
    assert cur.kind == "form" and cur.view.canvas.sel == ["label1"]
    win._select_designer_control("gibtsnicht")
    assert "gibtsnicht" in win.statusBar().currentMessage()


def test_designer_generated_pages_carry_data_vds_for_every_control(tmp_path):
    from vds.designer.targets import web
    m = codegen.new_form("F", "react")
    m["controls"] = [{"type": "Button", "name": "button1", "x": 1, "y": 1, "w": 80, "h": 30, "props": {"text": "x"}},
                     {"type": "CheckBox", "name": "checkBox1", "x": 1, "y": 40, "w": 80, "h": 30, "props": {"text": "y"}}]
    src = web.react_source(m, "F")
    assert 'data-vds="button1"' in src and 'data-vds="checkBox1"' in src
    assert 'data-vds="button1"' in web.vue_source(m, "F")


def test_options_dialog_has_a_web_page(win):
    from vds.ui.options_dialog import OptionsDialog
    dlg = OptionsDialog(win)
    assert "Web-Vorschau" in [dlg.nav.item(i).text() for i in range(dlg.nav.count())]
    dlg.fields["web/auto_reload"][2]("immer"); dlg.fields["web/device"][2]("Tablet 768×1024"); dlg.fields["web/auto_open"][2](False)
    dlg.apply()
    assert options.get("web/auto_reload") == "immer" and options.get("web/auto_open") is False
    assert win.preview.device.currentText() == "Tablet 768×1024"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@needs("php")
def test_php_project_end_to_end_start_preview_pick_change_write_back(qapp, pump, tmp_path, monkeypatch):
    """F5 startet php -S, die IDE öffnet die Vorschau selbst, ein Klick wählt die Überschrift, die Farbe wird geändert und landet in style.css."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    monkeypatch.setattr(WriteDialog, "exec", lambda self: 1)
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.php").write_text('<?php $name = "Welt"; ?><!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/style.css"></head>'
                                                    '<body><h1 id="titel" class="kopf">Hallo <?= $name ?></h1><p class="info">Text</p></body></html>')
    css = tmp_path / "public" / "style.css"
    css.write_text(".kopf { color: rgb(51, 51, 51); }\n.info { margin: 0; }\n")
    port = free_port()
    ProjectSettings(run_cmd=f"php -S 127.0.0.1:{port} -t public").save(tmp_path)
    options.reset()
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    try:
        w.dbg.start()
        assert pump(lambda: w.d_preview.isVisible() and f":{port}" in w.preview.url.text(), 30)       # Adresse aus der php-Ausgabe erkannt
        assert pump(lambda: w.preview.page.url().toString().startswith(f"http://127.0.0.1:{port}"), 30)
        assert pump(lambda: "Hallo Welt" in (_text(w.preview, pump) or ""), 30)
        w.preview.set_mode("pick"); pump(lambda: False, 0.3)
        w.preview.eval("document.querySelector('#titel').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))")
        assert pump(lambda: w.inspector.info and w.inspector.info["id"] == "titel", 20)
        w.inspector.set_style("color", "#2255ff")
        assert pump(lambda: w.inspector.pending, 20)
        files = w.inspector.write_back()
        assert files == [str(css.resolve())] and "#2255ff" in css.read_text() and ".info { margin: 0; }" in css.read_text()
        w.preview.reload()
        assert pump(lambda: _computed(w.preview, pump, "#titel", "color") == "rgb(34, 85, 255)", 30)
        w.stop_any()
        assert pump(lambda: not w.runner.busy, 20)
    finally:
        w.docs.close_all(); w.close()


def _text(panel, pump):
    out = []
    panel.eval("document.body ? document.body.innerText : ''", lambda v: out.append(v))
    pump(lambda: bool(out), 5)
    return out[0] if out else ""


def _computed(panel, pump, sel, prop):
    out = []
    panel.eval(f"getComputedStyle(document.querySelector({json.dumps(sel)})).getPropertyValue({json.dumps(prop)})", lambda v: out.append(v))
    pump(lambda: bool(out), 5)
    return out[0] if out else ""


# --- Start-Befehl erkennen -------------------------------------------------------------------------------------------
def test_detect_command_for_laravel_vite_angular_and_nothing(tmp_path):
    from vds.web import devserver
    assert devserver.detect_command(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}})); assert devserver.detect_command(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    assert devserver.detect_command(tmp_path) == "[ -d node_modules ] || npm install; npm run dev"
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "ng serve"}}))
    assert devserver.detect_command(tmp_path).endswith("npm start")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}})); assert devserver.detect_command(tmp_path) is None
    (tmp_path / "artisan").write_text("#!/usr/bin/env php"); (tmp_path / "composer.json").write_text("{}")
    assert devserver.detect_command(tmp_path) == "php artisan serve"                  # Laravel hat Vorrang


def test_f5_uses_the_detected_dev_server_only_for_files_without_an_interpreter(qapp, pump, tmp_path, monkeypatch):
    import os, stat
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    log = tmp_path / "npm.log"
    (tmp_path / "bin").mkdir()
    npm = tmp_path / "bin" / "npm"
    npm.write_text(f'#!/usr/bin/env bash\necho "npm $@" >> {log}\n'); npm.chmod(npm.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    proj = tmp_path / "p"; (proj / "node_modules").mkdir(parents=True)
    (proj / "package.json").write_text('{"scripts": {"dev": "vite"}}')
    (proj / "index.html").write_text("<h1>x</h1>"); (proj / "tool.py").write_text("print('py')\n")
    w = MainWindow(); w.show(); w.set_root(proj)
    try:
        w.docs.open(proj / "tool.py"); w.run("buildrun")                              # Python-Datei: läuft selbst, kein npm
        assert pump(lambda: "py" in w.output.text.toPlainText() and not w.runner.busy, 20)
        assert not log.exists()
        w.docs.open(proj / "index.html"); w.run("buildrun")                           # HTML hat keinen Interpreter → Dev-Server des Projekts
        assert pump(lambda: log.exists() and not w.runner.busy, 20)
        assert log.read_text().splitlines() == ["npm run dev"]
        assert "Start-Befehl" in w.output.text.toPlainText()
    finally:
        w.docs.close_all(); w.close()


def test_bottom_dock_group_can_be_made_small_even_with_tall_tabs(win):
    """Eine Dock-Gruppe ist so hoch wie ihr höchster Reiter (früher Pakete mit 359 px): der Teiler ließ sich nicht nach unten ziehen."""
    for d in (win.d_output, win.d_packages, win.d_inspector, win.d_changes):
        assert d.minimumSizeHint().height() <= 130, d.windowTitle()
