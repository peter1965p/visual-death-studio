"""Eigenschaften-Fenster: Dateiinfos oder – bei aktivem Designer – Objektauswahl plus Property-Grid."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..ui.font_dialog import FontDialog, describe, dict_to_font, font_to_dict
from ..designer.controls import BY_TYPE, CHOICES, KIND_DEFAULT, PROP_INFO, prop_keys
from ..designer.layouts import LAYOUT_DEFAULTS, LAYOUT_KEYS
from .tools import Properties


class ColorEdit(QWidget):
    """Farbfeld mit Farbwähler, Hex-/Namenseingabe und Zurücksetzen (leer = Standardfarbe)."""

    def __init__(self, value: str, setter):
        super().__init__()
        self.setter = setter
        self.swatch = QPushButton(); self.swatch.setFixedSize(22, 20)
        self.text = QLineEdit(value); self.text.setPlaceholderText("(Standard)"); self.text.setMinimumWidth(30)
        self.clear = QPushButton("✕"); self.clear.setFixedSize(22, 20); self.clear.setToolTip("Auf Standardfarbe zurücksetzen")
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(3)
        for w in (self.swatch, self.text, self.clear):
            lay.addWidget(w)
        self._paint(value)
        self.swatch.clicked.connect(self._pick)
        self.text.editingFinished.connect(self._typed)
        self.clear.clicked.connect(lambda: self._set(""))

    def _paint(self, value):
        c = QColor(value)
        self.swatch.setStyleSheet(f"background:{c.name()}; border:1px solid #888;" if value and c.isValid() else "background:transparent; border:1px dashed #666;")

    def _set(self, value):
        self.text.setText(value); self._paint(value); self.setter(value)

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.text.text()) if QColor.isValidColor(self.text.text()) else QColor("#f0f0f0"), self,
                                  "Farbe wählen", QColorDialog.DontUseNativeDialog)
        if c.isValid():
            self._set(c.name())

    def _typed(self):
        t = self.text.text().strip()
        if not t:
            return self._set("")
        if QColor.isValidColor(t):
            self._set(QColor(t).name())
        else:
            self.text.setText("")      # ungültige Eingabe verwerfen
            self._paint("")


class FontEdit(QWidget):
    """Zeigt die Schrift als Text und öffnet den futuristischen Schriftart-Dialog; ✕ setzt auf Standard zurück."""

    def __init__(self, value, setter):
        super().__init__()
        self.setter = setter
        self.value = value if isinstance(value, dict) else {}
        self.text = QLineEdit(describe(self.value)); self.text.setReadOnly(True); self.text.setPlaceholderText("(Standard)"); self.text.setMinimumWidth(30)
        self.pick = QPushButton("Aa…"); self.pick.setFixedHeight(20); self.pick.setToolTip("Schriftart wählen")
        self.clear = QPushButton("✕"); self.clear.setFixedSize(22, 20); self.clear.setToolTip("Auf Standardschrift zurücksetzen")
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(3)
        for w in (self.text, self.pick, self.clear):
            lay.addWidget(w)
        self.pick.clicked.connect(self._pick); self.clear.clicked.connect(lambda: self._set(""))

    def _set(self, v):
        self.value = v if isinstance(v, dict) else {}
        self.text.setText(describe(self.value)); self.setter(v)

    def _pick(self):
        f = FontDialog.get_font(dict_to_font(self.value) if self.value else QFont(), self.window(), False, "Schriftart")
        if f is not None:
            self._set(font_to_dict(f))


class PropertiesDock(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_props = Properties()
        self.grid = QTableWidget(0, 2)
        self.grid.horizontalHeader().hide(); self.grid.verticalHeader().hide()
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.setColumnWidth(0, 120)
        self.grid.setShowGrid(False); self.grid.setSelectionMode(QAbstractItemView.NoSelection)
        self.combo = QComboBox()
        self.combo.activated.connect(self._combo_activated)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.file_props)
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self.combo); lay.addWidget(self.grid)
        self.stack.addWidget(page)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(self.stack)
        self.designer = None

    def show_file(self, path):
        self.detach()
        self.file_props.show_path(path)
        self.stack.setCurrentIndex(0)

    def detach(self):
        if self.designer:
            for sig in (self.designer.selectionChanged, self.designer.modelChanged):
                try:
                    sig.disconnect(self._on_designer)
                except (RuntimeError, TypeError):
                    pass
        self.designer = None

    def show_designer(self, designer):
        self.detach()
        self.designer = designer
        designer.selectionChanged.connect(self._on_designer)
        designer.modelChanged.connect(self._on_designer)
        self.stack.setCurrentIndex(1)
        self._on_designer("select")

    # --- Objektauswahl ------------------------------------------------------------------
    def _selected(self):
        sel = self.designer.canvas.sel
        return sel[0] if len(sel) == 1 else None

    def _combo_activated(self, i):
        m = self.designer.model
        names = [c["name"] for c in m["controls"] + m["components"]]
        self.designer.canvas.set_sel([] if i == 0 else [names[i - 1]])

    def _on_designer(self, source="select"):
        if not self.designer:
            return
        m, cur = self.designer.model, self._selected()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(f"{m['name']}  (Form)")
        names = {c["name"]: c for c in m["controls"]}
        for c in m["controls"]:
            depth, p = 0, c.get("parent")
            while p in names:
                depth += 1; p = names[p].get("parent")
            self.combo.addItem(f"{'    ' * depth}{c['name']}  ({c['type']})")
        for c in m["components"]:
            self.combo.addItem(f"{c['name']}  ({c['type']})")
        self.combo.setCurrentIndex(0 if cur is None else 1 + [c["name"] for c in m["controls"] + m["components"]].index(cur))
        self.combo.blockSignals(False)
        if source != "grid":
            self._build_grid(cur)

    # --- Grid -------------------------------------------------------------------------------
    def _section(self, title):
        r = self.grid.rowCount(); self.grid.insertRow(r)
        it = QTableWidgetItem(title); it.setFlags(Qt.ItemIsEnabled)
        f = it.font(); f.setBold(True); it.setFont(f)
        self.grid.setItem(r, 0, it); self.grid.setSpan(r, 0, 1, 2)
        it.setBackground(self.palette().alternateBase())

    def _row(self, label, editor):
        r = self.grid.rowCount(); self.grid.insertRow(r)
        it = QTableWidgetItem(label); it.setFlags(Qt.ItemIsEnabled); it.setForeground(Qt.gray)
        self.grid.setItem(r, 0, it); self.grid.setCellWidget(r, 1, editor)

    def _edit(self, kind, value, setter, choices=None, readonly=False):
        if kind == "int":
            w = QSpinBox(); w.setRange(-10000, 100000); w.setValue(int(value)); w.valueChanged.connect(setter)
        elif kind == "font":
            w = FontEdit(value, setter)
        elif kind == "color":
            w = ColorEdit(str(value or ""), setter)
        elif kind in ("bool", "choice"):
            w = QComboBox()
            opts = ["True", "False"] if kind == "bool" else choices
            w.addItems(opts); w.setCurrentText(str(value) if kind == "choice" else str(bool(value)))
            w.activated.connect(lambda _i, w=w: setter(w.currentText() == "True" if kind == "bool" else w.currentText()))
        else:
            text = ", ".join(value) if kind == "items" else str(value)
            w = QLineEdit(text); w.setReadOnly(readonly)
            if kind == "items":
                w.editingFinished.connect(lambda w=w: setter([s.strip() for s in w.text().split(",") if s.strip()]))
            else:
                w.editingFinished.connect(lambda w=w: setter(w.text()))
        return w

    def _build_grid(self, cid):
        g, cv = self.grid, self.designer.canvas
        g.setRowCount(0)
        g.clearSpans()
        if cid is None:
            m = cv.model
            self._section("Design")
            self._row("(Name)", self._edit("str", m["name"], lambda v: None, readonly=True))
            self._row("Text", self._edit("str", m["title"], lambda v: cv.set_prop(None, "title", v)))
            self._row("Font", self._edit("font", m.get("font", ""), lambda v: cv.set_prop(None, "font", v)))
            self._row("BackColor", self._edit("color", m.get("back_color", ""), lambda v: cv.set_prop(None, "back_color", v)))
            self._section("Layout")
            self._row("Width", self._edit("int", m["width"], lambda v: cv.set_prop(None, "width", v)))
            self._row("Height", self._edit("int", m["height"], lambda v: cv.set_prop(None, "height", v)))
            for k in LAYOUT_KEYS:
                label, kind, _ = PROP_INFO[k]
                self._row(label, self._edit(kind, m.get(k, LAYOUT_DEFAULTS[k]), lambda v, k=k: cv.set_prop(None, k, v), CHOICES.get(k)))
            return
        c = cv.control(cid)
        self._section("Design")
        self._row("(Name)", self._edit("str", c["name"], lambda v: self._rename(cid, v)))
        if "x" in c:                                                       # Komponenten haben keine Geometrie
            self._section("Layout")
            for key, label in (("x", "Location X"), ("y", "Location Y"), ("w", "Width"), ("h", "Height")):
                self._row(label, self._edit("int", c[key], lambda v, k=key: cv.set_prop(cid, k, v)))
        cats: dict[str, list] = {}
        for k in prop_keys(BY_TYPE[c["type"]]):
            label, kind, cat = PROP_INFO[k]
            cats.setdefault(cat, []).append((k, label, kind))
        for k, label, kind in cats.pop("Layout", []):                      # Layout-Eigenschaften von Containern
            self._row(label, self._edit(kind, c["props"].get(k, LAYOUT_DEFAULTS[k]), lambda v, k=k: cv.set_prop(cid, k, v), CHOICES.get(k)))
        for cat in ("Darstellung", "Verhalten", "Daten"):
            if cat in cats:
                self._section(cat)
                for k, label, kind in cats[cat]:
                    self._row(label, self._edit(kind, c["props"].get(k, KIND_DEFAULT[kind]), lambda v, k=k: cv.set_prop(cid, k, v), CHOICES.get(k)))

    def _rename(self, cid, v):
        if not self.designer.canvas.set_prop(cid, "name", v.strip()):
            self._build_grid(cid)
