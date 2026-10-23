"""Schriftart-Dialog im futuristischen Look: Familienliste in Eigenschrift, Live-Vorschau mit Glow, Gewicht/Größe per Slider,
Stil-Schalter. Dazu Hilfen zum Umwandeln zwischen QFont und einem JSON-fähigen Dict (für den Formular-Designer)."""
from PySide6.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (QButtonGroup, QDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QStyledItemDelegate, QSlider, QSpinBox, QTextEdit, QVBoxLayout, QWidget)

WEIGHTS = [(100, "Thin"), (200, "ExtraLight"), (300, "Light"), (400, "Normal"), (500, "Medium"),
           (600, "DemiBold"), (700, "Fett"), (800, "ExtraBold"), (900, "Black")]
WEIGHT_NAME = dict(WEIGHTS)
SIZE_CHIPS = [8, 10, 12, 14, 18, 24, 36, 48, 72]
SAMPLES = {
    "Text": "Falsche Zicke, Xylofon & Wörter\nDer schnelle braune Fuchs springt über den faulen Hund.\n0123456789  ÄÖÜ äöü ß",
    "Code": 'def greet(name: str) -> str:\n    return f"Hallo, {name}!"   # 0O 1lI != == -> =>',
    "Symbole": "0123456789   ½ ¼ € § & @ # %\n← → ↑ ↓ ✓ ✗ ≠ ≤ ≥ ∑ √ ∞ ★",
}

QSS = """
QDialog#fontdlg { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #060813, stop:0.55 #0f0c24, stop:1 #1c0f36); }
QDialog#fontdlg QLabel { color: #d7e3ff; background: transparent; }
QLabel#kicker { color: #00e5ff; font-size: 10px; letter-spacing: 4px; }
QLabel#title { font-size: 26px; font-weight: 200; letter-spacing: 3px; color: #ffffff; }
QLabel#section { color: #7dd3fc; font-size: 10px; letter-spacing: 3px; }
QLabel#info { color: #9fb3d9; font-size: 11px; letter-spacing: 1px; }
QWidget#card { background: rgba(255,255,255,0.045); border: 1px solid rgba(0,229,255,0.22); border-radius: 14px; }
QWidget#preview { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(0,229,255,0.10), stop:1 rgba(224,64,251,0.10));
                  border: 1px solid rgba(0,229,255,0.65); border-radius: 16px; }
QTextEdit#previewText { background: transparent; border: none; color: #ffffff; selection-background-color: rgba(0,229,255,0.35); }
QLineEdit#search { background: rgba(0,0,0,0.35); border: 1px solid rgba(125,211,252,0.35); border-radius: 10px; padding: 8px 12px; color: #fff; font-size: 13px; }
QLineEdit#search:focus { border-color: #00e5ff; }
QListWidget { background: transparent; border: none; outline: 0; color: #e6eeff; }
QListWidget::item { padding: 5px 10px; border-radius: 8px; }
QListWidget::item:hover { background: rgba(0,229,255,0.10); }
QListWidget::item:selected { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,229,255,0.35), stop:1 rgba(224,64,251,0.30)); color: #fff; border: 1px solid rgba(0,229,255,0.7); }
QPushButton#pill, QPushButton#chip { background: rgba(255,255,255,0.05); border: 1px solid rgba(125,211,252,0.35); border-radius: 15px; color: #cfe0ff; padding: 5px 14px; }
QPushButton#pill:hover, QPushButton#chip:hover { border-color: #00e5ff; color: #fff; }
QPushButton#pill:checked, QPushButton#chip:checked { background: rgba(0,229,255,0.22); border-color: #00e5ff; color: #ffffff; }
QPushButton#ghost { background: transparent; border: 1px solid rgba(255,255,255,0.25); border-radius: 12px; color: #cfd8ee; padding: 8px 18px; }
QPushButton#ghost:hover { border-color: #fff; }
QPushButton#go { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00e5ff, stop:1 #b44cff); border: none; border-radius: 12px; color: #05060f; font-weight: 600; padding: 9px 26px; letter-spacing: 1px; }
QPushButton#go:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5af0ff, stop:1 #cf7cff); }
QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,0.15); border-radius: 2px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00e5ff, stop:1 #b44cff); border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -7px 0; border-radius: 8px; background: #0a0d1c; border: 2px solid #00e5ff; }
QSlider::handle:horizontal:hover { background: #00e5ff; }
QSpinBox { background: rgba(0,0,0,0.35); border: 1px solid rgba(125,211,252,0.35); border-radius: 8px; color: #fff; padding: 3px 8px; min-width: 56px; }
QScrollBar:vertical { background: transparent; width: 8px; } QScrollBar::handle:vertical { background: rgba(125,211,252,0.35); border-radius: 4px; min-height: 30px; margin: 0; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


# --- QFont <-> Dict ---------------------------------------------------------------------------------------------
def font_to_dict(f: QFont) -> dict:
    return {"family": f.family(), "size": f.pointSize() if f.pointSize() > 0 else 10, "weight": int(f.weight()),
            "italic": f.italic(), "underline": f.underline(), "strike": f.strikeOut()}


def dict_to_font(d: dict) -> QFont:
    f = QFont(d.get("family", ""))
    f.setPointSize(int(d.get("size", 10)))
    f.setWeight(QFont.Weight(int(d.get("weight", 400))))
    f.setItalic(bool(d.get("italic"))); f.setUnderline(bool(d.get("underline"))); f.setStrikeOut(bool(d.get("strike")))
    return f


def describe(d) -> str:
    """Kurzbeschreibung wie „Cascadia Code, 12 pt, Fett, Kursiv“."""
    if not d:
        return ""
    bits = [d.get("family", ""), f"{d.get('size', 10)} pt"]
    w = int(d.get("weight", 400))
    if w != 400:
        bits.append(WEIGHT_NAME.get(w, str(w)))
    bits += [n for k, n in (("italic", "Kursiv"), ("underline", "Unterstrichen"), ("strike", "Durchgestrichen")) if d.get(k)]
    return ", ".join(bits)


class _FamilyDelegate(QStyledItemDelegate):
    """Zeigt jede Familie in ihrer eigenen Schrift – aber erst beim Zeichnen der sichtbaren Zeilen (schnelles Öffnen).
    Symbolschriften ohne lateinische Buchstaben erscheinen gedimmt in der Standardschrift."""
    ROW = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache: dict = {}

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        fam = index.data(Qt.DisplayRole)
        if fam not in self.cache:
            f = QFont(fam, 13)
            self.cache[fam] = f if QFontMetrics(f).inFontUcs4(ord("A")) else None
        f = self.cache[fam]
        if f is not None:
            option.font = f
        else:
            option.palette.setColor(option.palette.ColorRole.Text, QColor("#8fa3c7"))
            option.palette.setColor(option.palette.ColorRole.HighlightedText, QColor("#8fa3c7"))


# --- Dialog ---------------------------------------------------------------------------------------------------------
class FontDialog(QDialog):
    def __init__(self, font: QFont | None = None, parent=None, monospace=False, title="Schriftart"):
        super().__init__(parent)
        self.setObjectName("fontdlg")
        self.setWindowTitle(title)
        self.resize(940, 640)
        self.setStyleSheet(QSS)
        self.initial = QFont(font) if font else QFont()
        self.mono_default = monospace
        self._building = True

        # Kopf
        kicker = QLabel("T Y P O G R A P H Y   //   S E L E C T"); kicker.setObjectName("kicker")
        head = QLabel(title.upper()); head.setObjectName("title")
        # linke Karte: Suche + Familien
        self.search = QLineEdit(); self.search.setObjectName("search"); self.search.setPlaceholderText("Schriftart suchen …")
        self.b_all, self.b_mono = self._pill("Alle", True), self._pill("Monospace", False)
        grp = QButtonGroup(self); grp.setExclusive(True); grp.addButton(self.b_all); grp.addButton(self.b_mono)
        (self.b_mono if monospace else self.b_all).setChecked(True)
        chips = QHBoxLayout(); chips.addWidget(self.b_all); chips.addWidget(self.b_mono); chips.addStretch()
        self.count = QLabel(); self.count.setObjectName("info")
        self.families = QListWidget(); self.families.setUniformItemSizes(True); self.families.setItemDelegate(_FamilyDelegate(self.families)); self.families.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        left = QWidget(); left.setObjectName("card"); ll = QVBoxLayout(left); ll.setContentsMargins(14, 14, 14, 12); ll.setSpacing(10)
        ll.addWidget(self._section("SCHRIFTFAMILIE")); ll.addWidget(self.search); ll.addLayout(chips); ll.addWidget(self.families, 1); ll.addWidget(self.count)
        left.setFixedWidth(300)

        # Vorschau
        self.preview_card = QWidget(); self.preview_card.setObjectName("preview")
        self.preview = QTextEdit(); self.preview.setObjectName("previewText"); self.preview.setAcceptRichText(False)
        self.preview.setPlainText(SAMPLES["Text"]); self._center()
        modes = QHBoxLayout(); self.mode_btns = []
        for name in SAMPLES:
            b = self._pill(name, name == "Text"); b.clicked.connect(lambda _c, n=name: self._sample(n)); modes.addWidget(b); self.mode_btns.append(b)
        modes.addStretch(); self.info = QLabel(); self.info.setObjectName("info")
        modes.addWidget(self.info)
        pl = QVBoxLayout(self.preview_card); pl.setContentsMargins(18, 14, 18, 12)
        pl.addWidget(self._section("LIVE-VORSCHAU")); pl.addWidget(self.preview, 1); pl.addLayout(modes)
        self.glow = QGraphicsDropShadowEffect(self.preview_card); self.glow.setColor(QColor(0, 229, 255, 150)); self.glow.setOffset(0, 0); self.glow.setBlurRadius(24)
        self.preview_card.setGraphicsEffect(self.glow)
        self._pulse = QVariantAnimation(self, duration=2600, startValue=14.0, endValue=38.0, loopCount=-1)
        self._pulse.setEasingCurve(QEasingCurve.InOutSine); self._pulse.valueChanged.connect(lambda v: self.glow.setBlurRadius(float(v)))
        self._pulse.start()

        # Regler
        self.weight = QSlider(Qt.Horizontal); self.weight.setRange(0, len(WEIGHTS) - 1)
        self.weight_name = QLabel(); self.weight_name.setObjectName("info")
        self.size = QSlider(Qt.Horizontal); self.size.setRange(6, 96)
        self.size_spin = QSpinBox(); self.size_spin.setRange(6, 96); self.size_spin.setSuffix(" pt")
        self.size_chips = []
        sc = QHBoxLayout(); sc.setSpacing(6)
        for n in SIZE_CHIPS:
            b = self._pill(str(n), False); b.setObjectName("chip"); b.clicked.connect(lambda _c, n=n: self.size.setValue(n)); sc.addWidget(b); self.size_chips.append((n, b))
        sc.addStretch()
        self.b_it, self.b_ul, self.b_st = self._pill("Kursiv", False), self._pill("Unterstrichen", False), self._pill("Durchgestrichen", False)
        styles = QHBoxLayout(); [styles.addWidget(b) for b in (self.b_it, self.b_ul, self.b_st)]; styles.addStretch()
        ctrl = QWidget(); ctrl.setObjectName("card"); cl = QVBoxLayout(ctrl); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(8)
        wrow = QHBoxLayout(); wrow.addWidget(self._section("GEWICHT")); wrow.addStretch(); wrow.addWidget(self.weight_name)
        srow = QHBoxLayout(); srow.addWidget(self._section("GRÖSSE")); srow.addStretch(); srow.addWidget(self.size_spin)
        cl.addLayout(wrow); cl.addWidget(self.weight); cl.addSpacing(4); cl.addLayout(srow); cl.addWidget(self.size); cl.addLayout(sc)
        cl.addSpacing(4); cl.addWidget(self._section("STIL")); cl.addLayout(styles)

        right = QVBoxLayout(); right.setSpacing(14); right.addWidget(self.preview_card, 3); right.addWidget(ctrl, 0)
        body = QHBoxLayout(); body.setSpacing(16); body.addWidget(left); body.addLayout(right, 1)

        # Fuß
        self.b_reset = QPushButton("Zurücksetzen"); self.b_reset.setObjectName("ghost")
        b_cancel = QPushButton("Abbrechen"); b_cancel.setObjectName("ghost")
        self.b_ok = QPushButton("ÜBERNEHMEN"); self.b_ok.setObjectName("go"); self.b_ok.setDefault(True)
        ok_glow = QGraphicsDropShadowEffect(self.b_ok); ok_glow.setColor(QColor(0, 229, 255, 170)); ok_glow.setOffset(0, 0); ok_glow.setBlurRadius(22)
        self.b_ok.setGraphicsEffect(ok_glow)
        foot = QHBoxLayout(); foot.addWidget(self.b_reset); foot.addStretch(); foot.addWidget(b_cancel); foot.addWidget(self.b_ok)
        root = QVBoxLayout(self); root.setContentsMargins(26, 20, 26, 18); root.setSpacing(12)
        root.addWidget(kicker); root.addWidget(head); root.addSpacing(4); root.addLayout(body, 1); root.addLayout(foot)

        # Verdrahtung
        self.search.textChanged.connect(self._fill); self.b_all.toggled.connect(self._fill)
        self.families.currentItemChanged.connect(lambda *_: self._changed())
        self.weight.valueChanged.connect(lambda *_: self._changed())
        self.size.valueChanged.connect(self._size_changed); self.size_spin.valueChanged.connect(self.size.setValue)
        for b in (self.b_it, self.b_ul, self.b_st):
            b.toggled.connect(lambda *_: self._changed())
        self.b_reset.clicked.connect(lambda: self._load(self.initial))
        b_cancel.clicked.connect(self.reject); self.b_ok.clicked.connect(self.accept)
        self._building = False
        self._fill()
        self._load(self.initial)

    # --- Bausteine ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _section(text):
        l = QLabel(text); l.setObjectName("section"); return l

    @staticmethod
    def _pill(text, checked):
        b = QPushButton(text); b.setObjectName("pill"); b.setCheckable(True); b.setChecked(checked); b.setCursor(Qt.PointingHandCursor); return b

    # --- Logik ----------------------------------------------------------------------------------------------------------
    def _fill(self, *_):
        sel = self.family()
        q = self.search.text().strip().lower()
        mono = self.b_mono.isChecked()
        self.families.blockSignals(True); self.families.clear()
        shown = 0
        for fam in QFontDatabase.families():
            if (q and q not in fam.lower()) or (mono and not QFontDatabase.isFixedPitch(fam)):
                continue
            it = QListWidgetItem(fam)
            self.families.addItem(it); shown += 1
        self.families.blockSignals(False)
        self.count.setText(f"{shown} Schriftarten")
        if sel:
            self._select_family(sel)

    def _select_family(self, fam):
        items = self.families.findItems(fam, Qt.MatchExactly)
        if items:
            self.families.setCurrentItem(items[0]); self.families.scrollToItem(items[0], QListWidget.PositionAtCenter)

    def family(self) -> str:
        it = self.families.currentItem()
        return it.text() if it else ""

    def _load(self, f: QFont):
        self._building = True
        fam = QFont(f).family() or QFont().family()
        if not self.families.findItems(fam, Qt.MatchExactly):       # gefiltert? Filter lockern
            self.b_all.setChecked(True); self.search.clear(); self._fill()
        self._select_family(fam)
        w = int(f.weight()) if f.weight() else 400
        self.weight.setValue(min(range(len(WEIGHTS)), key=lambda i: abs(WEIGHTS[i][0] - w)))
        sz = f.pointSize() if f.pointSize() > 0 else 10
        self.size.setValue(sz); self.size_spin.setValue(sz)
        self.b_it.setChecked(f.italic()); self.b_ul.setChecked(f.underline()); self.b_st.setChecked(f.strikeOut())
        self._building = False
        self._changed()

    def _size_changed(self, v):
        self.size_spin.blockSignals(True); self.size_spin.setValue(v); self.size_spin.blockSignals(False)
        for n, b in self.size_chips:
            b.setChecked(n == v)
        self._changed()

    def _center(self):
        """Zentriert alle Absätze der Vorschau (setAlignment wirkt nur auf den aktuellen Absatz)."""
        c = QTextCursor(self.preview.document())
        c.select(QTextCursor.Document)
        fmt = QTextBlockFormat(); fmt.setAlignment(Qt.AlignCenter)
        c.mergeBlockFormat(fmt)

    def _sample(self, name):
        for b in self.mode_btns:
            b.setChecked(b.text() == name)
        self.preview.setPlainText(SAMPLES[name]); self._center(); self._changed()

    def font(self) -> QFont:
        f = QFont(self.family() or self.initial.family())
        f.setPointSize(self.size.value())
        f.setWeight(QFont.Weight(WEIGHTS[self.weight.value()][0]))
        f.setItalic(self.b_it.isChecked()); f.setUnderline(self.b_ul.isChecked()); f.setStrikeOut(self.b_st.isChecked())
        return f

    def _changed(self):
        if self._building:
            return
        f = self.font()
        self.weight_name.setText(f"{WEIGHTS[self.weight.value()][1]}  ·  {WEIGHTS[self.weight.value()][0]}")
        self.preview.setFont(f); self._center()
        self.info.setText(describe(font_to_dict(f)))

    @staticmethod
    def get_font(initial: QFont | None = None, parent=None, monospace=False, title="Schriftart") -> QFont | None:
        d = FontDialog(initial, parent, monospace, title)
        return d.font() if d.exec() else None
