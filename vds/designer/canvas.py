"""Visueller Formular-Designer: Controls ziehen, verschieben, skalieren, Snaplines, Undo/Redo."""
import copy
import json

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from .controls import BY_TYPE, apply_prop, font_decls, font_for, make_widget, new_props

M, TB, GRID, SNAP, HS = 24, 30, 8, 5, 7        # Rand, Titelleiste, Raster, Snap-Distanz, Handle-Größe
HANDLES = [(0, 0), (.5, 0), (1, 0), (1, .5), (1, 1), (.5, 1), (0, 1), (0, .5)]
CURSORS = [Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor,
           Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor, Qt.SizeHorCursor]
MIME = "application/x-vds-control"
GUIDE = QColor("#e040a0")

LIGHT = """
#formsurface QPushButton { background:#e1e1e1; color:#000; border:1px solid #adadad; padding:2px 8px; border-radius:0; }
#formsurface QLineEdit, #formsurface QPlainTextEdit, #formsurface QListWidget, #formsurface QSpinBox, #formsurface QComboBox
  { background:#fff; color:#000; border:1px solid #7a7a7a; selection-background-color:#3399ff; }
#formsurface QComboBox QAbstractItemView { background:#fff; color:#000; }
#formsurface QLabel, #formsurface QCheckBox, #formsurface QRadioButton, #formsurface QGroupBox { color:#000; background:transparent; }
#formsurface QGroupBox { border:1px solid #dcdcdc; margin-top:8px; } #formsurface QGroupBox::title { subcontrol-origin: margin; left:8px; padding:0 3px; }
#formsurface QFrame[vdsPanel="true"] { border:1px solid #a0a0a0; background:transparent; } #formsurface QProgressBar { border:1px solid #bcbcbc; background:#e6e6e6; color:#000; text-align:center; }
#formsurface QProgressBar::chunk { background:#06b025; }
"""


class Surface(QWidget):
    bg = QColor("#f0f0f0")

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
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
            p.setPen(QPen(QColor("#00b8d9"), 1, Qt.DotLine)); p.setBrush(Qt.NoBrush)
            p.drawRect(c.canvas_rect(cid).adjusted(0, 0, -1, -1))
        for r in c.handle_rects().values():
            p.setPen(QColor("black")); p.setBrush(QColor("white")); p.drawRect(r)
        p.setPen(QPen(GUIDE, 1))
        for kind, v in c.guides:
            if kind == "v":
                p.drawLine(v + M, M + TB, v + M, M + TB + c.model["height"])
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
        self.undo_stack.clear(); self.redo_stack.clear()
        self.rebuild()

    def rebuild(self):
        for w in self.items.values():
            w.deleteLater()
        self.items = {}
        for c in self.model["controls"]:
            self._create_widget(c)
        self.sel = [s for s in self.sel if s in self.items]
        self.relayout()

    def _create_widget(self, c):
        w = make_widget(c["type"], c["props"], self.surface)
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        w.setFocusPolicy(Qt.NoFocus)
        w.setGeometry(c["x"], c["y"], c["w"], c["h"])
        w.show()
        self.items[c["name"]] = w

    def relayout(self):
        m = self.model
        self.setFixedSize(m["width"] + 2 * M, m["height"] + TB + 2 * M)
        self.surface.setGeometry(M, M + TB, m["width"], m["height"])
        c = QColor(m.get("back_color") or "#f0f0f0")
        self.surface.bg = c if c.isValid() else QColor("#f0f0f0")
        decl = font_decls(m)
        self.surface.setStyleSheet(LIGHT + (f"#formsurface * {{ {decl} }}" if decl else ""))
        self.overlay.setGeometry(self.rect()); self.overlay.raise_()
        self.update(); self.overlay.update()

    def control(self, cid):
        return next((c for c in self.model["controls"] if c["name"] == cid), None)

    def canvas_rect(self, cid) -> QRect:
        c = self.control(cid)
        return QRect(c["x"] + M, c["y"] + M + TB, c["w"], c["h"])

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
        names = {c["name"] for c in self.model["controls"]}
        n = 1
        while f"{base}{n}" in names:
            n += 1
        return f"{base}{n}"

    # --- Operationen -------------------------------------------------------------------
    def add_control(self, ctype, pos=None):
        spec = BY_TYPE[ctype]
        self.push_undo()
        name = self.unique_name(spec.base)
        if pos is None:
            k = len(self.model["controls"]) % 10
            pos = (24 + 16 * k, 24 + 16 * k)
        c = {"type": ctype, "name": name, "x": self._grid(pos[0]), "y": self._grid(pos[1]),
             "w": spec.size[0], "h": spec.size[1], "props": new_props(spec, name)}
        self.model["controls"].append(c)
        self._create_widget(c)
        self.set_sel([name]); self.owner.changed("add")

    def set_sel(self, ids):
        self.sel = list(ids)
        self.overlay.update(); self.owner.selection_changed()

    def delete_selected(self):
        if not self.sel:
            return
        self.push_undo()
        self.model["controls"] = [c for c in self.model["controls"] if c["name"] not in self.sel]
        self.set_sel([]); self.rebuild(); self.owner.changed("delete")

    def copy(self):
        self.clipboard = [copy.deepcopy(self.control(s)) for s in self.sel]

    def cut(self):
        self.copy(); self.delete_selected()

    def paste(self):
        if not self.clipboard:
            return
        self.push_undo()
        new = []
        for src in self.clipboard:
            c = copy.deepcopy(src)
            c["name"] = self.unique_name(BY_TYPE[c["type"]].base)
            c["x"] += 16; c["y"] += 16
            for k in ("text", "title"):
                if c["props"].get(k) == src["name"]:
                    c["props"][k] = c["name"]
            self.model["controls"].append(c); self._create_widget(c); new.append(c["name"])
        self.set_sel(new); self.owner.changed("paste")

    def select_all(self):
        self.set_sel([c["name"] for c in self.model["controls"]])

    def set_prop(self, cid, key, value, source="grid"):
        """cid None = Formular. Rückgabe: True, wenn übernommen."""
        if cid is None:
            if key in ("title", "back_color", "font"):
                pass
            elif key not in ("width", "height"):
                return False
            elif value < 100:
                return False
            if self._last_prop != (None, key):
                self.push_undo(); self._last_prop = (None, key)
            self.model[key] = value
            self.relayout()
        else:
            c = self.control(cid)
            if key == "name":
                if not str(value).isidentifier() or any(x["name"] == value for x in self.model["controls"] if x is not c):
                    return False
                self.push_undo(); c["name"] = value; self.items[value] = self.items.pop(cid)
                self.sel = [value if s == cid else s for s in self.sel]
            elif key in ("x", "y", "w", "h"):
                if self._last_prop != (cid, key):
                    self.push_undo(); self._last_prop = (cid, key)
                c[key] = max(8, value) if key in ("w", "h") else value
                self.items[cid].setGeometry(c["x"], c["y"], c["w"], c["h"])
            else:
                if self._last_prop != (cid, key):
                    self.push_undo(); self._last_prop = (cid, key)
                c["props"][key] = value
                apply_prop(self.items[cid], c["type"], key, value, c["props"])
        self.overlay.update()
        self.owner.changed(source)
        return True

    # --- Geometrie-Helfer ----------------------------------------------------------------
    @staticmethod
    def _grid(v):
        return round(v / GRID) * GRID

    def handle_rects(self) -> dict:
        if len(self.sel) == 1:
            r = self.canvas_rect(self.sel[0]); idx = range(8)
        elif not self.sel and self.model:
            r = QRect(M, M + TB, self.model["width"], self.model["height"]); idx = (3, 4, 5)
        else:
            return {}
        return {i: QRect(int(r.x() + HANDLES[i][0] * r.width() - HS // 2), int(r.y() + HANDLES[i][1] * r.height() - HS // 2), HS, HS)
                for i in idx}

    def item_at(self, p):
        for c in reversed(self.model["controls"]):
            if QRect(c["x"] + M, c["y"] + M + TB, c["w"], c["h"]).contains(p):
                return c["name"]
        return None

    # --- Maus ----------------------------------------------------------------------------
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.LeftButton:
            return
        p = e.position().toPoint()
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
        self.drag = dict(mode=mode, start=p, handle=handle, pushed=False,
                         orig={s: (c["x"], c["y"], c["w"], c["h"]) for s in self.sel for c in [self.control(s)]},
                         form=(self.model["width"], self.model["height"]))

    def mouseDoubleClickEvent(self, e):
        cid = self.item_at(e.position().toPoint())
        if cid:
            self.owner.event_requested(cid)

    def mouseMoveEvent(self, e):
        p = e.position().toPoint()
        if self.band:
            self.band = (self.band[0], p)
            r = QRect(*self.band).normalized().translated(-M, -(M + TB))
            self.set_sel([c["name"] for c in self.model["controls"] if r.intersects(QRect(c["x"], c["y"], c["w"], c["h"]))])
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

    def _targets(self):
        xs, ys = [10, self.model["width"] - 10], [10, self.model["height"] - 10]
        for c in self.model["controls"]:
            if c["name"] in self.sel:
                continue
            xs += [c["x"], c["x"] + c["w"] // 2, c["x"] + c["w"]]; ys += [c["y"], c["y"] + c["h"] // 2, c["y"] + c["h"]]
        return xs, ys

    def _do_move(self, dx, dy):
        o = self.drag["orig"]
        bx, by = min(v[0] for v in o.values()), min(v[1] for v in o.values())
        bw, bh = max(v[0] + v[2] for v in o.values()) - bx, max(v[1] + v[3] for v in o.values()) - by
        xs, ys = self._targets()
        out = []
        for start, size, delta, targets, kind in ((bx, bw, dx, xs, "v"), (by, bh, dy, ys, "h")):
            pos = start + delta
            cands = [(t - m, t) for m in (pos, pos + size // 2, pos + size) for t in targets if abs(t - m) <= SNAP]
            if cands:
                adj, line = min(cands, key=lambda a: abs(a[0]))
                pos += adj; self.guides.append((kind, line))
            else:
                pos = self._grid(pos)
            out.append(pos - start)
        for cid, (x, y, w, h) in o.items():
            c = self.control(cid)
            c["x"], c["y"] = x + out[0], y + out[1]
            self.items[cid].move(c["x"], c["y"])

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
        self.drag, self.band, self.guides = None, None, []
        self.overlay.update()

    def keyPressEvent(self, e):
        step = GRID if e.modifiers() & Qt.ShiftModifier else 1
        k = e.key()
        if k == Qt.Key_Delete:
            self.delete_selected()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.sel:
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            self.push_undo()
            for s in self.sel:
                c = self.control(s); c["x"] += dx; c["y"] += dy; self.items[s].move(c["x"], c["y"])
            self.overlay.update(); self.owner.changed("canvas")
        else:
            super().keyPressEvent(e)

    # --- Drag & Drop aus der Toolbox -----------------------------------------------------------
    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasFormat(MIME) else e.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        ctype = bytes(e.mimeData().data(MIME)).decode()
        p = e.position().toPoint() - QPoint(M, M + TB)
        self.add_control(ctype, (p.x(), p.y()))
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
