"""Bausteine zum Einfügen in Webseiten (Vorlagen, die sich an das Projekt anpassen) und das Fenster mit Palette und Seitenstruktur."""
import re
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QLabel, QListWidget, QListWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import source_map as sm
from . import writer

MIME_PREFIX = "vds-block:"
BLOCKS = [("heading", "Überschrift", "h2"), ("paragraph", "Absatz", "p"), ("button", "Button", "a.btn"), ("link", "Link", "a"), ("image", "Bild", "img"),
          ("section", "Abschnitt", "section"), ("columns", "Zwei Spalten", "div"), ("card", "Karte", "div.card"), ("list", "Liste", "ul"),
          ("form", "Kontaktformular", "form"), ("divider", "Trennlinie", "hr")]
WHERE = [("Nach dem Element", "after"), ("In das Element", "inside"), ("Vor dem Element", "before")]


def css_text(root: Path) -> str:
    out = []
    for f in sm.project_files(Path(root), sm.STYLE_EXT, limit=60):
        t = sm.read(f)
        if t:
            out.append(t[:200_000])
    return "\n".join(out)


def snippet(root: Path, block_id: str) -> str | None:
    """HTML-Vorlage (zwei Leerzeichen je Ebene). Nutzt Klassen des Projekts (.btn, .section, .container, .card, Tailwind), sonst schlichte Inline-Stile."""
    root = Path(root)
    tw = writer.uses_tailwind(root)
    css = "" if tw else css_text(root)
    has = lambda c: bool(re.search(r"\." + re.escape(c) + r"\b", css))
    btn = ('class="inline-block rounded-lg bg-indigo-600 px-5 py-2.5 font-semibold text-white"' if tw else
           'class="btn btn-primary"' if has("btn") and has("btn-primary") else
           'style="display:inline-block;padding:.6rem 1.2rem;background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none;font-weight:600"')
    card = ('class="rounded-xl border border-gray-200 p-6 shadow-sm"' if tw else 'class="card"' if has("card") else
            'style="border:1px solid #e5e7eb;border-radius:12px;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.08)"')
    wrap = ('class="mx-auto max-w-5xl px-4"' if tw else 'class="container"' if has("container") else 'style="max-width:1100px;margin:0 auto;padding:0 1rem"')
    sect = ('class="py-16"' if tw else 'class="section"' if has("section") else 'style="padding:4rem 0"')
    field = 'class="w-full rounded border border-gray-300 p-2"' if tw else 'style="width:100%;padding:.5rem;margin:.25rem 0 1rem;box-sizing:border-box"'
    return {
        "heading": "<h2>Neue Überschrift</h2>",
        "paragraph": "<p>Neuer Absatz. Doppelklick in der Vorschau ändert den Text.</p>",
        "button": f'<a {btn} href="#">Button</a>',
        "link": '<a href="#">Neuer Link</a>',
        "image": '<img src="https://placehold.co/600x300" alt="Bild" style="max-width:100%;height:auto" />',
        "section": f"<section {sect}>\n  <div {wrap}>\n    <h2>Neuer Abschnitt</h2>\n    <p>Text des Abschnitts.</p>\n  </div>\n</section>",
        "columns": '<div style="display:flex;gap:1.5rem;flex-wrap:wrap">\n  <div style="flex:1;min-width:240px">\n    <h3>Links</h3>\n    <p>Text</p>\n  </div>\n'
                   '  <div style="flex:1;min-width:240px">\n    <h3>Rechts</h3>\n    <p>Text</p>\n  </div>\n</div>',
        "card": f"<div {card}>\n  <h3>Karte</h3>\n  <p>Kurzer Text zur Karte.</p>\n</div>",
        "list": "<ul>\n  <li>Erster Punkt</li>\n  <li>Zweiter Punkt</li>\n  <li>Dritter Punkt</li>\n</ul>",
        "form": f'<form method="post" action="#">\n  <label>Name\n    <input type="text" name="name" {field} />\n  </label>\n  <label>E-Mail\n    <input type="email" name="email" {field} />\n  </label>\n'
                f'  <label>Nachricht\n    <textarea name="message" rows="4" {field}></textarea>\n  </label>\n  <button type="submit" {btn}>Senden</button>\n</form>',
        "divider": "<hr />",
    }.get(block_id)


class BlockList(QListWidget):
    """Palette: Einträge lassen sich auf die Web-Vorschau ziehen (Text „vds-block:<id>“)."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True); self.setDragDropMode(QAbstractItemView.DragOnly); self.setDefaultDropAction(Qt.CopyAction)
        for bid, label, tag in BLOCKS:
            it = QListWidgetItem(f"{label}   <{tag}>"); it.setData(Qt.UserRole, bid); self.addItem(it)

    def mimeData(self, items):
        m = QMimeData()
        m.setText(MIME_PREFIX + items[0].data(Qt.UserRole))
        return m

    def supportedDropActions(self):
        return Qt.CopyAction


class BlocksPanel(QWidget):
    insertRequested = Signal(str, str)            # Baustein, Ort (before | after | inside)
    outlineSelected = Signal(str)                 # CSS-Pfad
    outlineWanted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.where = QComboBox()
        for label, key in WHERE:
            self.where.addItem(label, key)
        self.blocks = BlockList()
        self.blocks.itemDoubleClicked.connect(lambda it: self.insertRequested.emit(it.data(Qt.UserRole), self.where.currentData()))
        hint = QLabel("Doppelklick fügt am gewählten Element ein – oder einen Baustein auf die Web-Vorschau ziehen (im Bearbeiten-Modus).")
        hint.setWordWrap(True); hint.setObjectName("sub")
        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); self.tree.setUniformRowHeights(True)
        self.tree.itemClicked.connect(lambda it, _c: self.outlineSelected.emit(it.data(0, Qt.UserRole) or ""))
        self._items: dict = {}
        tabs = QTabWidget()
        first = QWidget(); fl = QVBoxLayout(first); fl.setContentsMargins(4, 4, 4, 4)
        fl.addWidget(QLabel("Einfügen:")); fl.addWidget(self.where); fl.addWidget(self.blocks, 1); fl.addWidget(hint)
        tabs.addTab(first, "Bausteine"); tabs.addTab(self.tree, "Struktur")
        tabs.currentChanged.connect(lambda i: i == 1 and self.outlineWanted.emit())
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.addWidget(tabs)

    def set_outline(self, nodes: list):
        self.tree.clear(); self._items = {}

        def add(parent, n, depth):
            label = n["t"] + (f"#{n['i']}" if n.get("i") else "") + "".join("." + c for c in n.get("c", [])[:2]) + (f"  – {n['x']}" if n.get("x") else "")
            it = QTreeWidgetItem(parent, [label]); it.setData(0, Qt.UserRole, n["p"]); self._items[n["p"]] = it
            for k in n.get("k", []):
                add(it, k, depth + 1)
            if depth < 2:
                it.setExpanded(True)
        for n in nodes or []:
            add(self.tree, n, 0)

    def select_path(self, path: str):
        it = self._items.get(path)
        if it is None:
            return
        self.tree.blockSignals(True)
        p = it.parent()
        while p is not None:
            p.setExpanded(True); p = p.parent()
        self.tree.setCurrentItem(it); self.tree.scrollToItem(it)
        self.tree.blockSignals(False)
