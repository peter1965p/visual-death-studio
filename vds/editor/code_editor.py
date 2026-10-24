"""Code-Editor: Zeilennummern, Haltepunkt-Gutter, aktuelle Zeile, Diagnosen, Auto-Einrückung."""
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtCore import QPoint, QPointF, QTimer
from PySide6.QtGui import QTextCursor, QColor, QFont, QPainter, QPen, QPolygonF, QTextCharFormat, QTextFormat, QTextOption
from PySide6.QtWidgets import QInputDialog, QMenu, QPlainTextEdit, QTextEdit, QToolTip, QWidget

import html
import re
from pathlib import Path

from ..build.languages import lang_for
from ..lsp.ranking import KIND_NAME, rank
from .. import options
from ..theme import EDITOR_FONT
from ..ai.completion import build_prompt
from .completion import CompletionPopup, SignatureTip, SuggestionCard
from .highlighter import PygmentsHighlighter
from ..theme import t as tc

SEV_COLOR = {k: tc(v) for k, v in {"error": "#ff4d6d", "warning": "#ffc474", "info": "#5ee7ff"}.items()}


class _Gutter(QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_gutter(e)

    def mousePressEvent(self, e):
        if e.position().x() < 20:
            line = self.ed.cursorForPosition(e.position().toPoint()).block().blockNumber() + 1
            if e.button() == Qt.LeftButton:
                self.ed.toggle_breakpoint(line)
            elif e.button() == Qt.RightButton:
                self.ed.breakpoint_menu(line, e.globalPosition().toPoint())


DEFAULT_FONT: QFont | None = None      # vom Nutzer gewählte Editor-Schrift (gilt für alle neuen Editoren)


def set_default_font(f: QFont):
    global DEFAULT_FONT
    DEFAULT_FONT = QFont(f)


class CodeEditor(QPlainTextEdit):
    breakpointsChanged = Signal()
    cursorInfo = Signal(int, int)
    definitionFound = Signal(list)          # [(Pfad, Zeile, Spalte)] für „Gehe zu Definition“
    aiStatus = Signal(str)                  # Statusmeldungen der Claude-Vervollständigung

    def __init__(self, filename: str = "", parent=None):
        super().__init__(parent)
        f = QFont(DEFAULT_FONT) if DEFAULT_FONT else QFont()
        if not DEFAULT_FONT:
            f.setFamilies([s.strip() for s in EDITOR_FONT.split(",")])
            f.setPointSize(11)
            f.setStyleHint(QFont.Monospace)
        self.set_editor_font(f)
        self.breakpoints: set[int] = set()
        self.bp_conditions: dict[int, str] = {}
        self.bp_disabled: set[int] = set()
        self.exec_line: int | None = None     # aktuelle Debugger-Zeile (gelb)
        self.diagnostics: list = []   # [(severity, message, line, col)] – Build + Language Server zusammen
        self._diag_build: list = []
        self._diag_lsp: list = []
        # IntelliSense
        self.intel = None             # LspManager (vom Hauptfenster gesetzt)
        self.doc_path: Path | None = None
        self.datatip = None           # Funktion(ausdruck, cb) – Variablenwert beim Debuggen
        self._items: list = []
        self._req = 0
        self._trigger: str | None = None
        self._after_trigger = False
        self.popup = CompletionPopup(self); self.popup.hide(); self.popup.accepted.connect(self._accept_item)
        self.sigtip = SignatureTip(self); self.sigtip.hide()
        self._ctimer = QTimer(self, singleShot=True, interval=60); self._ctimer.timeout.connect(self._request)
        self._stimer = QTimer(self, singleShot=True, interval=40); self._stimer.timeout.connect(self._signature)
        self._htimer = QTimer(self, singleShot=True, interval=520); self._htimer.timeout.connect(self._hover)
        self._hover_pos: QPoint | None = None
        # Claude-Vervollständigung
        self.ai = None                # AiCompletion (vom Hauptfenster gesetzt)
        self.card = SuggestionCard(self); self.card.hide()
        self._ai_pos: int | None = None
        self._ai_text = ""
        self.cursorPositionChanged.connect(self._ai_cursor_moved)
        self.viewport().setMouseTracking(True)
        self.highlighter = PygmentsHighlighter(self.document(), filename)
        self.gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda: self.setViewportMargins(self.gutter_width(), 0, 0, 0))
        self.updateRequest.connect(self._scroll_gutter)
        self.cursorPositionChanged.connect(self._on_cursor)
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self.apply_options()
        self._on_cursor()

    def set_editor_font(self, f: QFont):
        """Schrift per eigenem Stylesheet setzen: Das globale Stylesheet (`* { font-family … }`) überschreibt sonst jedes setFont() und der Editor wäre proportional."""
        fams = [x for x in (f.families() or [f.family()]) if x]
        size = f.pointSize() if f.pointSize() > 0 else 11
        css = (f'QPlainTextEdit {{ font-family: {", ".join(chr(34) + x + chr(34) for x in fams)}, monospace; font-size: {size}pt; '
               f'font-weight: {f.weight()}; font-style: {"italic" if f.italic() else "normal"}; }}')
        self.setFont(f)
        self.setStyleSheet(css)
        self.ensurePolished()                                   # damit fontMetrics() sofort die wirksame Schrift misst

    def indent_unit(self) -> str:
        return " " * options.get("editor/tab_width") if options.get("editor/use_spaces") else "\t"

    def apply_options(self):
        """Tab-Breite, Zeilenumbruch, Leerraum-Anzeige und IntelliSense-Verzögerung aus Extras → Optionen übernehmen."""
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * options.get("editor/tab_width"))
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if options.get("editor/word_wrap") else QPlainTextEdit.NoWrap)
        opt = self.document().defaultTextOption()
        flags = opt.flags()
        opt.setFlags(flags | QTextOption.ShowTabsAndSpaces if options.get("editor/whitespace") else flags & ~QTextOption.ShowTabsAndSpaces)
        self.document().setDefaultTextOption(opt)
        self._ctimer.setInterval(options.get("intellisense/delay_ms"))

    def refresh_font(self, f: QFont):
        """Neue Schrift übernehmen: Tabbreite und Zeilennummern-Spalte neu berechnen."""
        self.set_editor_font(f)
        self.popup.list.setFont(f); self.sigtip.setFont(f)
        self.apply_options()
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))
        self.gutter.update()

    # --- Gutter ---------------------------------------------------------------
    def gutter_width(self):
        return 18 + 12 + self.fontMetrics().horizontalAdvance("9") * max(3, len(str(self.blockCount())))

    def _scroll_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, e):
        p = QPainter(self.gutter)
        p.fillRect(e.rect(), QColor(tc("#080a16")))
        cur = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= e.rect().bottom():
            h = round(self.blockBoundingRect(block).height())
            n = block.blockNumber() + 1
            if block.isVisible() and top + h >= e.rect().top():
                if n in self.breakpoints:
                    y = top + (h - 10) // 2
                    if n in self.bp_disabled:                       # deaktiviert: Ring
                        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(tc("#ff2d6f")), 1.5)); p.drawEllipse(5, y + 1, 8, 8)
                    else:
                        p.setBrush(QColor(tc("#ff2d6f"))); p.setPen(Qt.NoPen); p.drawEllipse(4, y, 10, 10)
                        if self.bp_conditions.get(n):               # bedingt: weißes Kreuz
                            p.setPen(QPen(QColor("white"), 1.4)); p.drawLine(6, y + 5, 12, y + 5); p.drawLine(9, y + 2, 9, y + 8)
                if n == self.exec_line:                             # Ausführungspfeil
                    p.setBrush(QColor(tc("#ffd60a"))); p.setPen(Qt.NoPen)
                    p.drawPolygon(QPolygonF([QPointF(2, top + 3), QPointF(16, top + h / 2), QPointF(2, top + h - 3)]))
                p.setPen(QColor("#9ad7ff" if block.blockNumber() == cur else "#4d5b82"))
                p.drawText(0, top, self.gutter.width() - 6, h, Qt.AlignRight | Qt.AlignVCenter, str(n))
            block = block.next()
            top += h
        p.end()

    def toggle_breakpoint(self, line: int):
        if line in self.breakpoints:
            self.breakpoints.discard(line); self.bp_conditions.pop(line, None); self.bp_disabled.discard(line)
        else:
            self.breakpoints.add(line)
        self._bp_changed()

    def _bp_changed(self):
        self.gutter.update()
        self.breakpointsChanged.emit()

    def breakpoint_list(self) -> list:
        """Aktive Haltepunkte als [(Zeile, Bedingung)] – deaktivierte werden nicht an den Debugger gegeben."""
        return sorted((n, self.bp_conditions.get(n, "")) for n in self.breakpoints if n not in self.bp_disabled)

    def set_breakpoint_state(self, line: int, condition: str = "", disabled: bool = False):
        self.breakpoints.add(line)
        (self.bp_conditions.__setitem__(line, condition) if condition else self.bp_conditions.pop(line, None))
        (self.bp_disabled.add(line) if disabled else self.bp_disabled.discard(line))
        self._bp_changed()

    def breakpoint_menu(self, line: int, pos):
        m = QMenu(self)
        if line in self.breakpoints:
            m.addAction("Bedingung…", lambda: self._ask_condition(line))
            off = line in self.bp_disabled
            m.addAction("Haltepunkt aktivieren" if off else "Haltepunkt deaktivieren", lambda: self.set_breakpoint_state(line, self.bp_conditions.get(line, ""), not off))
            m.addAction("Haltepunkt entfernen", lambda: self.toggle_breakpoint(line))
        else:
            m.addAction("Haltepunkt setzen", lambda: self.toggle_breakpoint(line))
            m.addAction("Bedingter Haltepunkt…", lambda: (self.toggle_breakpoint(line), self._ask_condition(line)))
        m.exec(pos)

    def _ask_condition(self, line: int):
        text, ok = QInputDialog.getText(self, "Bedingter Haltepunkt", f"Zeile {line}: nur anhalten, wenn dieser Ausdruck wahr ist\n(leer = immer):",
                                        text=self.bp_conditions.get(line, ""))
        if ok:
            self.set_breakpoint_state(line, text.strip(), line in self.bp_disabled)

    def set_exec_line(self, line: int | None):
        self.exec_line = line
        self.refresh_selections()
        self.gutter.update()

    # --- Hervorhebungen -----------------------------------------------------------
    def _on_cursor(self):
        c = self.textCursor()
        self.cursorInfo.emit(c.blockNumber() + 1, c.positionInBlock() + 1)
        self.refresh_selections()
        self.gutter.update()

    def set_diagnostics(self, items):
        """Build-Fehler (Compiler/Interpreter)."""
        self._diag_build = items
        self.diagnostics = self._diag_build + self._diag_lsp
        self.refresh_selections()

    def set_lsp_diagnostics(self, items):
        """Live-Diagnosen des Language Servers."""
        self._diag_lsp = items
        self.diagnostics = self._diag_build + self._diag_lsp
        self.refresh_selections()

    def refresh_selections(self):
        sels = []
        line = QTextEdit.ExtraSelection()
        line.format.setBackground(QColor(tc("#0f1530")))
        line.format.setProperty(QTextFormat.FullWidthSelection, True)
        line.cursor = self.textCursor()
        line.cursor.clearSelection()
        sels.append(line)
        if self.exec_line:
            blk = self.document().findBlockByNumber(self.exec_line - 1)
            if blk.isValid():
                ex = QTextEdit.ExtraSelection()
                ex.format.setBackground(QColor(255, 214, 10, 70))
                ex.format.setProperty(QTextFormat.FullWidthSelection, True)
                ex.cursor = self.textCursor(); ex.cursor.setPosition(blk.position()); ex.cursor.clearSelection()
                sels.append(ex)
        for sev, _msg, ln, col in self.diagnostics:
            block = self.document().findBlockByNumber(ln - 1)
            if not block.isValid():
                continue
            s = QTextEdit.ExtraSelection()
            s.format.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            s.format.setUnderlineColor(QColor(SEV_COLOR.get(sev, "#5ee7ff")))
            c = self.textCursor()
            start = block.position() + max(0, min(col - 1, block.length() - 1))
            c.setPosition(start)
            c.movePosition(QTextCursor.MoveOperation.EndOfWord, QTextCursor.MoveMode.KeepAnchor)
            if not c.hasSelection():
                c.setPosition(block.position()); c.setPosition(block.position() + max(1, block.length() - 1), QTextCursor.MoveMode.KeepAnchor)
            s.cursor = c
            sels.append(s)
        self.setExtraSelections(sels)

    def goto(self, line: int, col: int = 1):
        block = self.document().findBlockByNumber(max(0, line - 1))
        c = self.textCursor()
        c.setPosition(block.position() + max(0, min(col - 1, block.length() - 1)))
        self.setTextCursor(c)
        self.centerCursor()
        self.setFocus()

    # --- Eingabe ----------------------------------------------------------------
    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        enter = k in (Qt.Key_Return, Qt.Key_Enter)
        if self.card.isVisible():
            if k == Qt.Key_Tab and not mods and self._ai_text:
                return self._ai_accept()
            if k == Qt.Key_Escape:
                return self._ai_dismiss(cancel=True)
            if enter and mods & Qt.ControlModifier:
                return self.request_ai(variant=True)
            self._ai_dismiss(cancel=True)          # jede andere Taste verwirft den Vorschlag und wird normal behandelt
        elif enter and mods & Qt.ControlModifier:
            return self._ask_ai_instruction() if mods & Qt.ShiftModifier else self.request_ai()
        if self.popup.isVisible():
            if k in (Qt.Key_Down, Qt.Key_Up) and not mods:
                return self.popup.step(1 if k == Qt.Key_Down else -1)
            if k in (Qt.Key_PageDown, Qt.Key_PageUp):
                return self.popup.step(8 if k == Qt.Key_PageDown else -8)
            # Tab nimmt den markierten Vorschlag. Enter nur, wenn man ihn selbst mit den Pfeiltasten gewählt hat –
            # sonst bleibt Enter ein Zeilenumbruch (kein versehentliches Einfügen).
            if k == Qt.Key_Tab and not mods or (k in (Qt.Key_Return, Qt.Key_Enter) and not mods and self.popup.explicit):
                cur = self.popup.current()
                if cur:
                    return self._accept_item(cur)
            if k == Qt.Key_Escape:
                return self._close_popups()
            if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End, Qt.Key_Return, Qt.Key_Enter):
                self.popup.hide()
        elif k == Qt.Key_Escape and self.sigtip.isVisible():
            return self.sigtip.hide()
        if k == Qt.Key_Space and mods & Qt.ControlModifier:
            self._after_trigger = False
            return self._request(forced=True)
        self._basic_key(e)
        self._after_key(e)

    def _basic_key(self, e):
        if e.key() == Qt.Key_Tab and not e.modifiers():
            self.insertPlainText(self.indent_unit())
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers():
            text = self.textCursor().block().text()
            indent = text[: len(text) - len(text.lstrip())]
            if text.rstrip().endswith((":", "{", "(", "[")):
                indent += self.indent_unit()
            super().keyPressEvent(e)
            self.insertPlainText(indent)
        else:
            super().keyPressEvent(e)

    # --- IntelliSense: Auslöser --------------------------------------------------------------------------------------
    def _prefix(self):
        """(getipptes Wortstück vor dem Cursor, Startspalte)"""
        c = self.textCursor()
        text, col = c.block().text(), c.positionInBlock()
        a = col
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] == "_"):
            a -= 1
        return text[a:col], a

    def _in_string_or_comment(self) -> bool:
        c = self.textCursor()
        before = c.block().text()[: c.positionInBlock()]
        lang = lang_for(self.doc_path) if self.doc_path else None
        quotes = 0
        for i, ch in enumerate(before):
            if ch in "'\"" and (i == 0 or before[i - 1] != "\\"):
                quotes += 1
            elif lang and before.startswith(lang.comment, i) and quotes % 2 == 0:
                return True                                       # Kommentar
        return quotes % 2 == 1                                    # offener String

    def _after_key(self, e):
        if not self.intel or not self.doc_path:
            return
        t = e.text()
        if e.key() == Qt.Key_Backspace:
            return self._refilter() if self.popup.isVisible() else None
        if not t or not t.isprintable():
            return
        ch = t[-1]
        c = self.textCursor()
        prev = c.block().text()[max(0, c.positionInBlock() - 2): c.positionInBlock() - 1]
        if ch in "(,":
            self._stimer.start()
        elif ch == ")":
            self._maybe_hide_sig()
        word_char = ch.isalnum() or ch == "_"
        if self.popup.isVisible():
            if word_char:
                return self._refilter()
            self.popup.hide()
        if not options.get("intellisense/auto"):
            return                                            # nur manuell (Strg+Leertaste)
        prefix, _ = self._prefix()
        if word_char and len(prefix) >= options.get("intellisense/min_chars") and not prefix[0].isdigit() and not self._in_string_or_comment():
            self._after_trigger = False
            self._ctimer.start()
        elif ch == "." or (ch == ":" and prev == ":") or (ch == ">" and prev == "-"):
            if not self._in_string_or_comment():
                self._trigger = ch; self._after_trigger = True
                self._ctimer.start()

    def _request(self, forced=False):
        if not self.intel or not self.doc_path:
            return
        c = self.textCursor()
        self._req += 1
        rid, trig = self._req, self._trigger
        self._trigger = None
        self.intel.complete(self.doc_path, c.blockNumber(), c.positionInBlock(), trig, lambda items: self._got_items(rid, items, forced))

    def _got_items(self, rid, items, forced):
        if rid != self._req:
            return                                    # veraltete Antwort
        self._items = items
        self._show(forced)

    def _ranked(self, prefix):
        lang = lang_for(self.doc_path)
        return rank(self._items, prefix, self.intel.local_words(self.doc_path), self.intel.mru_for(lang.id) if lang else {})

    def _refilter(self):
        prefix, _ = self._prefix()
        if not prefix and not self._after_trigger:
            return self.popup.hide()
        self._show(False)

    def _show(self, forced):
        prefix, start = self._prefix()
        if not prefix and not forced and not self._after_trigger:
            return self.popup.hide()
        ranked = self._ranked(prefix)
        if not ranked or (len(ranked) == 1 and ranked[0]["name"] == prefix and ranked[0]["label"] == prefix):
            return self.popup.hide()
        self.popup.set_items(ranked)
        c = self.textCursor(); c.setPosition(c.block().position() + start)
        r = self.cursorRect(c)
        pos = self.viewport().mapToGlobal(r.bottomLeft()) + QPoint(-6, 4)
        scr = self.screen().availableGeometry()
        if pos.y() + self.popup.height() > scr.bottom():
            pos = self.viewport().mapToGlobal(r.topLeft()) - QPoint(6, self.popup.height() + 4)
        pos.setX(min(pos.x(), scr.right() - self.popup.width() - 8))
        self.popup.move(pos)
        self.popup.show()

    def _close_popups(self):
        self.popup.hide(); self.sigtip.hide()
        self._ai_dismiss(cancel=True)

    def _accept_item(self, it: dict):
        c = self.textCursor()
        block = c.block()
        text = block.text()
        prefix, a = self._prefix()
        e = c.positionInBlock()
        while e < len(text) and (text[e].isalnum() or text[e] == "_"):
            e += 1                                    # Rest des Wortes mit ersetzen
        start, end = block.position() + a, block.position() + e
        new = it.get("insertText") or it["name"]
        te = it.get("textEdit")
        if te and te.get("range") and te["range"]["start"]["line"] == te["range"]["end"]["line"] == block.blockNumber():
            start = block.position() + te["range"]["start"]["character"]; end = block.position() + te["range"]["end"]["character"]
            new = te.get("newText", new)
        if it.get("snippet"):
            new = re.sub(r"\$\{\d+:([^}]*)\}", r"\1", new); new = re.sub(r"\$\d+|\$\{\d+\}", "", new)
        kind = KIND_NAME.get(it.get("kind") or 1, "text")
        nxt = text[e:e + 1]
        line_start = text.lstrip()
        parens = kind in ("function", "method", "constructor") and "(" not in new and nxt != "(" and not line_start.startswith(("import ", "from "))
        c.beginEditBlock()
        c.setPosition(start); c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        c.insertText(new + ("()" if parens else ""))
        if parens:
            c.movePosition(QTextCursor.MoveOperation.Left)
        c.endEditBlock()
        self.setTextCursor(c)
        lang = lang_for(self.doc_path) if self.doc_path else None
        if lang:
            self.intel.record_choice(lang.id, it["name"])
        self.popup.hide()
        if parens:
            self._stimer.start()

    # --- Claude-Vervollständigung ----------------------------------------------------------------------------------
    def _ask_ai_instruction(self):
        text, ok = QInputDialog.getText(self, "Claude an der Cursorposition", "Was soll Claude hier schreiben?")
        if ok and text.strip():
            self.request_ai(instruction=text.strip())

    def _card_pos(self) -> QPoint:
        """Position unter der Cursorzeile, am Zeilenanfang ausgerichtet."""
        c = self.textCursor()
        line_start = QTextCursor(c); line_start.setPosition(c.block().position())
        left = self.cursorRect(line_start).left()
        r = self.cursorRect()
        return self.viewport().mapToGlobal(QPoint(left, r.bottom() + 4))

    def _place_card(self):
        scr = self.screen().availableGeometry()
        pos = self._card_pos()
        if pos.y() + self.card.height() > scr.bottom():
            r = self.cursorRect()
            pos = QPoint(pos.x(), self.viewport().mapToGlobal(QPoint(0, r.top())).y() - self.card.height() - 4)
        self.card.move(pos)

    def request_ai(self, instruction: str = "", variant: bool = False):
        """Strg+Enter: Claude schreibt Code an der Cursorposition. Der Vorschlag erscheint in einer Karte (Tab = übernehmen)."""
        if not self.ai or not self.doc_path:
            return
        self.popup.hide(); self.sigtip.hide()
        prev = self._ai_text if variant else ""
        if not variant:
            self._ai_pos = self.textCursor().position()
        c = self.textCursor()
        text, pos = self.toPlainText(), self._ai_pos
        lang = lang_for(self.doc_path)
        prompt = build_prompt(self.doc_path.name, lang.name if lang else "Text", text[:pos], text[pos:], instruction, avoid=prev)
        self._ai_text = ""
        self.card.show_loading(self._card_pos(), self.doc_path.name)
        self.aiStatus.emit("Claude denkt nach … (Esc bricht ab)")

        def got(ok, result):
            if self.toPlainText() != text or self.textCursor().position() != pos:
                return self.card.hide()               # der Text hat sich inzwischen geändert
            if not ok:
                self.card.hide()
                return self.aiStatus.emit(f"Claude: {result}")
            # Steht der Cursor auf einer leeren Zeile, wäre ein führender Zeilenumbruch nur eine überflüssige Leerzeile
            before_line = text[:pos].rsplit("\n", 1)[-1]
            self._ai_text = result.lstrip("\n") if not before_line.strip() else result
            self.card.show_suggestion(self._ai_text, self._card_pos(), self.viewport().width() - 40, self.doc_path.name, variant)
            self._place_card()
            self.aiStatus.emit("Vorschlag bereit – Tab übernimmt, Esc verwirft")
        self.ai.run(prompt, got, self)

    def _ai_accept(self):
        if not self._ai_text or self._ai_pos is None:
            return
        c = self.textCursor()
        c.setPosition(self._ai_pos)
        text = self._ai_text
        self._ai_text = ""
        self.card.hide()
        c.insertText(text)
        self.setTextCursor(c)
        self.aiStatus.emit("Vorschlag übernommen.")

    def _ai_dismiss(self, cancel: bool = False):
        was = self.card.isVisible()
        self.card.hide()
        self._ai_text = ""
        if cancel and self.ai and was:
            self.ai.cancel()

    def _ai_cursor_moved(self):
        if self.card.isVisible() and self._ai_pos is not None and self.textCursor().position() != self._ai_pos:
            self._ai_dismiss(cancel=True)

    # --- Signaturhilfe / Hover / Definition ------------------------------------------------------------------------------
    def _paren_depth(self) -> int:
        c = self.textCursor()
        before = c.block().text()[: c.positionInBlock()]
        return before.count("(") - before.count(")")

    def _maybe_hide_sig(self):
        if self._paren_depth() <= 0:
            self.sigtip.hide()

    def _signature(self):
        if not self.intel or not self.doc_path or self._paren_depth() <= 0:
            return
        c = self.textCursor()
        rid = (c.blockNumber(), c.positionInBlock())

        def got(sig):
            cur = self.textCursor()
            if not sig or self._paren_depth() <= 0 or (cur.blockNumber(), cur.positionInBlock()) != rid:
                return
            r = self.cursorRect()
            self.sigtip.show_sig(sig, self.viewport().mapToGlobal(r.topLeft()))
            self.sigtip.move(self.viewport().mapToGlobal(r.topLeft()) - QPoint(0, self.sigtip.height() + 6))
        self.intel.signature(self.doc_path, c.blockNumber(), c.positionInBlock(), got)

    def mouseMoveEvent(self, e):
        self._hover_pos = e.position().toPoint()
        self._htimer.start()
        QToolTip.hideText()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._htimer.stop()
        super().leaveEvent(e)

    def focusOutEvent(self, e):
        self._close_popups()
        super().focusOutEvent(e)

    def _expr_at(self, text: str, col: int) -> str:
        """Ausdruck unter dem Cursor, z. B. self.name oder liste[0].wert (für Variablenwerte beim Debuggen)."""
        a = col
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] in "_."):
            a -= 1
        b = col
        while b < len(text) and (text[b].isalnum() or text[b] == "_"):
            b += 1
        return text[a:b].strip(".")

    def _hover(self):
        if not self._hover_pos or not self.underMouse():
            return
        pos = self._hover_pos
        c = self.cursorForPosition(pos)
        r = self.cursorRect(c)
        if abs(pos.x() - r.x()) > 40 or abs(pos.y() - r.center().y()) > 16:
            return
        line, col, text = c.blockNumber(), c.positionInBlock(), c.block().text()
        gpos = self.viewport().mapToGlobal(pos)
        parts: list = []
        for sev, msg, ln, dcol in self.diagnostics:                # Fehlertext zuerst
            if ln - 1 == line:
                color = tc({"error": "#ff4d6d", "warning": "#ffc474"}.get(sev, "#5ee7ff"))
                parts.append(f"<span style='color:{color}'>● {html.escape(msg)}</span>")
        expr = self._expr_at(text, col)

        def show(extra):
            body = "<br>".join(parts + ([extra] if extra else []))
            if body and self._hover_pos == pos:
                QToolTip.showText(gpos, f"<div style='max-width:560px'>{body}</div>", self)

        if self.datatip and expr and not expr[0].isdigit():
            def got(val):
                if val:
                    show(val)
                elif self.intel and self.doc_path:
                    self.intel.hover(self.doc_path, line, col, show)
                else:
                    show(None)
            return self.datatip(expr, got)
        if self.intel and self.doc_path and expr:
            return self.intel.hover(self.doc_path, line, col, show)
        show(None)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.modifiers() & Qt.ControlModifier and self.intel and self.doc_path:
            c = self.cursorForPosition(e.position().toPoint())
            self.intel.definition(self.doc_path, c.blockNumber(), c.positionInBlock(), self.definitionFound.emit)
            return
        super().mousePressEvent(e)

    def jump_to_definition(self):
        if self.intel and self.doc_path:
            c = self.textCursor()
            self.intel.definition(self.doc_path, c.blockNumber(), c.positionInBlock(), self.definitionFound.emit)
