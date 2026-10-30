"""Dock-Layout: linke und rechte Leisten haben eine Mindestbreite, damit Reiter lesbar bleiben."""
from vds import app
from vds.app import MainWindow


def test_side_docks_keep_a_readable_minimum_width(qapp, tmp_path):
    win = MainWindow()
    try:
        for d in (win.d_explorer, win.d_toolbox, win.d_changes):
            assert d.minimumWidth() == app.LEFT_MIN
        for d in (win.d_chat, win.d_props):
            assert d.minimumWidth() == app.RIGHT_MIN
        long = tmp_path / "ein_sehr_langer_projektname_xyz"; long.mkdir()
        win.set_root(long)
        assert win.d_explorer.windowTitle() == "Explorer – ein_sehr_lang…"
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()
