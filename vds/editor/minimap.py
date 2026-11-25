"""Minimap rechts neben dem Editor: jede Zeile ein Strich, dazu der sichtbare Bereich, Fehler, Haltepunkte und Lesezeichen. Klicken und Ziehen scrollt."""
from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import t as tc

WIDTH = 84
ROW = 2                 # Pixel pro Zeile
CHARS = 100             # so viele Zeichen füllen die Breite


class Minimap(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.ed = editor
        self.setFixedWidth(WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Minimap: klicken oder ziehen zum Scrollen")
        self._later = QTimer(self, singleShot=True, interval=150)     # beim Tippen nicht bei jedem Zeichen neu zeichnen
        self._later.timeout.connect(self.update)
        editor.document().contentsChanged.connect(self._later.start)
        editor.verticalScrollBar().valueChanged.connect(lambda _v: self.update())

    def _rows(self) -> int:
        bar = self.ed.verticalScrollBar()
        return max(1, bar.maximum() + bar.pageStep())

    def first_row(self) -> int:
        """Erste gezeichnete Zeile: Passt die Datei nicht ganz hinein, wandert der Ausschnitt anteilig mit dem Scrollen mit."""
        bar, room = self.ed.verticalScrollBar(), self.height() // ROW
        spare = self._rows() - room
        return round(spare * bar.value() / bar.maximum()) if spare > 0 and bar.maximum() > 0 else 0

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(tc("#080a16")))
        ed, first, room = self.ed, self.first_row(), self.height() // ROW + 1
        scale = (self.width() - 6) / CHARS
        tab = ed.tab_size()
        ink, soft = QColor(tc("#6f7fa6")), QColor(tc("#4d5b82"))
        rows: dict[int, int] = {}
        block, row = ed.document().firstBlock(), 0
        if not ed.folded:                                   # ohne Faltung ist Zeile = Blocknummer, der Weg durch die Datei entfällt
            block, row = ed.document().findBlockByNumber(first), first
        while block.isValid() and row < first + room:
            if block.isVisible():
                if row >= first:
                    y = (row - first) * ROW
                    rows[block.blockNumber() + 1] = y
                    text = block.text()
                    start = len(text) - len(text.lstrip())
                    width = len(text.expandtabs(tab).strip())
                    if width:
                        p.fillRect(QRectF(3 + (len(text[:start].expandtabs(tab))) * scale, y, max(width * scale, 1), ROW - 0.5), soft if text.lstrip().startswith(("#", "//")) else ink)
                row += 1
            block = block.next()
        bar = ed.verticalScrollBar()
        top = (bar.value() - first) * ROW
        p.fillRect(QRectF(0, top, self.width(), max(bar.pageStep() * ROW, 8)), QColor(0, 229, 255, 34))
        for sev, _m, line, _c in ed.diagnostics:
            if line in rows:
                p.fillRect(QRectF(self.width() - 4, rows[line] - 1, 4, 4), QColor(tc({"error": "#ff4d6d", "warning": "#ffc474"}.get(sev, "#5ee7ff"))))
        for line in ed.breakpoints:
            if line in rows:
                p.fillRect(QRectF(0, rows[line] - 1, 4, 4), QColor(tc("#ff2d6f")))
        for line in ed.bookmarks:
            if line in rows:
                p.fillRect(QRectF(0, rows[line] - 1, 4, 4), QColor(tc("#00e5ff")))
        p.end()

    def _scroll_to(self, y: float):
        bar = self.ed.verticalScrollBar()
        bar.setValue(round(self.first_row() + y / ROW - bar.pageStep() / 2))

    def mousePressEvent(self, e):
        self._scroll_to(e.position().y())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._scroll_to(e.position().y())

    def wheelEvent(self, e):
        self.ed.wheelEvent(e)
