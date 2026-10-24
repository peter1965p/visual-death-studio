"""Ausgabefenster (mit Eingabezeile für stdin) und Fehlerliste."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor, QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..icons import icon
from ..theme import EDITOR_FONT
from ..theme import t

COLORS = {k: t(v) for k, v in {"stdout": "#dbe6ff", "stderr": "#ff7a93", "info": "#7f93bd", "ok": "#3dffa1"}.items()}


class OutputPane(QWidget):
    inputSubmitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = QPlainTextEdit(readOnly=True)
        f = QFont(); f.setFamilies([s.strip() for s in EDITOR_FONT.split(",")]); f.setPointSize(10)
        self.text.setFont(f)
        self.entry = QLineEdit(placeholderText="Eingabe für das laufende Programm (Enter sendet)")
        self.entry.returnPressed.connect(self._send)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(self.text); lay.addWidget(self.entry)

    def append(self, text: str, kind: str = "stdout"):
        fmt = QTextCharFormat(); fmt.setForeground(QColor(COLORS.get(kind, COLORS["stdout"])))
        c = self.text.textCursor(); c.movePosition(QTextCursor.MoveOperation.End); c.insertText(text, fmt)
        self.text.setTextCursor(c); self.text.ensureCursorVisible()

    def clear(self):
        self.text.clear()

    def _send(self):
        t = self.entry.text() + "\n"
        self.entry.clear()
        self.append(t, "info")
        self.inputSubmitted.emit(t)


class ErrorList(QTableWidget):
    activated = Signal(str, int, int)
    countChanged = Signal(int, int)  # Fehler, Warnungen

    ICON = {"error": ("error", t("#ff4d6d")), "warning": ("warning", t("#ffc474")), "info": ("info", t("#5ee7ff"))}

    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["", "Beschreibung", "Datei", "Zeile", "Spalte"])
        self.verticalHeader().hide()
        self.setColumnWidth(0, 28); self.setColumnWidth(1, 520); self.setColumnWidth(2, 220); self.setColumnWidth(3, 60)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setShowGrid(False)
        self.cellDoubleClicked.connect(lambda r, _c: self.activated.emit(self.item(r, 2).data(Qt.UserRole), int(self.item(r, 3).text()), int(self.item(r, 4).text())))
        self.sources: dict[str, list] = {}

    def set_source(self, source: str, items):  # items: [(sev, msg, abs_file, line, col)]
        if items:
            self.sources[source] = items
        else:
            self.sources.pop(source, None)
        rows = [i for v in self.sources.values() for i in v]
        self.setRowCount(len(rows))
        for r, (sev, msg, file, line, col) in enumerate(rows):
            name, color = self.ICON.get(sev, self.ICON["info"])
            ic = QTableWidgetItem(); ic.setIcon(icon(name, color))
            self.setItem(r, 0, ic); self.setItem(r, 1, QTableWidgetItem(msg))
            f = QTableWidgetItem(Path(file).name); f.setData(Qt.UserRole, file); f.setToolTip(file)
            self.setItem(r, 2, f); self.setItem(r, 3, QTableWidgetItem(str(line))); self.setItem(r, 4, QTableWidgetItem(str(col)))
        self.countChanged.emit(sum(i[0] == "error" for i in rows), sum(i[0] == "warning" for i in rows))
