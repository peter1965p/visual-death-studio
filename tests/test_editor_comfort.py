"""Faltung, Klammerpaare, Lesezeichen, wandernde Haltepunkte, Minimap, Zurück/Vor und der Branch in der Statusleiste."""
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from vds import options
from vds.app import MainWindow
from vds.editor.code_editor import CodeEditor
from vds.editor.structure import NavHistory, fold_end, indent_width, match_bracket, shift_lines

CODE = "def a():\n    x = 1\n    if x:\n        y = 2\n\n    return x\n\n\ndef b():\n    return 2\n"


def lines_of(text):
    parts = text.split("\n")
    return lambda n: parts[n] if 0 <= n < len(parts) else None


def test_a_block_ends_with_its_last_indented_line_and_trailing_blanks_stay_out():
    lines = lines_of(CODE)
    assert fold_end(lines, 0, 4) == 5
    assert fold_end(lines, 2, 4) == 3
    assert fold_end(lines, 3, 4) is None, "nichts Tieferes dahinter"
    assert fold_end(lines, 4, 4) is None, "eine Leerzeile faltet nichts"
    assert indent_width("\t  x", 4) == 6


def test_brackets_pair_up_nested_and_from_both_sides():
    text = "f(a[1], (b))"
    at = lambda i: text[i]
    assert match_bracket(at, len(text), 1) == (1, 11)
    assert match_bracket(at, len(text), 12) == (11, 1), "links vom Cursor am Zeilenende"
    assert match_bracket(at, len(text), 8) == (8, 10)
    assert match_bracket(at, len(text), 0) is None
    assert match_bracket(lambda i: "(("[i], 2, 0) is None, "ohne Gegenstück"


def test_marks_move_with_their_lines():
    assert shift_lines({2, 5}, 3, 2) == {2, 7}
    assert shift_lines({2, 5, 9}, 3, -2) == {2, 3, 7}, "Zeile 5 war gelöscht und rückt auf die Stelle der Änderung"


def test_navigation_keeps_jumps_only_and_a_new_jump_cuts_the_way_forward():
    n, a, b = NavHistory(), Path("a"), Path("b")
    n.note(a, 1); n.note(a, 5); n.note(a, 50); n.note(b, 3)
    assert n.entries == [(a, 5), (a, 50), (b, 3)]
    assert n.back() == (a, 50) and n.back() == (a, 5) and n.back() is None
    assert n.forward() == (a, 50)
    n.note(b, 80)
    assert n.forward() is None and n.entries[-1] == (b, 80) and len(n.entries) == 3


@pytest.fixture
def ed(qapp):
    options.reset(["editor/minimap", "editor/indent_guides", "editor/tab_width"])
    e = CodeEditor("a.py")
    e.resize(700, 400); e.setPlainText(CODE); e.show()
    qapp.processEvents()
    yield e
    e.close()


def visible(ed):
    block, out = ed.document().firstBlock(), []
    while block.isValid():
        if block.isVisible():
            out.append(block.blockNumber())
        block = block.next()
    return out


def test_folding_hides_lines_but_never_text(ed, qapp, tmp_path):
    ed.toggle_fold(0)
    assert visible(ed) == [0, 6, 7, 8, 9, 10]
    assert ed.toPlainText() == CODE, "gespeichert wird immer der ganze Text"
    ed.grab()
    ed.toggle_fold(0)
    assert visible(ed) == list(range(11))


def test_fold_all_and_unfold_all(ed):
    ed.fold_all()
    assert 0 in ed.folded and 8 in ed.folded
    assert visible(ed) == [0, 6, 7, 8, 10]
    ed.unfold_all()
    assert not ed.folded and len(visible(ed)) == 11


def test_the_shortcut_folds_the_block_around_the_cursor(ed):
    ed.goto(2)
    ed.toggle_fold()
    assert 0 in ed.folded
    assert ed.textCursor().blockNumber() == 0, "der Cursor verschwindet nicht im eingeklappten Text"


def test_jumping_into_folded_text_opens_it(ed):
    ed.toggle_fold(0)
    ed.goto(4)
    assert not ed.folded and ed.textCursor().block().isVisible()


def test_a_click_in_the_fold_column_folds(ed, qapp):
    y = ed.cursorRect(ed.document().findBlockByNumber(0) and ed.textCursor()).center().y()
    QTest.mouseClick(ed.gutter, Qt.LeftButton, pos=QPoint(ed.gutter.width() - 5, y))
    assert ed.folded == {0}
    assert not ed.breakpoints


def test_folds_bookmarks_and_breakpoints_follow_an_edit_above_them(ed, qapp):
    ed.toggle_fold(8)
    ed.toggle_bookmark(9)
    ed.set_breakpoint_state(10, "x > 1", disabled=True)
    c = ed.textCursor(); c.movePosition(QTextCursor.Start); c.insertText("# neu\n# neu\n")
    qapp.processEvents()
    assert ed.folded == {10}
    assert ed.bookmarks == {11}
    assert ed.breakpoints == {12}
    assert ed.bp_conditions == {12: "x > 1"} and ed.bp_disabled == {12}
    assert ed.document().findBlockByNumber(11).text() == "    return 2"


def test_a_fold_that_no_longer_encloses_anything_goes_away(ed, qapp):
    ed.toggle_fold(8)
    c = ed.textCursor(); c.setPosition(ed.document().findBlockByNumber(9).position())
    c.movePosition(QTextCursor.StartOfBlock); c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor); c.removeSelectedText()
    qapp.processEvents()
    assert not ed.folded and len(visible(ed)) == ed.blockCount()


def test_bookmarks_wrap_around(ed):
    assert ed.next_bookmark() is False
    ed.toggle_bookmark(2); ed.toggle_bookmark(9)
    ed.goto(3)
    ed.next_bookmark(); assert ed.textCursor().blockNumber() == 8
    ed.next_bookmark(); assert ed.textCursor().blockNumber() == 1
    ed.prev_bookmark(); assert ed.textCursor().blockNumber() == 8
    ed.toggle_bookmark(9); assert ed.bookmarks == {2}


def test_the_bracket_pair_is_highlighted_at_the_cursor(ed):
    c = ed.textCursor(); c.setPosition(5); ed.setTextCursor(c)        # vor der öffnenden Klammer von a()
    spots = {s.cursor.selectionStart() for s in ed.extraSelections() if s.cursor.hasSelection()}
    assert {5, 6} <= spots


def test_the_minimap_sits_beside_the_text_scrolls_and_can_be_switched_off(ed, qapp):
    ed.setPlainText("\n".join(f"zeile {i}" for i in range(2000)))
    qapp.processEvents()
    assert ed.minimap.isVisible() and ed.minimap.x() >= ed.viewport().geometry().right()
    ed.minimap.grab()
    QTest.mouseClick(ed.minimap, Qt.LeftButton, pos=QPoint(10, ed.minimap.height() - 2))
    assert ed.verticalScrollBar().value() > 0
    options.set("editor/minimap", False); ed.apply_options(); qapp.processEvents()
    assert not ed.minimap.isVisible()
    wide = ed.viewport().width()
    options.set("editor/minimap", True); ed.apply_options(); qapp.processEvents()
    assert ed.minimap.isVisible() and ed.viewport().width() < wide


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    yield w
    w.docs.close_all(); w.close()


def test_back_and_forward_across_files_and_the_branch_in_the_status_bar(win, tmp_path, qapp):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("\n".join(f"a{i}" for i in range(100))); b.write_text("b\n")
    assert win.st_branch.text() == ""
    win.docs.open(a).view.goto(50); qapp.processEvents()
    win.docs.open(b); qapp.processEvents()
    win.a["navback"].trigger(); qapp.processEvents()
    d = win.docs.current_doc()
    assert d.path == a.resolve() and d.view.textCursor().blockNumber() == 49
    win.a["navforward"].trigger(); qapp.processEvents()
    assert win.docs.current_doc().path == b.resolve()
    subprocess.run(["git", "init", "-q", "-b", "testzweig", str(tmp_path)], check=True)
    win.show_branch()
    assert "testzweig" in win.st_branch.text()
    assert win.a["fold"].shortcut().toString() == "Ctrl+M, Ctrl+M"
