"""Designer: Controls in Containern (GroupBox, Panel, TabWidget) und Layouts – Modell, Canvas und erzeugter Code."""
import subprocess
import sys
import textwrap

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from vds.designer import codegen, layouts
from vds.designer.canvas import M, TB, FormDesigner
from vds.designer.controls import BY_TYPE, new_props


def ctl(ctype, name, x, y, w=None, h=None, **extra):
    spec = BY_TYPE[ctype]
    props = new_props(spec, name)
    props.update(extra.pop("props", {}))
    return {"type": ctype, "name": name, "x": x, "y": y, "w": w or spec.size[0], "h": h or spec.size[1], "props": props, **extra}


def model(*controls, **form):
    m = codegen.new_form("F")
    m.update(width=520, height=400, controls=list(controls), **form)
    return m


def run_generated(tmp_path, m, expr):
    codegen.write_files(tmp_path / "F.form.json", m)
    code = textwrap.dedent(f'''
        import sys; sys.path.insert(0, {str(tmp_path)!r})
        from PySide6.QtWidgets import *
        from F import F
        app = QApplication([]); f = F(); f.show(); app.processEvents()
        print({expr})
    ''')
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin"}, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return r.stdout.strip()


# --- Codegenerator ---------------------------------------------------------------------------
def test_generated_code_nests_children_in_containers(qapp, tmp_path):
    m = model(ctl("GroupBox", "groupBox1", 10, 10, 220, 140),
              ctl("Button", "button1", 12, 30, parent="groupBox1"),
              ctl("TabWidget", "tabControl1", 250, 10, 240, 180, props={"tabs": ["Eins", "Zwei"]}),
              ctl("Label", "label1", 8, 8, parent="tabControl1", tab=0),
              ctl("CheckBox", "checkBox1", 8, 8, parent="tabControl1", tab=1))
    out = run_generated(tmp_path, m, "f.button1.parent() is f.groupBox1, f.button1.geometry().x(), "
                                     "f.label1.parent() is f.tabControl1.widget(0), f.checkBox1.parent() is f.tabControl1.widget(1), "
                                     "f.tabControl1.count(), f.tabControl1.tabText(1)")
    assert out == "True 12 True True 2 Zwei"


def test_vertical_layout_orders_children_by_position(qapp, tmp_path):
    m = model(ctl("GroupBox", "groupBox1", 10, 10, 200, 200, props={"layout": "Vertikal", "spacing": 10, "margin": 12}),
              ctl("Button", "button2", 0, 100, parent="groupBox1"), ctl("Button", "button1", 0, 10, parent="groupBox1"))
    src = codegen.designer_source(m, "F")
    assert "QVBoxLayout(self.groupBox1)" in src and src.index("addWidget(self.button1)") < src.index("addWidget(self.button2)")
    assert "QVBoxLayout" in codegen.widget_imports(m)
    assert run_generated(tmp_path, m, "f.groupBox1.layout().__class__.__name__, f.button1.y() < f.button2.y(), f.groupBox1.layout().spacing()") \
        == "QVBoxLayout True 10"


def test_form_level_grid_layout(qapp, tmp_path):
    kids = [ctl("Button", f"button{i + 1}", 10 + (i % 2) * 120, 10 + (i // 2) * 50) for i in range(4)]
    m = model(*kids, layout="Raster", grid_columns=2)
    assert run_generated(tmp_path, m, "f.layout().__class__.__name__, f.layout().getItemPosition(3)") == "QGridLayout (1, 1, 1, 1)"


def test_old_flat_models_still_work(qapp, tmp_path):
    m = model(ctl("Button", "button1", 10, 10))                    # ohne parent/layout-Schlüssel
    assert run_generated(tmp_path, m, "f.button1.geometry().x(), f.layout() is None") == "10 True"


def test_normalize_repairs_bad_parents():
    m = model(ctl("Button", "button1", 0, 0, parent="gibtsnicht"), ctl("Button", "button2", 0, 0, parent="button1"),
              ctl("Panel", "panel1", 0, 0), ctl("Label", "label1", 0, 0, parent="panel1"))
    layouts.normalize(m)
    by = layouts.by_name(m)
    assert "parent" not in by["button1"] and "parent" not in by["button2"] and by["label1"]["parent"] == "panel1"


def test_children_listed_before_parent_are_reordered():
    m = model(ctl("Label", "label1", 0, 0, parent="panel1"), ctl("Panel", "panel1", 0, 0))
    layouts.normalize(m)
    assert [c["name"] for c in m["controls"]] == ["panel1", "label1"]


# --- Canvas ----------------------------------------------------------------------------------
def make(qapp, *controls, **form):
    d = FormDesigner(model(*controls, **form))
    d.resize(700, 600); d.show()
    qapp.processEvents()
    return d, d.canvas


def press_drag_release(cv, start, end):
    def ev(kind, pos):
        return QMouseEvent(kind, QPointF(pos), QPointF(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    cv.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, start))
    cv.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, end))
    cv.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, end))


def test_drop_from_toolbox_lands_in_container_with_relative_coordinates(qapp):
    d, cv = make(qapp, ctl("GroupBox", "groupBox1", 40, 40, 200, 150))
    origin = cv.origin("groupBox1")
    target = QPoint(M + origin.x() + 24, M + TB + origin.y() + 40)
    parent, tab = cv.container_at(target)
    assert parent == "groupBox1"
    p = target - QPoint(M, M + TB) - origin
    cv.add_control("Button", (p.x(), p.y()), parent, tab)
    b = cv.control("button1")
    assert b["parent"] == "groupBox1" and (b["x"], b["y"]) == (24, 40)
    assert cv.items["button1"].parent() is cv.items["groupBox1"]
    assert cv.container_at(QPoint(M + 5, M + TB + 5)) == (None, 0)          # außerhalb: Formular


def test_dragging_a_control_into_a_container_reparents_it_and_keeps_position(qapp):
    d, cv = make(qapp, ctl("GroupBox", "groupBox1", 200, 40, 220, 160), ctl("Button", "button1", 20, 40))
    before = cv.canvas_rect("button1").topLeft()
    start = cv.canvas_rect("button1").center()
    end = start + QPoint(260, 30)
    press_drag_release(cv, start, end)
    c = cv.control("button1")
    assert c.get("parent") == "groupBox1"
    assert cv.items["button1"].parent() is cv.items["groupBox1"]
    moved = cv.canvas_rect("button1").topLeft() - before
    assert abs(moved.x() - 260) <= 8 and abs(moved.y() - 30) <= 8        # optisch dort, wo man es losgelassen hat (Raster)
    assert [x["name"] for x in cv.model["controls"]].index("groupBox1") < [x["name"] for x in cv.model["controls"]].index("button1")
    # und wieder heraus
    start = cv.canvas_rect("button1").center()
    press_drag_release(cv, start, start - QPoint(250, -150 + 150))
    assert "parent" not in cv.control("button1")


def test_moving_a_container_moves_its_children(qapp):
    d, cv = make(qapp, ctl("Panel", "panel1", 40, 40, 200, 140), ctl("Button", "button1", 10, 10, parent="panel1"))
    before = cv.canvas_rect("button1").topLeft()
    cv.set_sel(["panel1"])
    start = cv.canvas_rect("panel1").bottomRight() - QPoint(10, 10)
    press_drag_release(cv, start, start + QPoint(40, 24))
    after = cv.canvas_rect("button1").topLeft()
    assert (after - before).x() == (cv.control("panel1")["x"] - 40) and cv.control("button1")["x"] == 10


def test_delete_container_deletes_children_and_undo_restores(qapp):
    d, cv = make(qapp, ctl("GroupBox", "groupBox1", 10, 10), ctl("Button", "button1", 5, 20, parent="groupBox1"), ctl("Label", "label1", 300, 10))
    cv.set_sel(["groupBox1"]); cv.delete_selected()
    assert [c["name"] for c in cv.model["controls"]] == ["label1"]
    cv.undo()
    assert [c["name"] for c in cv.model["controls"]] == ["groupBox1", "button1", "label1"]
    assert cv.items["button1"].parent() is cv.items["groupBox1"]


def test_copy_paste_container_copies_children_with_new_names(qapp):
    d, cv = make(qapp, ctl("GroupBox", "groupBox1", 10, 10), ctl("Button", "button1", 5, 20, parent="groupBox1"))
    cv.set_sel(["groupBox1"]); cv.copy(); cv.paste()
    names = {c["name"]: c for c in cv.model["controls"]}
    assert set(names) == {"groupBox1", "button1", "groupBox2", "button2"}
    assert names["button2"]["parent"] == "groupBox2" and names["groupBox2"]["x"] == 26


def test_rename_container_updates_children(qapp):
    d, cv = make(qapp, ctl("GroupBox", "groupBox1", 10, 10), ctl("Button", "button1", 5, 20, parent="groupBox1"))
    assert cv.set_prop("groupBox1", "name", "optionen")
    assert cv.control("button1")["parent"] == "optionen" and cv.items["button1"].parent() is cv.items["optionen"]


def test_layout_property_reflows_children_live(qapp):
    d, cv = make(qapp, ctl("GroupBox", "groupBox1", 10, 10, 240, 220),
                 ctl("Button", "button1", 10, 100, parent="groupBox1"), ctl("Button", "button2", 10, 30, parent="groupBox1"))
    assert cv.items["button1"].y() == 100                                   # ohne Layout: Modellposition
    cv.set_prop("groupBox1", "layout", "Vertikal")
    assert cv.items["button2"].y() < cv.items["button1"].y() != 100         # Layout: nach y sortiert, untereinander
    assert cv._layout_mode("groupBox1") == "Vertikal"
    cv.set_sel(["button1"]); assert cv.handle_rects() == {}                 # Größe bestimmt das Layout
    cv.set_prop("groupBox1", "layout", "Keine")
    assert cv.items["button1"].y() == 100


def test_tab_pages_hide_children_of_other_tabs(qapp):
    d, cv = make(qapp, ctl("TabWidget", "tabControl1", 10, 10, 300, 200, props={"tabs": ["A", "B"]}),
                 ctl("Label", "label1", 10, 10, parent="tabControl1", tab=0), ctl("Label", "label2", 10, 10, parent="tabControl1", tab=1))
    assert cv._visible("label1") and not cv._visible("label2")
    cv.set_prop("tabControl1", "current", 1)
    assert cv._visible("label2") and not cv._visible("label1")
    assert cv.item_at(cv.canvas_rect("label2").center()) == "label2"
    assert cv.container_at(cv.canvas_rect("label2").center()) == ("tabControl1", 1)


def test_form_layout_via_property(qapp):
    d, cv = make(qapp, ctl("Button", "button1", 10, 10), ctl("Button", "button2", 10, 80))
    assert cv.set_prop(None, "layout", "Horizontal")
    assert cv.surface.layout() is not None
    assert cv.items["button2"].x() > cv.items["button1"].x() and cv.items["button1"].y() == cv.items["button2"].y()
    assert cv.model["layout"] == "Horizontal"
