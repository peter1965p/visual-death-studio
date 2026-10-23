"""Hauptfenster: Umbenennen (mit Language Server und als Textrückfall), Verweise suchen."""
from PySide6.QtWidgets import QInputDialog, QMessageBox

from vds import refactor
from vds.app import MainWindow


def _open(w, pump, root, names):
    w.set_root(root)
    docs = [w.docs.open(root / n) for n in names]
    assert pump(lambda: w._lsp_status.get("python") == "bereit", 30)
    pump(lambda: all(str(d.path) in w.lsp.servers["python"].opened for d in docs), 10)
    return docs


def _cursor_on(ed, line, col):
    c = ed.textCursor()
    c.setPosition(ed.document().findBlockByNumber(line).position() + col)
    ed.setTextCursor(c)


def test_rename_with_language_server_across_files(qapp, pump, tmp_path, monkeypatch):
    (tmp_path / "tools.py").write_text("def berechne_summe(zahlen):\n    return sum(zahlen)\n")
    (tmp_path / "main.py").write_text("from tools import berechne_summe\n\nergebnis = berechne_summe([1, 2])\n")
    w = MainWindow()
    w.show()
    d_tools, d_main = _open(w, pump, tmp_path, ["tools.py", "main.py"])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("summiere", True)))
    monkeypatch.setattr(refactor.PreviewDialog, "exec", lambda self: 1)           # Vorschau bestätigen
    w.docs.setCurrentWidget(d_main.view)
    _cursor_on(d_main.view, 2, 14)
    w.rename_symbol()
    assert pump(lambda: "summiere" in d_tools.view.toPlainText(), 20)
    assert d_tools.view.toPlainText().startswith("def summiere(zahlen)")
    assert d_main.view.toPlainText().count("summiere") == 2 and "berechne_summe" not in d_main.view.toPlainText()
    # Undo im Editor macht die Umbenennung rückgängig
    d_main.view.undo()
    assert "berechne_summe" in d_main.view.toPlainText()
    w.docs.close_all(); w.close()


def test_text_rename_fallback_without_language_server(qapp, pump, tmp_path, monkeypatch):
    (tmp_path / "lib.rs").write_text("fn verdoppeln(x: i32) -> i32 {\n    x * 2\n}\n")
    (tmp_path / "main.rs").write_text("mod lib;\nfn main() {\n    println!(\"{}\", lib::verdoppeln(4));\n    let verdoppelnd = 1;\n}\n")
    w = MainWindow()
    w.show()
    w.set_root(tmp_path)
    d = w.docs.open(tmp_path / "lib.rs")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("doppelt", True)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(refactor.PreviewDialog, "exec", lambda self: 1)
    _cursor_on(d.view, 0, 5)
    w.rename_symbol()
    assert pump(lambda: "doppelt" in (tmp_path / "main.rs").read_text(), 10)
    assert "lib::doppelt(4)" in (tmp_path / "main.rs").read_text()
    assert "verdoppelnd" in (tmp_path / "main.rs").read_text()                  # nur ganze Wörter
    assert d.view.toPlainText().startswith("fn doppelt(")
    w.docs.close_all(); w.close()


def test_find_references_word_fallback(qapp, pump, tmp_path):
    (tmp_path / "a.go").write_text("package main\n\nfunc grusz() {}\n")
    (tmp_path / "b.go").write_text("package main\n\nfunc main() {\n\tgrusz()\n\tgrusz()\n}\n")
    w = MainWindow()
    w.show()
    w.set_root(tmp_path)
    d = w.docs.open(tmp_path / "a.go")
    _cursor_on(d.view, 2, 7)
    w.find_references()
    assert pump(lambda: w.p_refs.tree.topLevelItemCount() == 3, 10)
    assert "3 Verweis(e) in 2 Datei(en)" in w.p_refs.info.text()
    w.docs.close_all(); w.close()
