"""Diff-Ansicht: Seite an Seite oder inline, synchrones Scrollen, Hunk-Leiste mit Übernehmen/Zurücksetzen."""
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QShortcut, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextEdit, QToolTip, QVBoxLayout,
                               QWidget)

from ..editor.highlighter import PygmentsHighlighter
from ..theme import EDITOR_FONT
from . import engine
from ..theme import t as tc

BG = {k: tc(v) for k, v in {"add": "#10372d", "del": "#3b1829", "chg_l": "#3b1829", "chg_r": "#10372d"}.items()}
SPAN = {k: tc(v) for k, v in {"l": "#8c2c55", "r": "#1c7a58"}.items()}
FILLER = QBrush(QColor(tc("#1a2040")), Qt.BDiagPattern)
HUNK_COLOR = {"add": QColor(115, 201, 145, 70), "del": QColor(241, 76, 76, 70), "chg": QColor(204, 167, 0, 70)}


class _Gutter(QWidget):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.pane.gutter_width(), 0)

    def paintEvent(self, e):
        self.pane.paint_gutter(e)


class _Pane(QPlainTextEdit):
    def __init__(self, filename=""):
        super().__init__()
        f = QFont(); f.setFamilies([s.strip() for s in EDITOR_FONT.split(",")]); f.setPointSize(10); f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        self.setReadOnly(True)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.numbers: list[str] = []
        self.gutter = _Gutter(self)
        self.highlighter = PygmentsHighlighter(self.document(), filename)
        self.updateRequest.connect(lambda r, dy: self.gutter.scroll(0, dy) if dy else self.gutter.update())
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def gutter_width(self):
        n = max((len(x) for x in self.numbers), default=3)
        return 12 + self.fontMetrics().horizontalAdvance("9") * max(n, 3)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, e):
        p = QPainter(self.gutter)
        p.fillRect(e.rect(), QColor(tc("#080a16")))
        p.setPen(QColor(tc("#4d5b82")))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= e.rect().bottom():
            h = round(self.blockBoundingRect(block).height())
            i = block.blockNumber()
            if block.isVisible() and i < len(self.numbers):
                p.drawText(0, top, self.gutter.width() - 6, h, Qt.AlignRight | Qt.AlignVCenter, self.numbers[i])
            block = block.next()
            top += h
        p.end()

    def set_content(self, texts, numbers, kinds, spans):
        """kinds[i]: Hintergrund-Schlüssel oder 'filler'|None; spans[i]: [(start, ende, Farbschlüssel)]."""
        self.numbers = numbers
        self.setPlainText("\n".join(texts))
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        sels = []
        for i, kind in enumerate(kinds):
            block = self.document().findBlockByNumber(i)
            if kind:
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(FILLER if kind == "filler" else QColor(BG[kind]))
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = self.textCursor(); s.cursor.setPosition(block.position()); s.cursor.clearSelection()
                sels.append(s)
            for a, b, key in spans[i]:
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(QColor(SPAN[key]))
                c = self.textCursor(); c.setPosition(block.position() + a); c.setPosition(block.position() + b, c.MoveMode.KeepAnchor)
                s.cursor = c
                sels.append(s)
        self.setExtraSelections(sels)
        self.gutter.update()

    def block_top(self, i):
        b = self.document().findBlockByNumber(i)
        return self.blockBoundingGeometry(b).translated(self.contentOffset()).top()

    def block_bottom(self, i):
        b = self.document().findBlockByNumber(i)
        return self.blockBoundingGeometry(b).translated(self.contentOffset()).bottom()


class _HunkBar(QWidget):
    """Schmale Leiste neben den Texten: Farbband je Änderung plus Pfeil-Schaltflächen zum Übernehmen."""
    def __init__(self, view):
        super().__init__()
        self.v = view
        self.setFixedWidth(50)
        self.setMouseTracking(True)
        self.buttons: list = []     # [(QRect, hunk_index, 'right'|'left')]

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(tc("#0c0f22")))
        self.buttons = []
        v = self.v
        for h in v.hunks:
            span = v.hunk_blocks.get(h.index)
            if not span:
                continue
            y1, y2 = v.left.block_top(span[0]), v.left.block_bottom(span[1])
            if y2 < 0 or y1 > self.height():
                continue
            kind = "add" if h.a1 == h.a2 else "del" if h.b1 == h.b2 else "chg"
            p.fillRect(QRect(0, int(y1), self.width(), max(2, int(y2 - y1))), HUNK_COLOR[kind])
            if h.index == v.current:
                p.setPen(QColor(tc("#00e5ff"))); p.drawRect(0, int(y1), self.width() - 1, max(2, int(y2 - y1)) - 1)
            ops = []
            if v.right_apply:
                ops.append(("right", "↩" if not v.left_apply else "▶"))
            if v.left_apply:
                ops.append(("left", "◀"))
            x = 4
            for op, glyph in ops:
                r = QRect(x, int(y1) + 1, 20, 18)
                p.setPen(QColor(tc("#2a3a6a"))); p.setBrush(QColor(tc("#161b3a"))); p.drawRoundedRect(r, 3, 3)
                p.setPen(QColor(tc("#dbe6ff"))); p.drawText(r, Qt.AlignCenter, glyph)
                self.buttons.append((r, h.index, op))
                x += 22
        p.end()

    def _hit(self, pos):
        return next(((i, op) for r, i, op in self.buttons if r.contains(pos)), None)

    def mouseMoveEvent(self, e):
        hit = self._hit(e.position().toPoint())
        self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
        if hit:
            tip = {"right": "Änderung zurücksetzen (links → rechts)" if not self.v.left_apply else "Linke Seite nach rechts übernehmen",
                   "left": "Rechte Seite nach links übernehmen"}[hit[1]]
            QToolTip.showText(e.globalPosition().toPoint(), tip, self)

    def mousePressEvent(self, e):
        hit = self._hit(e.position().toPoint())
        if hit and e.button() == Qt.LeftButton:
            self.v.apply_hunk(*hit)


class DiffView(QWidget):
    applied = Signal()      # nach einer übernommenen Änderung

    def __init__(self, parent=None):
        super().__init__(parent)
        self.left_t = engine.Text([]); self.right_t = engine.Text([])
        self.rows, self.hunks, self.hunk_blocks, self.current = [], [], {}, -1
        self.left_apply = self.right_apply = None
        self.inline, self.ignore_ws, self._sync = False, False, False
        self.left, self.right = _Pane(), _Pane()
        self.bar = _HunkBar(self)
        # Kopfzeile
        self.title_l, self.title_r = QLabel(), QLabel()
        self.stats = QLabel(); self.pos = QLabel()
        self.b_prev, self.b_next = QPushButton("▲ Vorherige"), QPushButton("▼ Nächste")
        self.b_inline = QPushButton("Inline"); self.b_inline.setCheckable(True)
        self.c_ws = QCheckBox("Leerraum ignorieren")
        self.b_prev.clicked.connect(lambda: self.goto_hunk(self.current - 1))
        self.b_next.clicked.connect(lambda: self.goto_hunk(self.current + 1))
        self.b_inline.toggled.connect(self._set_inline); self.c_ws.toggled.connect(self._set_ws)
        top = QHBoxLayout(); top.setContentsMargins(8, 4, 8, 4); top.setSpacing(14)
        for w in (self.stats, self.pos):
            top.addWidget(w)
        top.addStretch(); [top.addWidget(w) for w in (self.c_ws, self.b_inline, self.b_prev, self.b_next)]
        self.titles = QHBoxLayout(); self.titles.setContentsMargins(8, 2, 8, 2)
        self.titles.addWidget(self.title_l, 1); self.titles.addSpacing(50); self.titles.addWidget(self.title_r, 1)
        self.panes = QHBoxLayout(); self.panes.setContentsMargins(0, 0, 0, 0); self.panes.setSpacing(0)
        self.panes.addWidget(self.left, 1); self.panes.addWidget(self.bar); self.panes.addWidget(self.right, 1)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addLayout(top); lay.addLayout(self.titles); lay.addLayout(self.panes, 1)
        for pane, other in ((self.left, self.right), (self.right, self.left)):
            pane.verticalScrollBar().valueChanged.connect(lambda v, o=other: self._scroll(o.verticalScrollBar(), v))
            pane.horizontalScrollBar().valueChanged.connect(lambda v, o=other: self._scroll(o.horizontalScrollBar(), v))
            pane.verticalScrollBar().valueChanged.connect(self.bar.update)
        for key, fn in (("F8", lambda: self.goto_hunk(self.current + 1)), ("Shift+F8", lambda: self.goto_hunk(self.current - 1))):
            sc = QShortcut(QKeySequence(key), self); sc.setContext(Qt.WidgetWithChildrenShortcut); sc.activated.connect(fn)
        self.setFocusProxy(self.left)

    # --- Daten -------------------------------------------------------------------------------
    def set_sources(self, left: str, right: str, left_title="", right_title="", filename="", left_apply=None, right_apply=None):
        """left_apply/right_apply: Funktion(text), wenn die jeweilige Seite veränderbar ist (sonst None)."""
        self.left_t, self.right_t = engine.Text.parse(left), engine.Text.parse(right)
        self.left_apply, self.right_apply = left_apply, right_apply
        self.titles_text = (left_title, right_title)
        self.title_l.setText(left_title); self.title_r.setText(right_title)
        for pane in (self.left, self.right):
            pane.highlighter.set_filename(filename)
        self.current = -1
        self.refresh()
        self.goto_hunk(0)

    def refresh(self):
        self.rows, self.hunks = engine.diff(self.left_t.lines, self.right_t.lines, self.ignore_ws)
        add, rem = engine.stats(self.rows)
        self.stats.setText(tc(f"<span style='color:#3dffa1'>+{add}</span>  <span style='color:#ff4d6d'>−{rem}</span>")
                           if self.hunks else "Keine Unterschiede")
        self.stats.setTextFormat(Qt.RichText)
        self.b_prev.setEnabled(bool(self.hunks)); self.b_next.setEnabled(bool(self.hunks))
        (self._render_inline if self.inline else self._render_side)()
        self.bar.update()

    def _render_side(self):
        self.right.setVisible(True); self.title_r.setVisible(True)
        self.title_l.setText(self.titles_text[0])
        L = ([], [], [], []); R = ([], [], [], [])
        self.hunk_blocks = {}
        for i, r in enumerate(self.rows):
            lt = None if r.kind == "add" else r.ltext
            rt = None if r.kind == "del" else r.rtext
            L[0].append(lt or ""); L[1].append("" if r.lno is None else str(r.lno))
            L[2].append("filler" if lt is None else ("chg_l" if r.kind in ("del", "chg") else None))
            L[3].append([(a, b, "l") for a, b in r.lspans])
            R[0].append(rt or ""); R[1].append("" if r.rno is None else str(r.rno))
            R[2].append("filler" if rt is None else ("chg_r" if r.kind in ("add", "chg") else None))
            R[3].append([(a, b, "r") for a, b in r.rspans])
            if r.hunk is not None:
                s = self.hunk_blocks.setdefault(r.hunk, [i, i]); s[1] = i
        self.left.set_content(*L); self.right.set_content(*R)

    def _render_inline(self):
        self.right.setVisible(False); self.title_r.setVisible(False)
        self.title_l.setText(f"{self.titles_text[0]}   →   {self.titles_text[1]}")
        texts, nums, kinds, spans = [], [], [], []
        self.hunk_blocks = {}

        def add(text, num, kind, sp, hunk):
            texts.append(text); nums.append(num); kinds.append(kind); spans.append(sp)
            if hunk is not None:
                s = self.hunk_blocks.setdefault(hunk, [len(texts) - 1, len(texts) - 1]); s[1] = len(texts) - 1
        i = 0
        while i < len(self.rows):
            r = self.rows[i]
            if r.kind == "eq":
                add(r.ltext, f"{r.lno:>4} {r.rno:>4}", None, [], None); i += 1; continue
            j = i
            while j < len(self.rows) and self.rows[j].hunk == r.hunk:
                j += 1
            grp = self.rows[i:j]
            for g in grp:
                if g.kind in ("del", "chg"):
                    add(g.ltext, f"{g.lno:>4}     ", "del", [(a, b, "l") for a, b in g.lspans], g.hunk)
            for g in grp:
                if g.kind in ("add", "chg"):
                    add(g.rtext, f"     {g.rno:>4}", "add", [(a, b, "r") for a, b in g.rspans], g.hunk)
            i = j
        self.left.set_content(texts, nums, kinds, spans)

    # --- Bedienung ------------------------------------------------------------------------------
    def _scroll(self, bar, v):
        if not self._sync:
            self._sync = True
            bar.setValue(v)
            self._sync = False

    def _set_inline(self, on):
        self.inline = on
        self.b_inline.setText("Nebeneinander" if on else "Inline")
        self.refresh()
        self.goto_hunk(self.current)

    def _set_ws(self, on):
        self.ignore_ws = on
        self.refresh()

    def goto_hunk(self, i):
        if not self.hunks:
            self.pos.setText(""); return
        self.current = max(0, min(len(self.hunks) - 1, i))
        self.pos.setText(f"Änderung {self.current + 1} von {len(self.hunks)}")
        span = self.hunk_blocks.get(self.current)
        if span:
            c = self.left.textCursor(); c.setPosition(self.left.document().findBlockByNumber(span[0]).position())
            self.left.setTextCursor(c); self.left.centerCursor()
        self.bar.update()

    def apply_hunk(self, index, op):
        h = self.hunks[index]
        if op == "right" and self.right_apply:
            self.right_t = engine.apply_to_right(self.left_t, self.right_t, h)
            self.right_apply(self.right_t.join())
        elif op == "left" and self.left_apply:
            self.left_t = engine.apply_to_left(self.left_t, self.right_t, h)
            self.left_apply(self.left_t.join())
        else:
            return
        keep = self.current
        self.refresh()
        self.goto_hunk(min(keep, len(self.hunks) - 1))
        self.applied.emit()

    def reload_right(self, text: str):
        """Von außen (z. B. Datei wurde geändert) die rechte Seite ersetzen."""
        self.right_t = engine.Text.parse(text)
        self.refresh()
