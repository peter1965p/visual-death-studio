"""Startbild: Neon-Totenkopf, Titel, „2026 by Peter Päffgen“ und ein Fortschrittsbalken mit Statustext."""
from PySide6.QtCore import QElapsedTimer, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import __version__
from .branding import APP_NAME

W, H = 640, 360
MIN_TOTAL_MS = 3500          # so lange bleibt das Startbild mindestens sichtbar (Start selbst ist meist schneller)
CYAN, VIOLET, PINK = QColor("#00e5ff"), QColor("#b44cff"), QColor("#ff2d95")


def skull_path(cx: float, cy: float, s: float) -> tuple:
    """(Schädel, Augenhöhlen, Nase, Zähne) als Pfade; s = Breite des Schädels."""
    skull = QPainterPath()
    skull.addEllipse(QRectF(cx - s / 2, cy - s * 0.52, s, s * 0.86))                         # Hirnschädel
    jaw = QPainterPath(); jaw.addRoundedRect(QRectF(cx - s * 0.30, cy + s * 0.14, s * 0.60, s * 0.38), s * 0.07, s * 0.07)
    skull = skull.united(jaw)
    eyes = QPainterPath()
    for dx in (-1, 1):
        e = QPainterPath(); e.addEllipse(QRectF(cx + dx * s * 0.20 - s * 0.115, cy - s * 0.10, s * 0.23, s * 0.25)); eyes = eyes.united(e)
    nose = QPainterPath(); nose.moveTo(cx, cy + s * 0.12)
    nose.lineTo(cx - s * 0.055, cy + s * 0.25); nose.lineTo(cx + s * 0.055, cy + s * 0.25); nose.closeSubpath()
    teeth = QPainterPath()
    for i in range(-2, 3):
        x = cx + i * s * 0.11
        teeth.moveTo(x, cy + s * 0.30); teeth.lineTo(x, cy + s * 0.50)
    teeth.moveTo(cx - s * 0.27, cy + s * 0.31); teeth.lineTo(cx + s * 0.27, cy + s * 0.31)
    return skull, eyes, nose, teeth


def draw_skull(p: QPainter, cx: float, cy: float, s: float):
    skull, eyes, nose, teeth = skull_path(cx, cy, s)
    glow = QRadialGradient(QPointF(cx, cy), s * 0.95)
    glow.setColorAt(0, QColor(180, 76, 255, 90)); glow.setColorAt(1, QColor(180, 76, 255, 0))
    p.setPen(Qt.NoPen); p.setBrush(glow); p.drawEllipse(QPointF(cx, cy), s * 0.95, s * 0.95)
    for width, alpha in ((9, 28), (5, 60), (2.4, 255)):                                      # Neon-Leuchten: breite blasse Linien unter der scharfen
        g = QLinearGradient(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)
        c1, c2 = QColor(CYAN), QColor(VIOLET)
        c1.setAlpha(alpha); c2.setAlpha(alpha)
        g.setColorAt(0, c1); g.setColorAt(1, c2)
        p.setPen(QPen(g, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.setBrush(Qt.NoBrush)
        p.drawPath(skull)
        p.drawPath(teeth)
    p.setPen(Qt.NoPen); p.setBrush(QColor(6, 8, 19)); p.drawPath(eyes); p.drawPath(nose)
    for dx in (-1, 1):                                                                       # glühende Pupillen
        r = s * 0.045
        pg = QRadialGradient(QPointF(cx + dx * s * 0.20, cy + s * 0.03), r * 2.4)
        pg.setColorAt(0, QColor(PINK)); pg.setColorAt(1, QColor(255, 45, 149, 0))
        p.setBrush(pg); p.drawEllipse(QPointF(cx + dx * s * 0.20, cy + s * 0.03), r * 2.4, r * 2.4)
    p.setPen(QPen(CYAN, 1.6)); p.setBrush(Qt.NoBrush); p.drawPath(eyes); p.drawPath(nose)


class SplashScreen(QWidget):
    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.value, self.text = 0.0, "Starte …"
        self._clock = QElapsedTimer()
        scr = QGuiApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - W // 2, g.center().y() - H // 2)

    def showEvent(self, e):
        if not self._clock.isValid():
            self._clock.start()
        super().showEvent(e)

    def step(self, percent: float, text: str):
        """Fortschritt setzen und sofort zeichnen (wird während des Starts aus dem Hauptfenster aufgerufen)."""
        self.value, self.text = max(0.0, min(100.0, float(percent))), text
        self.repaint()
        QGuiApplication.processEvents()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(6, 6, W - 12, H - 12)
        bg = QLinearGradient(0, 0, W, H)
        bg.setColorAt(0, QColor("#060813")); bg.setColorAt(0.6, QColor("#0d0b22")); bg.setColorAt(1, QColor("#1c0f36"))
        p.setPen(QPen(QColor(0, 229, 255, 150), 1.5)); p.setBrush(bg); p.drawRoundedRect(box, 18, 18)
        # Raster im Hintergrund
        p.setPen(QPen(QColor(0, 229, 255, 14), 1))
        for x in range(24, W - 12, 28):
            p.drawLine(x, 14, x, H - 14)
        draw_skull(p, 150, 150, 150)
        # Titel
        f = QFont("Segoe UI", 28); f.setWeight(QFont.Light); p.setFont(f)
        tg = QLinearGradient(290, 0, W - 30, 0); tg.setColorAt(0, CYAN); tg.setColorAt(1, VIOLET)
        p.setPen(QPen(tg, 1)); p.drawText(QRectF(285, 80, W - 300, 44), Qt.AlignLeft | Qt.AlignVCenter, "Visual")
        f2 = QFont("Segoe UI", 34); f2.setWeight(QFont.DemiBold); p.setFont(f2)
        p.setPen(QColor("#dbe6ff")); p.drawText(QRectF(285, 118, W - 300, 52), Qt.AlignLeft | Qt.AlignVCenter, "Death Studio")
        f3 = QFont("Segoe UI", 11); p.setFont(f3)
        p.setPen(QColor("#8fa3c7")); p.drawText(QRectF(287, 176, W - 300, 24), Qt.AlignLeft | Qt.AlignVCenter, f"{__version__}   ·   2026 by Peter Päffgen")
        p.setPen(QColor("#4d5b82")); p.drawText(QRectF(287, 200, W - 300, 22), Qt.AlignLeft | Qt.AlignVCenter, "Päffgen IT")
        # Fortschritt
        track = QRectF(40, H - 78, W - 80, 12)
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 22)); p.drawRoundedRect(track, 6, 6)
        fill = QRectF(track.x(), track.y(), max(12.0, track.width() * self.value / 100), track.height())
        pg = QLinearGradient(track.x(), 0, track.right(), 0); pg.setColorAt(0, CYAN); pg.setColorAt(1, VIOLET)
        p.setBrush(pg); p.drawRoundedRect(fill, 6, 6)
        p.setBrush(QColor(0, 229, 255, 40)); p.drawRoundedRect(fill.adjusted(-3, -3, 3, 3), 8, 8)
        p.setFont(QFont("Segoe UI", 10)); p.setPen(QColor("#c8d6f5"))
        p.drawText(QRectF(40, H - 60, W - 160, 22), Qt.AlignLeft | Qt.AlignVCenter, self.text)
        p.setPen(QColor(CYAN)); p.drawText(QRectF(W - 120, H - 60, 80, 22), Qt.AlignRight | Qt.AlignVCenter, f"{int(self.value)} %")

    def finish(self, window=None, min_total_ms: int = MIN_TOTAL_MS):
        """Auf 100 % setzen, insgesamt mindestens `min_total_ms` seit dem Zeigen sichtbar lassen, dann sanft ausblenden und schließen."""
        self.step(100, "Fertig")
        min_ms = max(400, min_total_ms - (self._clock.elapsed() if self._clock.isValid() else 0))
        def fade():
            a = QPropertyAnimation(self, b"windowOpacity", self)
            a.setDuration(260); a.setStartValue(1.0); a.setEndValue(0.0); a.setEasingCurve(QEasingCurve.InQuad)
            a.finished.connect(self.close)
            a.start()
            self._anim = a
        QTimer.singleShot(min_ms, fade)
