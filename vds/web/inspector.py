"""Web-Element-Inspektor: zeigt das angeklickte Element, ändert Stile live in der Vorschau, findet die Quelle und schreibt Änderungen in den Quellcode."""
import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from . import source_map, writer

GROUPS = [("Layout", ["display", "position", "width", "height", "margin", "padding", "top", "left", "z-index", "overflow"]),
          ("Flex", ["flex-direction", "justify-content", "align-items", "gap"]),
          ("Text", ["color", "font-family", "font-size", "font-weight", "font-style", "line-height", "text-align", "text-decoration", "letter-spacing"]),
          ("Aussehen", ["background-color", "border", "border-radius", "box-shadow", "opacity"])]
COLOR_PROPS = {"color", "background-color"}


def describe(info: dict) -> str:
    return info["tag"] + (f"#{info['id']}" if info.get("id") else "") + "".join("." + c for c in info.get("classes", [])[:4])


class WriteDialog(QDialog):
    """Wohin sollen die Änderungen? Pro Element eine Auswahl der Möglichkeiten, darunter der Unterschied im Quellcode."""

    def __init__(self, root: Path, items: list, parent=None):
        super().__init__(parent)
        self.root = root
        self.setWindowTitle("Änderungen in den Quellcode übernehmen"); self.resize(760, 560)
        self.items = items                                # [(Überschrift, [Plan])]
        self.combos = []
        lay = QVBoxLayout(self)
        for title, plans in items:
            box = QGroupBox(title); bl = QVBoxLayout(box)
            c = QComboBox()
            if plans:
                for p in plans:
                    c.addItem(p.label, p)
            else:
                c.addItem("Keine passende Stelle gefunden – nichts zu schreiben"); c.setEnabled(False)
            c.currentIndexChanged.connect(self._preview)
            bl.addWidget(c); self.combos.append(c); lay.addWidget(box)
        self.view = QPlainTextEdit(); self.view.setReadOnly(True); self.view.setPlaceholderText("Unterschied")
        lay.addWidget(self.view, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.button(QDialogButtonBox.Ok).setText("Übernehmen")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._preview()

    def chosen(self) -> list:
        return [c.currentData() for c in self.combos if c.currentData() is not None]

    def _preview(self, *_):
        self.view.setPlainText("\n".join(p.diff(self.root) for p in self.chosen()))


class ColorField(QWidget):
    def __init__(self, on_change):
        super().__init__()
        self.edit = QLineEdit(); self.btn = QPushButton("●"); self.btn.setFixedWidth(26)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(3); lay.addWidget(self.edit); lay.addWidget(self.btn)
        self.btn.clicked.connect(self._pick)
        self.edit.editingFinished.connect(lambda: on_change(self.edit.text()))
        self._on_change = on_change

    def _pick(self):
        c = QColorDialog.getColor(QColor(writer.hexcolor(self.edit.text()) or "#ffffff"), self, "Farbe wählen", QColorDialog.DontUseNativeDialog)
        if c.isValid():
            self.edit.setText(c.name()); self._on_change(c.name())


class WebInspector(QWidget):
    openFile = Signal(str, int)
    designerControl = Signal(str)
    applied = Signal(list)                 # geschriebene Dateien

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.root = Path(".")
        self.info: dict | None = None
        self.pending: dict = {}            # Pfad -> {"info", "props"}
        self.text_pending: dict = {}       # Pfad -> (alt, neu, info)
        self.undo_stack: list = []
        self.candidates: list = []
        self.fields: dict = {}
        self.head = QLabel("Kein Element gewählt – in der Web-Vorschau „⌖ Auswählen“ und ein Element anklicken.")
        self.head.setWordWrap(True); self.head.setTextInteractionFlags(Qt.TextSelectableByMouse)
        nav = QHBoxLayout()
        for text, tip, fn in (("↑ Eltern", "Übergeordnetes Element", lambda: self._rel("parent")), ("↓ Kind", "Erstes Kindelement", lambda: self._rel("child")),
                              ("← Vorher", "Vorheriges Geschwister", lambda: self._rel("prev")), ("→ Nachher", "Nächstes Geschwister", lambda: self._rel("next"))):
            b = QPushButton(text); b.setToolTip(tip); b.clicked.connect(fn); nav.addWidget(b)
        self.text_edit = QLineEdit(); self.text_edit.setPlaceholderText("Text des Elements")
        self.text_edit.editingFinished.connect(self._text_changed)
        body = QWidget(); form_lay = QVBoxLayout(body); form_lay.setContentsMargins(4, 4, 4, 4)
        tform = QFormLayout(); tform.addRow("Text", self.text_edit); form_lay.addLayout(tform)
        for title, props in GROUPS:
            box = QGroupBox(title); f = QFormLayout(box)
            for p in props:
                w = ColorField(lambda v, p=p: self.set_style(p, v)) if p in COLOR_PROPS else QLineEdit()
                if isinstance(w, QLineEdit):
                    w.editingFinished.connect(lambda p=p, w=w: self.set_style(p, w.text()))
                self.fields[p] = w
                f.addRow(p, w)
            form_lay.addWidget(box)
        form_lay.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(body); scroll.setFrameShape(QScrollArea.NoFrame)
        self.src_list = QListWidget(); self.src_list.setMaximumHeight(110)
        self.src_list.itemDoubleClicked.connect(lambda it: self._open_candidate(it.data(Qt.UserRole)))
        self.btn_src = QPushButton("Zum Code springen"); self.btn_src.clicked.connect(self.jump_to_source)
        self.changes = QListWidget(); self.changes.setMaximumHeight(90)
        self.btn_write = QPushButton("In Quellcode übernehmen …"); self.btn_write.clicked.connect(self.write_back)
        self.btn_discard = QPushButton("Verwerfen"); self.btn_discard.clicked.connect(self.discard)
        self.btn_undo = QPushButton("Letzte Übernahme rückgängig"); self.btn_undo.clicked.connect(self.undo_last)
        wr = QHBoxLayout(); wr.addWidget(self.btn_write); wr.addWidget(self.btn_discard)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6); lay.setSpacing(5)
        lay.addWidget(self.head); lay.addLayout(nav); lay.addWidget(scroll, 1)
        lay.addWidget(self.btn_src); lay.addWidget(self.src_list)
        lay.addWidget(QLabel("Nicht übernommene Änderungen:")); lay.addWidget(self.changes); lay.addLayout(wr); lay.addWidget(self.btn_undo)
        panel.picked.connect(self.show_info)
        panel.changed.connect(self._changed)
        panel.textChanged.connect(self._text_msg)
        self._refresh()

    def set_root(self, root: Path):
        self.root = Path(root).resolve()

    # --- Anzeige --------------------------------------------------------------------------------------------
    def show_info(self, info: dict):
        self.info = info
        self.head.setText(f"{describe(info)}   {round(info['rect']['w'])}×{round(info['rect']['h'])}\n{info['path']}")
        ov = info.get("overrides", {})
        for p, w in self.fields.items():
            val = ov.get(p) or info["computed"].get(p, "")
            (w.edit if isinstance(w, ColorField) else w).setText(val)
        self.text_edit.setEnabled(not info.get("children")); self.text_edit.setText(info.get("text", ""))
        self.src_list.clear(); self.candidates = []
        self.btn_src.setText("Zum Code springen" if not info.get("vds") else f"Im Designer öffnen ({info['vds']})")

    def _rel(self, kind: str):
        self.panel.eval(f"window.__vds && window.__vds.selectRelative({json.dumps(kind)})")

    def set_style(self, prop: str, value: str):
        if not self.info:
            return
        self.panel.eval(f"window.__vds && window.__vds.setStyle({json.dumps(self.info['path'])}, {json.dumps(prop)}, {json.dumps(value.strip())})")

    def _text_changed(self):
        if self.info and self.text_edit.isEnabled() and self.text_edit.text() != self.info.get("text", ""):
            self.panel.eval(f"window.__vds && window.__vds.setText({json.dumps(self.info['path'])}, {json.dumps(self.text_edit.text())})")

    # --- Änderungen sammeln -------------------------------------------------------------------------------------
    def _changed(self, data: dict):
        path, props = data["path"], data.get("props", {})
        if props:
            self.pending[path] = {"info": data["info"], "props": props}
        else:
            self.pending.pop(path, None)
        if self.info and self.info["path"] == path:
            self.show_info(data["info"])
        self._refresh()

    def _text_msg(self, data: dict):
        old, new = data.get("old", ""), data.get("new", "")
        if old.strip() == new.strip():
            self.text_pending.pop(data["path"], None)
        else:
            self.text_pending[data["path"]] = (old, new, data["info"])
        self._refresh()

    def _refresh(self):
        self.changes.clear()
        for path, d in self.pending.items():
            self.changes.addItem(f"{describe(d['info'])}: " + ", ".join(f"{k}: {v}" for k, v in d["props"].items()))
        for path, (old, new, info) in self.text_pending.items():
            self.changes.addItem(f"{describe(info)}: Text „{old[:20]}“ → „{new[:20]}“")
        n = len(self.pending) + len(self.text_pending)
        self.btn_write.setEnabled(n > 0); self.btn_discard.setEnabled(n > 0); self.btn_undo.setEnabled(bool(self.undo_stack))

    def discard(self):
        self.panel.eval("window.__vds && window.__vds.revertAll()")
        self.pending.clear(); self.text_pending.clear(); self._refresh()
        if self.info:
            self.panel.eval("window.__vds && window.__vds.selected()", lambda i: i and self.show_info(i))

    # --- Quelle -------------------------------------------------------------------------------------------------------
    def jump_to_source(self):
        if not self.info:
            return
        if self.info.get("vds"):
            return self.designerControl.emit(self.info["vds"])
        self.candidates = source_map.search(self.root, self.info)
        self.src_list.clear()
        for c in self.candidates:
            it = QListWidgetItem(c.label(self.root)); it.setData(Qt.UserRole, c); self.src_list.addItem(it)
        if not self.candidates:
            self.src_list.addItem("Keine Stelle im Quellcode gefunden (dynamisch erzeugt?)")
        elif len(self.candidates) == 1 or self.candidates[0].score - (self.candidates[1].score if len(self.candidates) > 1 else 0) >= 15:
            self._open_candidate(self.candidates[0])                 # klarer Treffer: gleich öffnen

    def _open_candidate(self, c):
        if c is not None:
            self.openFile.emit(str(c.file), c.line)

    # --- Zurückschreiben --------------------------------------------------------------------------------------------------
    def build_plans(self) -> list:
        items = []
        for path, d in self.pending.items():
            plans = writer.plan_style(self.root, d["info"], d["props"])
            tp = self.text_pending.get(path)
            items.append((f"{describe(d['info'])} – {', '.join(d['props'])}", plans))
        for path, (old, new, info) in self.text_pending.items():
            items.append((f"{describe(info)} – Text", writer.text_plans(self.root, old, new, source_map.search(self.root, info))))
        return items

    def write_back(self, confirm=True) -> list:
        items = self.build_plans()
        if not items:
            return []
        dlg = WriteDialog(self.root, items, self)
        if confirm and not dlg.exec():
            return []
        plans = dlg.chosen()
        if not plans:
            QMessageBox.information(self, "Quellcode", "Für diese Änderungen wurde keine passende Stelle im Quellcode gefunden.")
            return []
        return self.commit(plans)

    def commit(self, plans: list) -> list:
        plans, skipped = writer.merge(plans)                     # mehrere Pläne für dieselbe Datei zusammenfassen
        if skipped:
            QMessageBox.information(self, "Quellcode", f"{len(skipped)} Änderung(en) überschneiden sich mit einer anderen und wurden nicht übernommen.")
        backup = writer.apply(plans)
        self.undo_stack.append(backup)
        self.panel.eval("window.__vds && window.__vds.revertAll()")
        self.pending.clear(); self.text_pending.clear()
        self._refresh()
        files = [str(f) for f in backup]
        self.applied.emit(files)
        return files

    def undo_last(self):
        if self.undo_stack:
            writer.undo(self.undo_stack.pop())
            self._refresh()
            self.panel.schedule_reload(force=True)
