"""Vorschlagsliste (IntelliSense) und Signatur-Tooltip im Neon-Look."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QStyledItemDelegate, QVBoxLayout

from ..lsp.ranking import KIND_NAME

CHIP = {"function": ("ƒ", "#c792ff"), "method": ("ƒ", "#c792ff"), "constructor": ("ƒ", "#c792ff"), "variable": ("v", "#5ee7ff"),
        "field": ("f", "#5ee7ff"), "property": ("p", "#5ee7ff"), "class": ("C", "#ffc474"), "struct": ("S", "#ffc474"), "interface": ("I", "#ffc474"),
        "module": ("M", "#ff7ac6"), "keyword": ("k", "#8fa3c7"), "constant": ("c", "#3dffa1"), "enum": ("E", "#3dffa1"), "enummember": ("e", "#3dffa1"),
        "snippet": ("s", "#8fa3c7"), "text": ("w", "#6f7fa6")}
ROW_H = 26
MAX_ROWS = 10


class _Delegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p: QPainter, option, index):
        it = index.data(Qt.UserRole)
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = bool(index.model().data(index, Qt.UserRole + 1))
        if selected:
            p.setPen(QPen(QColor(0, 229, 255, 180), 1)); p.setBrush(QColor(0, 160, 220, 70))
            p.drawRoundedRect(QRectF(r).adjusted(3, 1, -3, -1), 6, 6)
        kind = KIND_NAME.get(it.get("kind") or 1, "text")
        letter, color = CHIP.get(kind, CHIP["text"])
        p.setPen(Qt.NoPen); c = QColor(color); c.setAlpha(55); p.setBrush(c)
        chip = QRectF(r.x() + 9, r.y() + 4, 18, 18); p.drawRoundedRect(chip, 5, 5)
        p.setPen(QColor(color)); f = QFont(option.font); f.setBold(True); f.setPointSize(max(8, f.pointSize() - 2)); p.setFont(f)
        p.drawText(chip, Qt.AlignCenter, letter)
        # Name mit hervorgehobenen Treffern
        f2 = QFont(option.font); fb = QFont(f2); fb.setBold(True)
        label, pos = it["label"], set(it.get("_pos") or [])
        x = r.x() + 36
        fm, fmb = QFontMetrics(f2), QFontMetrics(fb)
        for i, ch in enumerate(label):
            hit = i in pos
            p.setFont(fb if hit else f2); p.setPen(QColor("#00e5ff") if hit else QColor("#dbe6ff" if not it.get("deprecated") else "#6f7fa6"))
            p.drawText(int(x), r.y() + 18, ch)
            x += (fmb if hit else fm).horizontalAdvance(ch)
        detail = it.get("detail") or ""
        if detail:
            p.setFont(f2); p.setPen(QColor("#6f7fa6"))
            w = r.right() - x - 20
            if w > 40:
                p.drawText(QRectF(x + 14, r.y(), r.right() - x - 22, r.height()), Qt.AlignVCenter | Qt.AlignRight, fm.elidedText(detail, Qt.ElideRight, int(w - 10)))
        p.restore()


class CompletionPopup(QFrame):
    accepted = Signal(dict)

    def __init__(self, editor):
        super().__init__(editor, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("QFrame#cp { background: #0c0f22; border: 1px solid rgba(0,229,255,0.55); border-radius: 10px; }"
                           "QListWidget { background: transparent; border: none; outline: 0; }"
                           "QLabel#doc { color: #9fb3d9; padding: 6px 12px; border-top: 1px solid rgba(0,229,255,0.18); }")
        self.setObjectName("cp")
        self.list = QListWidget(); self.list.setItemDelegate(_Delegate(self.list)); self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerItem)
        self.list.setFont(editor.font())
        self.doc = QLabel(); self.doc.setObjectName("doc"); self.doc.setWordWrap(True); self.doc.setTextFormat(Qt.PlainText)
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 5, 4, 0); lay.setSpacing(0)
        lay.addWidget(self.list); lay.addWidget(self.doc)
        self.list.itemClicked.connect(lambda it: self.accepted.emit(it.data(Qt.UserRole)))
        self.explicit = False          # Nutzer hat selbst mit Pfeiltasten gewählt (nur dann nimmt Enter den Vorschlag)

    def set_items(self, items: list):
        self.list.clear()
        for it in items[:80]:
            li = QListWidgetItem(); li.setData(Qt.UserRole, it); li.setData(Qt.UserRole + 1, False); self.list.addItem(li)
        self.explicit = False
        rows = min(MAX_ROWS, len(items))
        self.list.setFixedHeight(rows * ROW_H + 2)
        self.setFixedWidth(560)
        self.select(0)

    def fit(self):
        """Höhe exakt auf den Inhalt setzen (adjustSize() erzwingt bei Fenstern eine Mindesthöhe)."""
        self.layout().activate()
        self.setFixedHeight(self.sizeHint().height())

    def current(self) -> dict | None:
        i = self.list.currentRow()
        return self.list.item(i).data(Qt.UserRole) if 0 <= i < self.list.count() else None

    def select(self, i: int):
        n = self.list.count()
        if not n:
            return
        i = max(0, min(n - 1, i))
        for r in range(n):
            self.list.item(r).setData(Qt.UserRole + 1, r == i)
        self.list.setCurrentRow(i)
        cur = self.current()
        doc = (cur.get("documentation") or "").strip() if cur else ""
        self.doc.setText(doc.split("\n\n")[0][:260]); self.doc.setVisible(bool(doc))
        self.fit()
        self.list.viewport().update()

    def step(self, delta: int):
        """Auswahl verschieben (nicht 'move' nennen: das überschreibt QWidget.move)."""
        self.explicit = True
        self.select(self.list.currentRow() + delta)


class SignatureTip(QLabel):
    """Kleines Fenster über dem Cursor: Funktionssignatur mit hervorgehobenem aktuellen Parameter."""

    def __init__(self, editor):
        super().__init__(editor, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.RichText)
        self.setStyleSheet("QLabel { background: #0c0f22; color: #dbe6ff; border: 1px solid rgba(180,76,255,0.7); border-radius: 8px; padding: 6px 10px; }")
        self.setFont(editor.font())

    def show_sig(self, sig: dict, pos):
        import html
        label, span = sig["label"], sig.get("active")
        if span and 0 <= span[0] < span[1] <= len(label):
            body = html.escape(label[:span[0]]) + f"<b><span style='color:#00e5ff'>{html.escape(label[span[0]:span[1]])}</span></b>" + html.escape(label[span[1]:])
        else:
            body = html.escape(label)
        doc = f"<br><span style='color:#8fa3c7'>{html.escape(sig['doc'])}</span>" if sig.get("doc") else ""
        self.setText(body + doc)
        self.adjustSize()
        self.move(pos)
        self.show()


class SuggestionCard(QFrame):
    """Vorschlag von Claude unter dem Cursor (mit Syntax-Highlighting). Tab übernimmt, Esc verwirft."""

    def __init__(self, editor):
        super().__init__(editor, Qt.ToolTip | Qt.FramelessWindowHint)
        from PySide6.QtWidgets import QPlainTextEdit
        from .highlighter import PygmentsHighlighter
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setObjectName("sc")
        self.setStyleSheet("QFrame#sc { background: #0c0f22; border: 1px solid rgba(180,76,255,0.85); border-radius: 10px; }"
                           "QLabel#hd { color: #c792ff; padding: 6px 12px 4px 12px; letter-spacing: 1px; }"
                           "QLabel#ft { color: #6f7fa6; padding: 2px 12px 6px 12px; }"
                           "QPlainTextEdit { background: transparent; border: none; color: #dbe6ff; }")
        self.head, self.foot = QLabel(), QLabel()
        self.head.setObjectName("hd"); self.foot.setObjectName("ft")
        self.body = QPlainTextEdit(); self.body.setReadOnly(True); self.body.setFont(editor.font()); self.body.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.body.setFocusPolicy(Qt.NoFocus)
        self.hl = PygmentsHighlighter(self.body.document(), "")
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 2, 4, 0); lay.setSpacing(0)
        lay.addWidget(self.head); lay.addWidget(self.body); lay.addWidget(self.foot)
        self._dots = 0
        from PySide6.QtCore import QTimer
        self.timer = QTimer(self, interval=350); self.timer.timeout.connect(self._tick)
        self.editor = editor

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.head.setText("✦ CLAUDE DENKT NACH" + " ·" * self._dots)

    def show_loading(self, pos, filename: str):
        self.hl.set_filename(filename)
        self.body.hide(); self.foot.setText("Esc – abbrechen")
        self._tick(); self.timer.start()
        self.layout().activate(); self.setFixedSize(300, self.sizeHint().height())
        self.move(pos); self.show()

    def show_suggestion(self, text: str, pos, width: int, filename: str, variant: bool = False):
        self.timer.stop()
        self.hl.set_filename(filename)
        self.head.setText("✦ CLAUDE-VORSCHLAG" + ("  ·  neue Variante" if variant else ""))
        self.foot.setText("Tab – übernehmen   ·   Esc – verwerfen   ·   Strg+Enter – andere Variante")
        self.body.setPlainText(text)
        self.hl.relex()
        lines = text.count("\n") + 1
        lh = self.body.fontMetrics().lineSpacing()
        self.body.setFixedHeight(min(lines, 16) * lh + 14); self.body.show()
        self.body.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.layout().activate()
        self.setFixedSize(max(420, min(width, 820)), self.sizeHint().height())
        self.move(pos); self.show()

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)
