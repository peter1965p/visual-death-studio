"""Befehlspalette: Fuzzy-Suche, Befehle, Dateien, Text in Dateien."""
from pathlib import Path

from PySide6.QtCore import Qt

from vds.app import MainWindow
from vds.ui import palette


def test_fuzzy_prefers_tight_matches_and_rejects_missing_letters():
    assert palette.fuzzy("xyz", "Datei öffnen") is None
    assert palette.fuzzy("main", "src/main.py") > palette.fuzzy("main", "src/domain_a_i_n.py")
    assert palette.fuzzy("", "x") == 0


def test_list_files_and_text_search_skip_environments(tmp_path):
    for n, t in {"a.py": "hallo Welt\n", "src/b.txt": "nichts\nWELT hier\n", "venv/x.py": "Welt", "bin.dat": "Welt\0"}.items():
        p = tmp_path / n; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t)
    assert palette.list_files(tmp_path) == ["a.py", "bin.dat", "src/b.txt"]
    assert palette.search_text(tmp_path, "welt") == [("a.py", 1, "hallo Welt"), ("src/b.txt", 2, "WELT hier")]


def test_palette_finds_commands_files_and_runs_them(qapp, tmp_path, pump):
    (tmp_path / "hello_world.py").write_text("print('x')\n")
    win = MainWindow()
    try:
        win.set_root(tmp_path)
        win.show_palette()
        pal = win._palette
        pal.edit.setText("hello_wo"); pal.refresh()
        assert pal.list.item(0).data(Qt.UserRole) == ("file", "hello_world.py")
        pal._run()
        pump(lambda: win.docs.current_doc() and win.docs.current_doc().path == tmp_path / "hello_world.py", 5)
        assert win.docs.current_doc().path == tmp_path / "hello_world.py"
        pal.open(">projekt exportieren"); 
        assert pal.list.count() and "exportieren" in pal.list.item(0).text()
        pal.open("%print"); pal.refresh()
        assert pal.list.item(0).data(Qt.UserRole) == ("goto", "hello_world.py", 1)
        pal.close()
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()
