"""Formular-Designer: Katalog, Code-Erzeugung, Nesting-unabhängige Grundfunktionen."""
import subprocess
import sys
import textwrap

from vds.designer import codegen
from vds.designer.controls import BY_TYPE, CATEGORIES, SPECS, make_widget, new_props


def test_catalog_is_complete_and_categorised():
    assert len(SPECS) >= 36
    assert {s.category for s in SPECS} <= set(CATEGORIES)
    assert len({s.type for s in SPECS}) == len(SPECS)           # keine doppelten Typnamen
    for t in ("DateEdit", "Dial", "LcdNumber", "CalendarWidget", "TreeWidget", "TableWidget", "Line", "DialogButtonBox"):
        assert t in BY_TYPE


def test_every_control_can_be_created_live(qapp):
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    for spec in SPECS:
        w = make_widget(spec.type, new_props(spec, spec.base + "1"), parent)
        assert w is not None, spec.type


def test_generated_form_with_every_control_compiles_and_runs(qapp, tmp_path):
    controls = []
    for i, spec in enumerate(SPECS):
        name = spec.base + "1"
        controls.append({"type": spec.type, "name": name, "x": 10 + (i % 4) * 150, "y": 10 + (i // 4) * 60, "w": spec.size[0], "h": spec.size[1],
                         "props": new_props(spec, name)})
    model = codegen.new_form("Alle")
    model.update(width=800, height=900, controls=controls)
    codegen.write_files(tmp_path / "Alle.form.json", model)
    code = textwrap.dedent(f'''
        import sys; sys.path.insert(0, {str(tmp_path)!r})
        from PySide6.QtWidgets import QApplication
        from Alle import Alle
        app = QApplication([]); f = Alle(); f.show(); app.processEvents()
        print("OK", len(f.findChildren(object)) > 0, f.dateEdit1.__class__.__name__, f.treeWidget1.topLevelItemCount(), f.tableWidget1.rowCount())
    ''')
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin"}, timeout=60)
    assert r.stdout.strip().startswith("OK True QDateEdit 2 3"), r.stderr[-600:]


def test_imports_contain_only_used_classes():
    model = codegen.new_form("F")
    model["controls"] = [{"type": "Button", "name": "button1", "x": 0, "y": 0, "w": 90, "h": 30, "props": new_props(BY_TYPE["Button"], "button1")}]
    src = codegen.designer_source(model, "F")
    assert "QPushButton" in src and "QCalendarWidget" not in src
