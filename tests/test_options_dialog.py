"""Extras → Optionen: Dialog und die Wirkung der Optionen auf Editor, IntelliSense, Designer, Autospeichern und Claude-Anbieter."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QPlainTextEdit

from fake_anthropic import FakeApi, sse
from vds import options
from vds.ai import keystore
from vds.app import MainWindow
from vds.ui.options_dialog import OptionsDialog


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    options.reset(); keystore.clear()
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    yield w
    w.docs.close_all(); w.close()
    options.reset(); keystore.clear()
    from vds.designer import canvas
    canvas.configure(8, True, True)


def test_options_menu_entry_exists(win):
    extras = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Extras")
    assert "Optionen…" in [a.text() for a in extras.actions()] and win.a["options"].shortcut().toString() == "Ctrl+,"


def test_dialog_loads_applies_and_resets(win):
    options.set("editor/tab_width", 2)
    dlg = OptionsDialog(win)
    assert dlg.fields["editor/tab_width"][0].value() == 2 and dlg.nav.count() == 6
    dlg.fields["editor/tab_width"][0].setValue(6)
    dlg.fields["editor/word_wrap"][0].setChecked(True)
    dlg.apply()
    assert options.get("editor/tab_width") == 6 and options.get("editor/word_wrap") is True
    options.reset(); dlg.load()
    assert dlg.fields["editor/tab_width"][0].value() == 4


def test_editor_options_take_effect_on_open_editors(win, tmp_path):
    f = tmp_path / "a.py"; f.write_text("def f():\n")
    ed = win.docs.open(f).view
    base = ed.tabStopDistance()
    options.set("editor/tab_width", 8)
    assert ed.tabStopDistance() == pytest.approx(base * 2)
    options.set("editor/word_wrap", True); assert ed.lineWrapMode() == QPlainTextEdit.WidgetWidth
    options.set("editor/whitespace", True); assert ed.document().defaultTextOption().flags() & QTextOption.ShowTabsAndSpaces
    options.set("editor/whitespace", False); assert not ed.document().defaultTextOption().flags() & QTextOption.ShowTabsAndSpaces
    # Tab-Taste und automatisches Einrücken folgen den Optionen
    ed.setPlainText(""); ed.setFocus()
    QTest.keyClick(ed, Qt.Key_Tab); assert ed.toPlainText() == " " * 8
    options.set("editor/use_spaces", False)
    ed.setPlainText(""); QTest.keyClick(ed, Qt.Key_Tab); assert ed.toPlainText() == "\t"
    options.set("editor/use_spaces", True); options.set("editor/tab_width", 3)
    ed.setPlainText("if x:"); c = ed.textCursor(); c.movePosition(c.MoveOperation.End); ed.setTextCursor(c)
    QTest.keyClick(ed, Qt.Key_Return); assert ed.toPlainText() == "if x:\n   "


def test_new_editors_pick_up_options_too(win, tmp_path):
    options.set("editor/word_wrap", True)
    f = tmp_path / "b.py"; f.write_text("x\n")
    assert win.docs.open(f).view.lineWrapMode() == QPlainTextEdit.WidgetWidth


def test_intellisense_auto_option(win, tmp_path):
    from vds.editor.code_editor import CodeEditor
    ed = win.docs.open(tmp_path.joinpath("c.py").write_text("") or tmp_path / "c.py").view
    started = []
    ed._ctimer.timeout.disconnect(); ed._ctimer.timeout.connect(lambda: started.append(1))
    ed.intel = object(); ed.doc_path = tmp_path / "c.py"
    ed.setFocus()
    options.set("intellisense/min_chars", 3)
    QTest.keyClicks(ed, "ab"); QTest.qWait(150); assert not started     # unter der Mindestlänge
    QTest.keyClicks(ed, "c"); QTest.qWait(150); assert started
    started.clear(); options.set("intellisense/auto", False)
    QTest.keyClicks(ed, "def"); QTest.qWait(150); assert not started   # automatisch aus
    options.set("intellisense/delay_ms", 400); assert ed._ctimer.interval() == 400


def test_designer_options_change_grid_and_snapping(win, tmp_path):
    from vds.designer import canvas
    from vds.designer.codegen import new_form
    import json as j
    (tmp_path / "F.form.json").write_text(j.dumps(new_form("F")))
    d = win.docs.open(tmp_path / "F.form.json")
    options.set("designer/grid", 16)
    assert canvas.GRID == 16 and d.view.canvas._grid(21) == 16 and d.view.canvas._grid(27) == 32
    options.set("designer/snap", False); assert canvas.SNAP_ON is False
    options.set("designer/show_grid", False); assert canvas.SHOW_GRID is False


def test_autosave_timer_and_focus_loss(win, tmp_path):
    f = tmp_path / "s.py"; f.write_text("a = 1\n")
    ed = win.docs.open(f).view
    ed.setPlainText("a = 2\n"); ed.document().setModified(True)
    assert win.docs.current_doc().modified
    win._autosave_tick(); assert f.read_text() == "a = 2\n"
    options.set("editor/autosave_seconds", 5); assert win._autosave.isActive() and win._autosave.interval() == 5000
    options.set("editor/autosave_seconds", 0); assert not win._autosave.isActive()
    ed.setPlainText("a = 3\n"); ed.document().setModified(True); win._app_state(Qt.ApplicationActive); assert f.read_text() == "a = 2\n"   # aktiv: nichts
    win._app_state(Qt.ApplicationInactive); assert f.read_text() == "a = 2\n"                              # Option aus: nichts
    options.set("editor/autosave_on_focus_loss", True)
    win._app_state(Qt.ApplicationInactive); assert f.read_text() == "a = 3\n"


def test_claude_page_toggles_providers_and_stores_key(win):
    dlg = OptionsDialog(win)
    assert dlg.r_auto.isChecked() and dlg.cli_box.isEnabled() and dlg.api_box.isEnabled()
    dlg.r_cli.setChecked(True)
    assert dlg.cli_box.isEnabled() and not dlg.api_box.isEnabled()
    dlg.r_api.setChecked(True)
    assert dlg.api_box.isEnabled() and not dlg.cli_box.isEnabled()
    dlg.key.setText("  sk-ant-api03-geheim-abcdefgh  ")
    dlg.fields["claude/api_model"][2]("claude-sonnet-5-5")
    dlg.apply()
    assert options.get("claude/provider") == "api" and options.get("claude/api_model") == "claude-sonnet-5-5"
    assert keystore.load() == "sk-ant-api03-geheim-abcdefgh" and dlg.key.text() == "" and "geheim" not in dlg.key_status.text()
    assert "abcdefgh"[-4:] in dlg.key_status.text()
    dlg._clear_key(); assert keystore.load() == "" and "Kein Schlüssel" in dlg.key_status.text()


def test_switching_provider_in_options_swaps_the_chat_agent(win):
    from vds.ai.agent import ApiAgent
    assert type(win.chat.claude).__name__ == "ClaudeProcess"
    keystore.save("sk-x"); options.set("claude/provider", "api")
    assert isinstance(win.chat.claude, ApiAgent)
    options.set("claude/provider", "cli"); assert type(win.chat.claude).__name__ == "ClaudeProcess"


def test_connection_test_button(win, pump):
    f = FakeApi([sse([("text", "OK")]), (401, {"type": "error", "error": {"type": "authentication_error", "message": "bad key"}})])
    try:
        dlg = OptionsDialog(win)
        dlg.r_api.setChecked(True)                                      # der Test-Knopf gehört zum API-Bereich
        dlg.fields["claude/api_base_url"][2](f.url)
        dlg.key.setText("sk-ant-testschluessel")
        dlg._test()
        assert pump(lambda: dlg.test_btn.isEnabled(), 20) and "✔" in dlg.test_out.text() and "claude-haiku-5-5" in dlg.test_out.text()
        dlg._test()
        assert pump(lambda: dlg.test_btn.isEnabled() and "✘" in dlg.test_out.text(), 20) and "Schlüssel wurde abgelehnt" in dlg.test_out.text()
        assert f.requests[0]["max_tokens"] == 64 and "sk-ant-testschluessel" not in json.dumps(options.export_all())
        dlg.key.clear(); keystore.clear(); dlg._test()
        assert "Kein Schlüssel" in dlg.test_out.text()
    finally:
        f.close()


def test_export_and_import_round_trip_without_secrets(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    keystore.save("sk-ant-niemals-exportieren"); options.set("editor/tab_width", 5)
    out = tmp_path / "opt.json"
    dlg = OptionsDialog(win)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    dlg._export()
    data = json.loads(out.read_text())
    assert data["editor/tab_width"] == 5 and "niemals" not in out.read_text()
    options.reset()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    dlg._import()
    assert options.get("editor/tab_width") == 5 and dlg.fields["editor/tab_width"][0].value() == 5
