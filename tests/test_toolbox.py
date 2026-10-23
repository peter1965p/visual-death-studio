"""Toolbox: Kategorien, A–Z-Liste, Suche, sprachabhängige Codeausschnitte, Drag-Daten."""
from PySide6.QtCore import Qt

from vds.designer.controls import SPECS
from vds.docks.tools import CTRL_ROLE, Toolbox


def _groups(tb):
    return {tb.tree.topLevelItem(i).text(0).split("  (")[0]: tb.tree.topLevelItem(i) for i in range(tb.tree.topLevelItemCount())}


def test_toolbox_lists_every_control_by_category_and_az(qapp):
    tb = Toolbox()
    g = _groups(tb)
    assert "Eingabe" in g and "Daten" in g and "Menüs und Leisten" in g
    az = g["Alle Steuerelemente (A–Z)"]
    names = [az.child(i).text(0) for i in range(az.childCount())]
    assert len(names) == len(SPECS) and names == sorted(names, key=str.lower)
    by_cat = sum(g[c].childCount() for c in g if c not in ("Alle Steuerelemente (A–Z)", "Allgemein") and not c.startswith(("Codeausschnitte")))
    assert by_cat == len(SPECS)


def test_snippets_follow_the_language(qapp):
    tb = Toolbox()
    assert not any(k.startswith("Codeausschnitte –") for k in _groups(tb))
    tb.set_language("python")
    py = next(v for k, v in _groups(tb).items() if k.startswith("Codeausschnitte – Python"))
    assert py.childCount() >= 15
    tb.set_language("go")
    g = _groups(tb)
    assert any(k.startswith("Codeausschnitte – Go") for k in g) and not any("Python" in k for k in g)


def test_search_filters_and_expands(qapp):
    tb = Toolbox()
    tb.set_language("python")
    tb.search.setText("calendar")
    g = _groups(tb)
    visible = [it.child(i).text(0) for it in g.values() if not it.isHidden() for i in range(it.childCount()) if not it.child(i).isHidden()]
    assert visible == ["CalendarWidget", "CalendarWidget"]              # einmal in „Anzeige“, einmal in „Alle Steuerelemente“
    tb.search.setText("dateedit")
    visible = {it.child(i).text(0) for it in _groups(tb).values() if not it.isHidden() for i in range(it.childCount()) if not it.child(i).isHidden()}
    assert visible == {"DateEdit"}
    tb.search.setText("")
    assert all(not it.isHidden() for it in _groups(tb).values())


def test_drag_data_contains_control_type(qapp):
    from vds.designer.canvas import MIME
    tb = Toolbox()
    az = _groups(tb)["Alle Steuerelemente (A–Z)"]
    item = az.child(0)
    m = tb.tree.mimeData([item])
    assert bytes(m.data(MIME)).decode() == item.data(0, CTRL_ROLE)
