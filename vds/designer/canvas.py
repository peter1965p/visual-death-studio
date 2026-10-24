"""Visueller Formular-Designer: Controls ziehen, verschieben, skalieren, Snaplines, Undo/Redo."""
import copy
import json

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from shiboken6 import delete as delete_qobject

from . import layouts
from ..icons import control_icon
from .controls import BY_TYPE, apply_prop, font_decls, make_widget, new_props
from .layouts import CONTAINERS, LAYOUT_KEYS

M, TB, GRID, SNAP, HS = 24, 30, 8, 5, 7        # Rand, Titelleiste, Raster, Snap-Distanz, Handle-Größe
HANDLES = [(0, 0), (.5, 0), (1, 0), (1, .5), (1, 1), (.5, 1), (0, 1), (0, .5)]
CURSORS = [Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor,
           Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor]
MIME = "application/x-vds-control"
GUIDE = QColor("#e040a0")
SNAP_ON, SHOW_GRID = True, True               # Fanglinien und Punktraster (Extras → Optionen → Designer)
TRAY_H, CHIP_W = 36, 156                       # Komponentenleiste unter dem Formular

LIGHT = """
#formsurface QPushButton { background:#e1e1e1; color:#000; border:1px solid #adadad; padding:2px 8px; border-radius:0; }
#formsurface QLineEdit, #formsurface QPlainTextEdit, #formsurface QListWidget, #formsurface QSpinBox, #formsurface QComboBox
  { background:#fff; color:#000; border:1px solid #7a7a7a; selection-background-color:#3399ff; }
#formsurface QComboBox QAbstractItemView { background:#fff; color:#000; }
#formsurface QLabel, #formsurface QCheckBox, #formsurface QRadioButton, #formsurface QGroupBox { color:#000; background:transparent; }
#formsurface QGroupBox { border:1px solid #a0a0a0; margin-top:8px; } #formsurface QGroupBox::title { subcontrol-origin: margin; left:8px; padding:0 3px; }
#formsurface QFrame[vdsPanel="true"] { border:1px solid #a0a0a0; background:transparent; } #formsurface QProgressBar { border:1px solid #bcbcbc; background:#e6e6e6; color:#000; text-align:center; }
#formsurface QProgressBar::chunk { background:#06b025; }
#formsurface QTabWidget::pane { border:1px solid #a0a0a0; background:transparent; } #formsurface QTabBar::tab { background:#e1e1e1; color:#000; padding:4px 10px; border:1px solid #adadad; }
#formsurface QTabBar::tab:selected { background:#fff; }
"""


def configure(grid: int | None = None, snap: bool | None = None, show_grid: bool | None = None):
    """Raster, Fanglinien und Rasteranzeige setzen (gilt für alle Designer)."""
    global GRID, SNAP_ON, SHOW_GRID
    GRID = grid if grid else GRID
    SNAP_ON = SNAP_ON if snap is None else snap
    SHOW_GRID = SHOW_GRID if show_grid is None else show_grid


class Surface(QWidget):
    bg = QColor("#f0f0f0")

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        if not SHOW_GRID:
            return
        p.setPen(self.bg.lighter(145) if self.bg.lightness() < 110 else self.bg.darker(122))
        for x in range(0, self.width(), GRID):
            for y in range(0, self.height(), GRID):
                p.drawPoint(x, y)


class Overlay(QWidget):
    def __init__(self, canvas):
        super().__init__(canvas)
        self.c = canvas
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        c, p = self.c, QPainter(self)
        for cid in c.sel:
            if not c._visible(cid):
                continue
            p.setPen(QPen(QColor("#00b8d9"), 1, Qt.DotLine)); p.setBrush(Qt.NoBrush)
            p.drawRect(c.canvas_rect(cid).adjusted(0, 0, -1, -1))
        for r in c.handle_rects().values():
            p.setPen(QColor("black")); p.setBrush(QColor("white")); p.drawRect(r)
        p.setPen(QPen(GUIDE, 1))
        for kind, v in c.guides:
            if kind == "v":
                p.drawLine(v + M, M + TB, v + M, M + TB + c.model["height"])     # v/h: Position in Formularkoordinaten
            else:
                p.drawLine(M, v + M + TB, M + c.model["width"], v + M + TB)
        if c.band:
            r = QRect(c.band[0], c.band[1]).normalized()
            p.setPen(QPen(QColor("#00e5ff"), 1, Qt.DashLine)); p.setBrush(QColor(0, 229, 255, 40)); p.drawRect(r)


class Canvas(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.model = None
        self.items: dict[str, QWidget] = {}
        self.pages: dict[str, list] = {}              # TabWidget -> Seiten-Widgets
        self.sel: list[str] = []
        self.guides, self.band, self.drag = [], None, None
        self.undo_stack, self.redo_stack, self._last_prop = [], [], None
        self.clipboard: list = []
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.surface = Surface(self)
        self.surface.setObjectName("formsurface")
        self.surface.setStyleSheet(LIGHT)
        self.surface.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.overlay = Overlay(self)

    # --- Modell -----------------------------------------------------------------
    def load(self, model):
        self.model = model
        model.setdefault("components", [])
        layouts.normalize(model)
        self.undo_stack.clear(); self.redo_stack.clear()
        self.rebuild()

    def rebuild(self):
        for w in self.items.values():
            w.hide(); w.setParent(None); w.deleteLater()
        self.items, self.pages = {}, {}
        old = self.surface.layout()
        if old is not None:
            delete_qobject(old)
        self._build(None)
        self.sel = [s for s in self.sel if s in self.items or self.component(s)]
        self.relayout()
        self._apply_layouts()

    def _build(self, parent):
        for c in self.model["controls"]:
            if c.get("parent") == parent:
                self._create_widget(c)
                if c["type"] in CONTAINERS:
                    self._build(c["name"])

    def _holder(self, parent, tab=0):
        """Das Widget, in das Kinder von `parent` (Tab `tab`) gehören."""
        if parent is None:
            return self.surface
        pages = self.pages.get(parent)
        return pages[min(max(tab, 0), len(pages) - 1)] if pages else self.items[parent]

    def _holders(self, key):
        """[(Tab, Widget)] der Layout-Flächen eines Containers (None = Formular)."""
        if key is None:
            return [(0, self.surface)]
        if key in self.pages:
            return list(enumerate(self.pages[key]))
        return [(0, self.items[key])]

    def _create_widget(self, c):
        parent = self.control(c["parent"]) if c.get("parent") else None
        w = make_widget(c["type"], c["props"], self._holder(c.get("parent"), layouts.tab_of(c, parent)))
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        w.setFocusPolicy(Qt.NoFocus)
        if c["type"] == "TabWidget":
            pages = []
            for t in layouts.tab_titles(c["props"]):
                page = QWidget(w); w.addTab(page, t); pages.append(page)
            self.pages[c["name"]] = pages
            w.setCurrentIndex(min(max(int(c["props"].get("current", 0)), 0), len(pages) - 1))
        w.setGeometry(c["x"], c["y"], c["w"], c["h"])
        w.show()
        self.items[c["name"]] = w

    def _layout_mode(self, parent):
        return layouts.cfg(self.model if parent is None else self.control(parent)["props"])[0]

    def _apply_layouts(self, only="*"):
        """Legt Qt-Layouts über Formular und Container (only: nur dieser Container, None = Formular)."""
        keys = [None] + [c["name"] for c in self.model["controls"] if c["type"] in CONTAINERS] if only == "*" else [only]
        for key in keys:
            mode, spacing, margin, cols = layouts.cfg(self.model if key is None else self.control(key)["props"])
            for tab, holder in self._holders(key):
                if holder.layout() is not None:
                    delete_qobject(holder.layout())
                kids = layouts.children(self.model, key, tab)
                for c in kids:
                    w = self.items[c["name"]]
                    if mode == "Keine":
                        w.setMinimumSize(0, 0); w.setGeometry(c["x"], c["y"], c["w"], c["h"])
                    else:
                        w.setMinimumSize(c["w"], c["h"])
                if mode == "Keine":
                    continue
                lay = {"Vertikal": QVBoxLayout, "Horizontal": QHBoxLayout, "Raster": QGridLayout}[mode](holder)
                lay.setSpacing(spacing); lay.setContentsMargins(margin, margin, margin, margin)
                for n, c in enumerate(layouts.ordered(kids, mode)):
                    if mode == "Raster":
                        lay.addWidget(self.items[c["name"]], n // cols, n % cols)
                    else:
                        lay.addWidget(self.items[c["name"]])
                lay.activate()

    def _place(self, c):
        """Bringt das Widget auf die Modellgeometrie – oder lässt das Layout des Containers neu anordnen."""
        if self._layout_mode(c.get("parent")) == "Keine":
            self.items[c["name"]].setGeometry(c["x"], c["y"], c["w"], c["h"])
        else:
            self._apply_layouts(c.get("parent"))

    def origin(self, parent, tab=0) -> QPoint:
        """Ursprung der Kinderfläche in Formularkoordinaten."""
        return self._holder(parent, tab).mapTo(self.surface, QPoint(0, 0))

    def relayout(self):
        m = self.model
        comps = len(m.get("components", []))
        self.setFixedSize(max(m["width"] + 2 * M, comps * CHIP_W + 2 * M), m["height"] + TB + 2 * M + (TRAY_H + 10 if comps else 0))
        self.surface.setGeometry(M, M + TB, m["width"], m["height"])
        c = QColor(m.get("back_color") or "#f0f0f0")
        self.surface.bg = c if c.isValid() else QColor("#f0f0f0")
        decl = font_decls(m)
        self.surface.setStyleSheet(LIGHT + (f"#formsurface * {{ {decl} }}" if decl else ""))
        self.overlay.setGeometry(self.rect()); self.overlay.raise_()
        self.update(); self.overlay.update()

    def component(self, cid):
        return next((c for c in self.model.get("components", []) if c["name"] == cid), None)

    def control(self, cid):
        return next((c for c in self.model["controls"] if c["name"] == cid), None) or self.component(cid)

    def tray_rects(self) -> dict:
        y = M + TB + self.model["height"] + 14
        return {c["name"]: QRect(M + i * CHIP_W, y, CHIP_W - 6, TRAY_H - 6) for i, c in enumerate(self.model.get("components", []))}

    def canvas_rect(self, cid) -> QRect:
        w = self.items[cid]
        p = w.mapTo(self.surface, QPoint(0, 0))
        return QRect(p.x() + M, p.y() + M + TB, w.width(), w.height())

    def _visible(self, cid) -> bool:
        return cid in self.items and self.items[cid].isVisibleTo(self.surface)

    def container_at(self, p, exclude=()):
        """Innerster Container unter dem Punkt (Canvaskoordinaten): (Name | None = Formular, Tab)."""
        sp = QPoint(p.x() - M, p.y() - M - TB)
        for c in reversed(self.model["controls"]):
            if c["type"] not in CONTAINERS or c["name"] in exclude or not self._visible(c["name"]):
                continue
            w, tab = self.items[c["name"]], 0
            if c["type"] == "TabWidget":
                w, tab = w.currentWidget(), w.currentIndex()
            if QRect(w.mapTo(self.surface, QPoint(0, 0)), w.size()).contains(sp):
                return c["name"], tab
        return None, 0

    def _snapshot(self):
        return json.dumps(self.model)

    def push_undo(self):
        self.undo_stack.append(self._snapshot()); self.redo_stack.clear(); self._last_prop = None
        del self.undo_stack[:-100]

    def _restore(self, snap):
        self.model = json.loads(snap)
        self.rebuild(); self.owner.changed("undo")

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot()); self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot()); self._restore(self.redo_stack.pop())

    def unique_name(self, base):
        names = {c["name"] for c in self.model["controls"] + self.model.get("components", [])}
        n = 1
        while f"{base}{n}" in names:
            n += 1
        return f"{base}{n}"

    # --- Operationen -------------------------------------------------------------------
    def add_control(self, ctype, pos=None, parent=None, tab=0):
        """pos: Position relativ zum Container `parent` (None = Formular)."""
        spec = BY_TYPE[ctype]
        if spec.component:
            return self.add_component(ctype)
        if pos is None:
            sel = self.control(self.sel[0]) if len(self.sel) == 1 else None
            if sel and sel["type"] in CONTAINERS:                           # Doppelklick in der Toolbox: in den gewählten Container
                parent, tab = sel["name"], (self.items[sel["name"]].currentIndex() if sel["type"] == "TabWidget" else 0)
                pos = (16, 24)
            else:
                k = len(self.model["controls"]) % 10
                pos = (24 + 16 * k, 24 + 16 * k)
        self.push_undo()
        name = self.unique_name(spec.base)
        c = {"type": ctype, "name": name, "x": self._grid(pos[0]), "y": self._grid(pos[1]),
             "w": spec.size[0], "h": spec.size[1], "props": new_props(spec, name)}
        if parent:
            c["parent"] = parent
            if self.control(parent)["type"] == "TabWidget":
                c["tab"] = tab
        self.model["controls"].append(c)
        self._create_widget(c)
        self._place(c)
        self.set_sel([name]); self.owner.changed("add")

    def add_component(self, ctype):
        """Nicht visuelle Komponente (Datei-, Druck-, Farbdialog …): landet in der Komponentenleiste unter dem Formular."""
        spec = BY_TYPE[ctype]
        self.push_undo()
        name = self.unique_name(spec.base)
        self.model["components"].append({"type": ctype, "name": name, "props": new_props(spec, name)})
        self.relayout()
        self.set_sel([name]); self.owner.changed("add")

    def set_sel(self, ids):
        self.sel = list(ids)
        self.overlay.update(); self.owner.selection_changed()

    def _top_level(self, names):
        """Aus der Auswahl nur Controls, deren Container nicht ebenfalls gewählt ist."""
        sel = set(names)
        out = []
        for n in names:
            p, up = self.control(n).get("parent"), False
            while p:
                if p in sel:
                    up = True; break
                p = self.control(p).get("parent")
            if not up:
                out.append(n)
        return out

    def delete_selected(self):
        if not self.sel:
            return
        self.push_undo()
        gone = set(layouts.with_descendants(self.model, self.sel))
        self.model["controls"] = [c for c in self.model["controls"] if c["name"] not in gone]
        self.model["components"] = [c for c in self.model["components"] if c["name"] not in self.sel]
        self.set_sel([]); self.rebuild(); self.owner.changed("delete")

    def copy(self):
        names = layouts.with_descendants(self.model, self._top_level(self.sel))
        self.clipboard = [copy.deepcopy(self.control(n)) for n in names]
        self.clip_comps = [copy.deepcopy(c) for c in self.model["components"] if c["name"] in self.sel]

    def cut(self):
        self.copy(); self.delete_selected()

    def paste(self):
        if not self.clipboard and not getattr(self, "clip_comps", None):
            return
        self.push_undo()
        mapping, new = {}, []
        for src in getattr(self, "clip_comps", []):
            c = copy.deepcopy(src)
            c["name"] = self.unique_name(BY_TYPE[c["type"]].base)
            self.model["components"].append(c); new.append(c["name"])
        for src in self.clipboard:
            c = copy.deepcopy(src)
            c["name"] = self.unique_name(BY_TYPE[c["type"]].base)
            mapping[src["name"]] = c["name"]
            if src.get("parent") in mapping:                                 # Kinder bleiben im kopierten Container
                c["parent"] = mapping[src["parent"]]
            else:
                if src.get("parent") and not self.control(src["parent"]):
                    c.pop("parent", None); c.pop("tab", None)
                c["x"] += 16; c["y"] += 16
                new.append(c["name"])
            for k in ("text", "title"):
                if c["props"].get(k) == src["name"]:
                    c["props"][k] = c["name"]
            self.model["controls"].append(c)
        self.set_sel(new); self.rebuild(); self.owner.changed("paste")

    def select_all(self):
        self.set_sel([c["name"] for c in self.model["controls"]])

    def set_prop(self, cid, key, value, source="grid"):
        """cid None = Formular. Rückgabe: True, wenn übernommen."""
        if cid is None:
            if key in ("title", "back_color", "font") or key in LAYOUT_KEYS:
                pass
            elif key not in ("width", "height"):
                return False
            elif value < 100:
                return False
            if self._last_prop != (None, key):
                self.push_undo(); self._last_prop = (None, key)
            self.model[key] = value
            self.relayout()
            if key in LAYOUT_KEYS:
                self._apply_layouts(None)
        else:
            c = self.control(cid)
            if key == "name":
                if not str(value).isidentifier() or any(x["name"] == value for x in self.model["controls"] + self.model["components"] if x is not c):
                    return False
                self.push_undo(); c["name"] = value
                if cid in self.items:
                    self.items[value] = self.items.pop(cid)
                if cid in self.pages:
                    self.pages[value] = self.pages.pop(cid)
                for x in self.model["controls"]:
                    if x.get("parent") == cid:
                        x["parent"] = value
                self.sel = [value if s == cid else s for s in self.sel]
            elif key in ("x", "y", "w", "h"):
                if self._last_prop != (cid, key):
                    self.push_undo(); self._last_prop = (cid, key)
                c[key] = max(8, value) if key in ("w", "h") else value
                self._place(c)
            else:
                if self._last_prop != (cid, key):
                    self.push_undo(); self._last_prop = (cid, key)
                c["props"][key] = value
                if key in LAYOUT_KEYS or key in ("tabs", "current"):         # strukturelle Eigenschaften: Fläche neu aufbauen
                    self.rebuild()
                elif cid in self.items:
                    apply_prop(self.items[cid], c["type"], key, value, c["props"])
        self.overlay.update(); self.update()
        self.owner.changed(source)
        return True

    # --- Geometrie-Helfer ----------------------------------------------------------------
    @staticmethod
    def _grid(v):
        return round(v / GRID) * GRID

    def handle_rects(self) -> dict:
        if len(self.sel) == 1:
            if self._layout_mode(self.control(self.sel[0]).get("parent")) != "Keine" or not self._visible(self.sel[0]):
                return {}                                                    # Größe bestimmt das Layout
            r = self.canvas_rect(self.sel[0]); idx = range(8)
        elif not self.sel and self.model:
            r = QRect(M, M + TB, self.model["width"], self.model["height"]); idx = (3, 4, 5)
        else:
            return {}
        return {i: QRect(int(r.x() + HANDLES[i][0] * r.width() - HS // 2), int(r.y() + HANDLES[i][1] * r.height() - HS // 2), HS, HS)
                for i in idx}

    def item_at(self, p):
        for c in reversed(self.model["controls"]):
            if self._visible(c["name"]) and self.canvas_rect(c["name"]).contains(p):
                return c["name"]
        return None

    # --- Maus ----------------------------------------------------------------------------
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.LeftButton:
            return
        p = e.position().toPoint()
        for name, r in self.tray_rects().items():
            if r.contains(p):
                return self.set_sel([name])
        for i, r in self.handle_rects().items():
            if r.adjusted(-2, -2, 2, 2).contains(p):
                return self._begin("resize", p, i)
        cid = self.item_at(p)
        if cid:
            if e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                self.set_sel([s for s in self.sel if s != cid] if cid in self.sel else self.sel + [cid])
            elif cid not in self.sel:
                self.set_sel([cid])
            self._begin("move", p)
        else:
            self.set_sel([])
            if QRect(M, M + TB, self.model["width"], self.model["height"]).contains(p):
                self.band = (p, p)

    def _begin(self, mode, p, handle=None):
        movers = self._top_level(self.sel) if mode == "move" else self.sel      # Kinder wandern mit ihrem Container
        self.drag = dict(mode=mode, start=p, handle=handle, pushed=False,
                         orig={s: (c["x"], c["y"], c["w"], c["h"]) for s in movers for c in [self.control(s)]},
                         abs0={s: self.canvas_rect(s).topLeft() - QPoint(M, M + TB) for s in movers},
                         form=(self.model["width"], self.model["height"]))

    def mouseDoubleClickEvent(self, e):
        cid = self.item_at(e.position().toPoint())
        if cid:
            self.owner.event_requested(cid)

    def mouseMoveEvent(self, e):
        p = e.position().toPoint()
        if self.band:
            self.band = (self.band[0], p)
            r = QRect(*self.band).normalized()
            self.set_sel([c["name"] for c in self.model["controls"] if self._visible(c["name"]) and r.intersects(self.canvas_rect(c["name"]))])
            self.overlay.update()
            return
        d = self.drag
        if not d:
            for i, r in self.handle_rects().items():
                if r.adjusted(-2, -2, 2, 2).contains(p):
                    return self.setCursor(CURSORS[i])
            self.setCursor(Qt.SizeAllCursor if self.item_at(p) else Qt.ArrowCursor)
            return
        dx, dy = p.x() - d["start"].x(), p.y() - d["start"].y()
        if not d["pushed"] and (abs(dx) > 2 or abs(dy) > 2):
            self.push_undo(); d["pushed"] = True
        if not d["pushed"]:
            return
        self.guides = []
        (self._do_move if d["mode"] == "move" else self._do_resize)(dx, dy)
        self.owner.changed("canvas")
        self.overlay.update()

    def _targets(self, parent, tab):
        """Fanglinien innerhalb eines Containers: dessen Rand und die Kanten der Geschwister."""
        if parent is None:
            pw, ph = self.model["width"], self.model["height"]
        else:
            h = self._holder(parent, tab); pw, ph = h.width(), h.height()
        xs, ys = [10, pw - 10], [10, ph - 10]
        for c in layouts.children(self.model, parent, tab):
            if c["name"] in self.sel:
                continue
            xs += [c["x"], c["x"] + c["w"] // 2, c["x"] + c["w"]]; ys += [c["y"], c["y"] + c["h"] // 2, c["y"] + c["h"]]
        return xs, ys

    def _do_move(self, dx, dy):
        o = self.drag["orig"]
        bx, by = min(v[0] for v in o.values()), min(v[1] for v in o.values())
        bw, bh = max(v[0] + v[2] for v in o.values()) - bx, max(v[1] + v[3] for v in o.values()) - by
        first = self.control(next(iter(o)))
        parent = first.get("parent")
        tab = layouts.tab_of(first, self.control(parent) if parent else None)
        in_layout = self._layout_mode(parent) != "Keine"
        xs, ys = self._targets(parent, tab)
        org = self.origin(parent, tab)
        out = []
        for start, size, delta, targets, kind, off in ((bx, bw, dx, xs, "v", org.x()), (by, bh, dy, ys, "h", org.y())):
            pos = start + delta
            cands = [] if in_layout or not SNAP_ON else [(t - m, t) for m in (pos, pos + size // 2, pos + size) for t in targets if abs(t - m) <= SNAP]
            if cands:
                adj, line = min(cands, key=lambda a: abs(a[0]))
                pos += adj; self.guides.append((kind, line + off))
            elif not in_layout:
                pos = self._grid(pos)
            out.append(pos - start)
        for cid, (x, y, w, h) in o.items():
            c = self.control(cid)
            c["x"], c["y"] = x + out[0], y + out[1]
        for par in {self.control(cid).get("parent") for cid in o}:
            if self._layout_mode(par) != "Keine":
                self._apply_layouts(par)                                          # Reihenfolge im Layout folgt der Position
        for cid in o:
            if self._layout_mode(self.control(cid).get("parent")) == "Keine":
                self.items[cid].move(self.control(cid)["x"], self.control(cid)["y"])

    def _do_resize(self, dx, dy):
        d = self.drag
        hx, hy = HANDLES[d["handle"]]
        if not self.sel:                      # Formulargröße
            w0, h0 = d["form"]
            if hx: self.model["width"] = max(100, self._grid(w0 + dx))
            if hy: self.model["height"] = max(100, self._grid(h0 + dy))
            self.relayout()
            return
        cid = self.sel[0]
        x, y, w, h = d["orig"][cid]
        l, t, r, b = x, y, x + w, y + h
        if hx == 0: l = self._grid(x + dx)
        if hx == 1: r = self._grid(x + w + dx)
        if hy == 0: t = self._grid(y + dy)
        if hy == 1: b = self._grid(y + h + dy)
        if r - l < 8: l, r = (r - 8, r) if hx == 0 else (l, l + 8)
        if b - t < 8: t, b = (b - 8, b) if hy == 0 else (t, t + 8)
        c = self.control(cid)
        c["x"], c["y"], c["w"], c["h"] = l, t, r - l, b - t
        self.items[cid].setGeometry(l, t, r - l, b - t)

    def mouseReleaseEvent(self, e):
        d = self.drag
        if d and d["mode"] == "move" and d["pushed"]:
            self._drop_into_container(d, e.position().toPoint())
        self.drag, self.band, self.guides = None, None, []
        self.overlay.update()

    def _drop_into_container(self, d, p):
        """Nach dem Verschieben: liegt der Mauszeiger über einem anderen Container, wandert das Control (samt Kindern) hinein."""
        movers = list(d["orig"])
        parent, tab = self.container_at(p, exclude=set(layouts.with_descendants(self.model, movers)))
        delta = p - d["start"]
        moved = []
        for cid in movers:
            c = self.control(cid)
            cur = c.get("parent")
            ptype = self.control(parent)["type"] if parent else None
            if cur == parent and (ptype != "TabWidget" or layouts.tab_of(c, self.control(parent)) == tab):
                continue
            ab = d["abs0"][cid] + delta - self.origin(parent, tab)
            c["x"], c["y"] = max(0, self._grid(ab.x())), max(0, self._grid(ab.y()))
            c.pop("parent", None); c.pop("tab", None)
            if parent:
                c["parent"] = parent
                if ptype == "TabWidget":
                    c["tab"] = tab
            moved.append(cid)
        if moved:                                      # Eltern müssen vor ihren Kindern stehen: Verschobene ans Ende
            keep = set(layouts.with_descendants(self.model, moved))
            ctrls = self.model["controls"]
            ctrls[:] = [c for c in ctrls if c["name"] not in keep] + [c for c in ctrls if c["name"] in keep]
            self.rebuild(); self.owner.changed("canvas")

    def keyPressEvent(self, e):
        step = GRID if e.modifiers() & Qt.ShiftModifier else 1
        k = e.key()
        if k == Qt.Key_Delete:
            self.delete_selected()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.sel:
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            self.push_undo()
            for s in (n for n in self._top_level(self.sel) if n in self.items):
                c = self.control(s); c["x"] += dx; c["y"] += dy; self._place(c)
            self.overlay.update(); self.owner.changed("canvas")
        else:
            super().keyPressEvent(e)

    # --- Drag & Drop aus der Toolbox -----------------------------------------------------------
    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasFormat(MIME) else e.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        ctype = bytes(e.mimeData().data(MIME)).decode()
        cp = e.position().toPoint()
        if BY_TYPE[ctype].component:
            self.add_component(ctype); self.setFocus(); e.acceptProposedAction()
            return
        parent, tab = self.container_at(cp)
        p = cp - QPoint(M, M + TB) - self.origin(parent, tab)
        self.add_control(ctype, (p.x(), p.y()), parent, tab)
        self.setFocus(); e.acceptProposedAction()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0a0d1f"))
        w = self.model["width"]
        bar = QRect(M, M, w, TB)
        p.fillRect(bar, QColor("#ffffff"))
        p.setPen(QColor("#000")); f = QFont(self.font()); f.setPointSize(9); p.setFont(f)
        p.fillRect(M + 8, M + 9, 12, 12, QColor("#00a8c8"))
        p.drawText(bar.adjusted(30, 0, -120, 0), Qt.AlignVCenter | Qt.AlignLeft, self.model["title"])
        p.drawText(QRect(M + w - 138, M, 46, TB), Qt.AlignCenter, "–")
        p.drawText(QRect(M + w - 92, M, 46, TB), Qt.AlignCenter, "□")
        p.drawText(QRect(M + w - 46, M, 46, TB), Qt.AlignCenter, "✕")
        p.setPen(QColor("#888")); p.drawRect(M - 1, M - 1, w + 1, self.model["height"] + TB + 1)
        rects = self.tray_rects()
        if rects:
            p.setPen(QColor("#6f82ad")); p.drawText(M, M + TB + self.model["height"] + 12, "Komponenten")
            for c in self.model["components"]:
                r = rects[c["name"]]
                on = c["name"] in self.sel
                p.setBrush(QColor("#1b2a5c" if on else "#121a3d")); p.setPen(QPen(QColor("#00e5ff" if on else "#33427a"), 1.4 if on else 1))
                p.drawRoundedRect(r, 6, 6)
                control_icon(c["type"]).paint(p, QRect(r.x() + 6, r.y() + 6, 16, 16))
                p.setPen(QColor("#dbe6ff")); p.drawText(r.adjusted(28, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft, c["name"])


class FormDesigner(QWidget):
    """Tab-Inhalt: ScrollArea mit Canvas plus die Signale, die Eigenschaften und Dokumentverwaltung brauchen."""
    selectionChanged = Signal()
    modelChanged = Signal(str)          # Quelle: grid|canvas|add|delete|paste|undo
    modifiedChanged = Signal(bool)
    eventRequested = Signal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout
        self.modified = False
        self.canvas = Canvas(self)
        self.canvas.load(model)
        sa = QScrollArea(); sa.setWidget(self.canvas); sa.setFrameShape(QScrollArea.NoFrame)
        sa.setStyleSheet("QScrollArea { background:#0a0d1f; }")
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(sa)
        self.setFocusProxy(self.canvas)

    @property
    def model(self):
        return self.canvas.model

    # Rückrufe des Canvas
    def changed(self, source):
        if not self.modified:
            self.modified = True; self.modifiedChanged.emit(True)
        self.modelChanged.emit(source)

    def selection_changed(self):
        self.selectionChanged.emit()

    def event_requested(self, cid):
        self.eventRequested.emit(cid)

    def mark_clean(self):
        self.modified = False; self.modifiedChanged.emit(False)

    # Bearbeiten-Menü
    undo = lambda self: self.canvas.undo()
    redo = lambda self: self.canvas.redo()
    cut = lambda self: self.canvas.cut()
    copy = lambda self: self.canvas.copy()
    paste = lambda self: self.canvas.paste()
    selectAll = lambda self: self.canvas.select_all()
    delete_selected = lambda self: self.canvas.delete_selected()
    add_control = lambda self, t: self.canvas.add_control(t)
