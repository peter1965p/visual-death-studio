"""Einfache vektorgezeichnete Icons (keine externen Dateien nötig)."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF

_cache: dict = {}


def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    from .theme import C, adapt
    color = adapt(color) if color else C["icon"]
    key = (name, color, size)
    if key not in _cache:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(color)
        p.setPen(QPen(col, 1.4))
        p.setBrush(Qt.NoBrush)
        s = size
        r = QRectF(2, 2, s - 4, s - 4)
        if name == "play":
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(4, 2), QPointF(s - 2, s / 2), QPointF(4, s - 2)]))
        elif name == "play-outline":
            p.drawPolygon(QPolygonF([QPointF(4, 2), QPointF(s - 2, s / 2), QPointF(4, s - 2)]))
        elif name == "stop":
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawRect(r)
        elif name in ("folder", "folder-open"):
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawRect(QRectF(1, 4, s - 2, s - 6)); p.drawRect(QRectF(1, 2.5, s / 2.2, 2.5))
        elif name == "file":
            p.drawPolygon(QPolygonF([QPointF(3, 1.5), QPointF(s - 6, 1.5), QPointF(s - 3, 5), QPointF(s - 3, s - 1.5), QPointF(3, s - 1.5)]))
        elif name == "solution":
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(s - 2, 1), QPointF(s - 2, s - 1), QPointF(s - 5, s - 3), QPointF(s - 5, 4)]))
            p.drawPolygon(QPolygonF([QPointF(2, 6), QPointF(5, 4), QPointF(5, s - 4), QPointF(2, s - 6)]))
        elif name == "save":
            p.drawRect(r); p.drawRect(QRectF(5, 2, s - 10, 4)); p.drawRect(QRectF(5, 9, s - 10, 5))
        elif name == "error":
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawEllipse(r)
            p.setPen(QPen(QColor("white"), 1.6)); p.drawLine(QPointF(5.5, 5.5), QPointF(s - 5.5, s - 5.5)); p.drawLine(QPointF(s - 5.5, 5.5), QPointF(5.5, s - 5.5))
        elif name == "warning":
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(s / 2, 1.5), QPointF(s - 1, s - 2), QPointF(1, s - 2)]))
        elif name == "bug":
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(4, 3, s - 8, s - 5))
        elif name == "build":
            p.drawLine(QPointF(3, s - 3), QPointF(s - 5, 5)); p.setPen(QPen(col, 3)); p.drawLine(QPointF(s - 6, 6), QPointF(s - 3, 3))
        elif name in ("t-pass", "t-fail", "t-skip", "t-none", "t-run"):
            colors = {"t-pass": "#3dffa1", "t-fail": "#ff4d6d", "t-skip": "#ffc474", "t-none": "#6f7fa6", "t-run": "#00e5ff"}
            c = QColor(colors[name])
            p.setBrush(Qt.NoBrush); p.setPen(QPen(c, 1.6)); p.drawEllipse(r)
            p.setPen(QPen(c, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if name == "t-pass":
                p.drawPolyline([QPointF(5, s / 2), QPointF(7.3, s / 2 + 2.6), QPointF(s - 4.8, 5.6)])
            elif name == "t-fail":
                p.drawLine(QPointF(5.6, 5.6), QPointF(s - 5.6, s - 5.6)); p.drawLine(QPointF(s - 5.6, 5.6), QPointF(5.6, s - 5.6))
            elif name == "t-skip":
                p.drawLine(QPointF(5.2, s / 2), QPointF(s - 5.2, s / 2))
            elif name == "t-run":
                p.setBrush(c); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(s / 2 - 2, s / 2 - 2, 4, 4))
        elif name == "pause":
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawRect(QRectF(4, 3, 3.2, s - 6)); p.drawRect(QRectF(s - 7.2, 3, 3.2, s - 6))
        elif name == "restart":
            p.drawArc(QRectF(3, 3, s - 6, s - 6), 40 * 16, 280 * 16)
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(s - 3, 2), QPointF(s - 3, 8), QPointF(s - 9, 6)]))
        elif name == "step-over":
            p.drawArc(QRectF(2, 3, s - 4, s - 5), 20 * 16, 140 * 16)
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(s - 2, 5), QPointF(s - 8, 3), QPointF(s - 5, 9)]))
            p.drawEllipse(QRectF(s / 2 - 2.2, s - 6, 4.4, 4.4))
        elif name == "step-in":
            p.drawLine(QPointF(s / 2, 2), QPointF(s / 2, s - 8))
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(s / 2 - 4, s - 9), QPointF(s / 2 + 4, s - 9), QPointF(s / 2, s - 4)]))
            p.drawEllipse(QRectF(s / 2 - 2.2, s - 4, 4.4, 3.6))
        elif name == "step-out":
            p.drawLine(QPointF(s / 2, s - 8), QPointF(s / 2, 6))
            p.setBrush(col); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(s / 2 - 4, 7), QPointF(s / 2 + 4, 7), QPointF(s / 2, 2)]))
            p.drawEllipse(QRectF(s / 2 - 2.2, s - 6, 4.4, 4.4))
        elif name in ("undo", "redo"):
            left = name == "undo"
            p.drawArc(QRectF(3, 4, s - 6, s - 7), 90 * 16, (180 if left else -180) * 16)
            tip = 3 if left else s - 3
            p.setBrush(col); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(tip, 9), QPointF(tip - 3, 5), QPointF(tip + 3, 5)]))
        else:  # Fallback: Buchstabe
            p.setPen(col); f = QFont(); f.setBold(True); f.setPixelSize(size - 3); p.setFont(f)
            p.drawText(pm.rect(), Qt.AlignCenter, name[:2])
        p.end()
        _cache[key] = QIcon(pm)
    return _cache[key]


def control_icon(kind: str, size: int = 16) -> QIcon:
    """Kleine Toolbox-Symbole für die Designer-Controls."""
    key = ("ctl", kind, size)
    if key not in _cache:
        pm = QPixmap(size, size); pm.fill(Qt.transparent)
        p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
        from .theme import C
        col = QColor(C["icon"]); acc = QColor(C["cyan"]); s = size
        p.setPen(QPen(col, 1.2)); p.setBrush(Qt.NoBrush)
        box = QRectF(1.5, 4, s - 3, s - 8)
        if kind == "Button":
            p.drawRoundedRect(box, 2, 2); p.drawLine(QPointF(5, s / 2), QPointF(s - 5, s / 2))
        elif kind == "Label":
            f = QFont(); f.setBold(True); f.setPixelSize(s - 3); p.setFont(f); p.setPen(col); p.drawText(pm.rect(), Qt.AlignCenter, "A")
        elif kind == "TextBox":
            p.drawRect(box); p.setPen(QPen(acc, 1.4)); p.drawLine(QPointF(5, 6), QPointF(5, s - 6))
        elif kind == "RichTextBox":
            p.drawRect(QRectF(1.5, 1.5, s - 3, s - 3)); [p.drawLine(QPointF(4, y), QPointF(s - 4, y)) for y in (5, 8, 11)]
        elif kind == "CheckBox":
            p.drawRect(QRectF(2.5, 2.5, s - 5, s - 5)); p.setPen(QPen(acc, 1.6)); p.drawPolyline([QPointF(5, 8), QPointF(7, 11), QPointF(11, 5)])
        elif kind == "RadioButton":
            p.drawEllipse(QRectF(2, 2, s - 4, s - 4)); p.setBrush(acc); p.setPen(Qt.NoPen); p.drawEllipse(QRectF(5.5, 5.5, s - 11, s - 11))
        elif kind == "ComboBox":
            p.drawRect(box); p.setBrush(acc); p.setPen(Qt.NoPen); p.drawPolygon(QPolygonF([QPointF(s - 8, 7), QPointF(s - 4, 7), QPointF(s - 6, 10)]))
        elif kind == "ListBox":
            p.drawRect(QRectF(1.5, 1.5, s - 3, s - 3)); [p.drawLine(QPointF(4, y), QPointF(s - 4, y)) for y in (5, 8, 11)]; p.setPen(QPen(acc, 1.4)); p.drawLine(QPointF(4, 8), QPointF(s - 4, 8))
        elif kind == "NumericUpDown":
            p.drawRect(box); p.setBrush(acc); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(s - 8, 8), QPointF(s - 4, 8), QPointF(s - 6, 5.5)])); p.drawPolygon(QPolygonF([QPointF(s - 8, 9), QPointF(s - 4, 9), QPointF(s - 6, 11.5)]))
        elif kind == "TrackBar":
            p.drawLine(QPointF(2, s / 2), QPointF(s - 2, s / 2)); p.setBrush(acc); p.setPen(Qt.NoPen); p.drawRect(QRectF(s / 2 - 2, 4, 4, s - 8))
        elif kind == "ProgressBar":
            p.drawRect(QRectF(1.5, 5.5, s - 3, s - 11)); p.setBrush(acc); p.setPen(Qt.NoPen); p.drawRect(QRectF(2.5, 6.5, (s - 5) * .6, s - 13))
        elif kind == "GroupBox":
            p.drawPolyline([QPointF(6, 3), QPointF(1.5, 3), QPointF(1.5, s - 2), QPointF(s - 1.5, s - 2), QPointF(s - 1.5, 3), QPointF(11, 3)])
        elif kind == "Panel":
            p.setPen(QPen(col, 1.2, Qt.DashLine)); p.drawRect(QRectF(1.5, 1.5, s - 3, s - 3))
        else:                                             # Standard: abgerundetes Feld mit Anfangsbuchstaben
            p.drawRoundedRect(QRectF(1.5, 3.5, s - 3, s - 7), 2.5, 2.5)
            f = QFont(); f.setBold(True); f.setPixelSize(max(7, s // 2 - 1)); p.setFont(f); p.setPen(acc)
            p.drawText(pm.rect(), Qt.AlignCenter, kind[:1])
        p.end(); _cache[key] = QIcon(pm)
    return _cache[key]
