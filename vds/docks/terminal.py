"""Integriertes Terminal: PTY-Shell, gerendert über pyte in einem eigenen QWidget."""
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios

import pyte
from PySide6.QtCore import QEvent, QSocketNotifier, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import EDITOR_FONT

NAMED = {"black": "#0a0d1f", "red": "#ff4d6d", "green": "#3dffa1", "brown": "#ffc474", "blue": "#4dd2ff",
         "magenta": "#c792ff", "cyan": "#5ee7ff", "white": "#dbe6ff", "default": None,
         "brightblack": "#4d5b82", "brightred": "#ff7a93", "brightgreen": "#7dffc0", "brightbrown": "#ffe09a",
         "brightblue": "#7cdcff", "brightmagenta": "#dcb0ff", "brightcyan": "#9af0ff", "brightwhite": "#ffffff"}
KEYS = {Qt.Key_Return: b"\r", Qt.Key_Enter: b"\r", Qt.Key_Backspace: b"\x7f", Qt.Key_Tab: b"\t", Qt.Key_Escape: b"\x1b",
        Qt.Key_Up: b"\x1b[A", Qt.Key_Down: b"\x1b[B", Qt.Key_Right: b"\x1b[C", Qt.Key_Left: b"\x1b[D",
        Qt.Key_Home: b"\x1b[H", Qt.Key_End: b"\x1b[F", Qt.Key_Delete: b"\x1b[3~", Qt.Key_PageUp: b"\x1b[5~", Qt.Key_PageDown: b"\x1b[6~"}


def _color(name, default):
    if name in NAMED:
        return QColor(NAMED[name]) if NAMED[name] else default
    return QColor("#" + name) if len(name) == 6 else default


class TerminalWidget(QWidget):
    def __init__(self, cwd, parent=None):
        super().__init__(parent)
        self.cwd = str(cwd)
        self.setFocusPolicy(Qt.StrongFocus)
        f = QFont(); f.setFamilies([s.strip() for s in EDITOR_FONT.split(",")]); f.setPointSize(10); f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        fm = QFontMetrics(f)
        self.cw, self.ch = fm.horizontalAdvance("M"), fm.height()
        self.screen = pyte.Screen(80, 24)
        self.stream = pyte.ByteStream(self.screen)
        self.proc = None
        self.master = -1
        self._fg, self._bg = QColor("#dbe6ff"), QColor("#080a16")
        self.cursor_on = True
        t = QTimer(self, interval=530); t.timeout.connect(self._blink); t.start()

    def start(self):
        if self.proc:
            return
        master, slave = pty.openpty()
        self.proc = subprocess.Popen([os.environ.get("SHELL", "/bin/bash"), "-l"], stdin=slave, stdout=slave, stderr=slave,
                                     cwd=self.cwd, env={**os.environ, "TERM": "xterm-256color"}, start_new_session=True,
                                     preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        os.close(slave)
        self.master = master
        self.notifier = QSocketNotifier(master, QSocketNotifier.Read, self)
        self.notifier.activated.connect(self._readable)
        self._resize_pty()

    def _readable(self):
        try:
            data = os.read(self.master, 65536)
        except OSError:
            data = b""
        if not data:
            self.notifier.setEnabled(False)
            self.stream.feed(b"\r\n[Prozess beendet - Enter startet neu]\r\n")
            self.proc = None
        else:
            self.stream.feed(data)
        self.update()

    def _resize_pty(self):
        cols, rows = max(20, self.width() // self.cw), max(5, self.height() // self.ch)
        if (cols, rows) != (self.screen.columns, self.screen.lines):
            self.screen.resize(rows, cols)
        if self.master >= 0 and self.proc:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def resizeEvent(self, e):
        self._resize_pty()

    def showEvent(self, e):
        self.start()
        self.setFocus()

    def _blink(self):
        self.cursor_on = not self.cursor_on
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self._bg)
        p.setFont(self.font())
        asc = QFontMetrics(self.font()).ascent()
        for y in range(self.screen.lines):
            line = self.screen.buffer[y]
            for x in range(self.screen.columns):
                c = line[x]
                fg, bg = _color(c.fg, self._fg), _color(c.bg, self._bg)
                if c.reverse:
                    fg, bg = bg, fg
                if bg != self._bg:
                    p.fillRect(x * self.cw, y * self.ch, self.cw, self.ch, bg)
                if c.data.strip():
                    f = p.font(); f.setBold(c.bold); p.setFont(f)
                    p.setPen(fg); p.drawText(x * self.cw, y * self.ch + asc, c.data)
        cur = self.screen.cursor
        if self.hasFocus() and self.cursor_on and not cur.hidden:
            p.fillRect(cur.x * self.cw, cur.y * self.ch, self.cw, self.ch, QColor(212, 212, 212, 150))
        p.end()

    def event(self, e):
        # App-Shortcuts (Strg+C/V/…) gehören dem Terminal, solange es den Fokus hat
        if e.type() == QEvent.ShortcutOverride:
            e.accept()
            return True
        return super().event(e)

    def focusNextPrevChild(self, nxt):
        return False

    def keyPressEvent(self, e):
        if not self.proc:
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.screen.reset(); self.start()
            return
        mods, key = e.modifiers(), e.key()
        if key in KEYS:
            data = KEYS[key]
        elif mods & Qt.ControlModifier and Qt.Key_A <= key <= Qt.Key_Z:
            data = bytes([key - Qt.Key_A + 1])
        else:
            data = e.text().encode()
        if data:
            os.write(self.master, data)

    def shutdown(self):
        if self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            self.proc = None
