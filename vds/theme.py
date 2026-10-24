"""Neon-Look: dunkler Violett-Verlauf, Cyan/Violett-Akzente, abgerundete Flächen. Ein Ort für Farben und das globale Stylesheet."""
import re
from pathlib import Path

from PySide6.QtGui import QColor, QPalette

ASSETS = Path(__file__).parent / "assets"

NEON = dict(
    bg="#060813", bg2="#1c0f36",            # Fenster-Verlauf
    editor="#080a16", panel="#0c0f22", chrome="#0a0d1f",
    fg="#dbe6ff", dim="#8fa3c7", faint="#4d5b82", muted="#6f7fa6",
    cyan="#00e5ff", violet="#b44cff", pink="#ff2d95",
    border="#1b2748", glow="rgba(0,229,255,0.35)",
    green="#3dffa1", red="#ff4d6d", warn="#ffc474", info="#5ee7ff",
    select="#0b3a5c", hover="rgba(0,229,255,0.10)",
    # abgeleitete Flächen und Texte
    editor_fg="#d7e3ff", seltext="#ffffff", icon="#c8d6f5", curline="#0f1530", input="rgba(0,0,0,0.38)", btn="rgba(255,255,255,0.05)",
    track="rgba(255,255,255,0.08)", edge="rgba(125,211,252,0.30)", grid="rgba(27,39,72,0.7)", gutter_cur="#9ad7ff",
    diff_add="#10372d", diff_del="#3b1829", diff_span_l="#8c2c55", diff_span_r="#1c7a58", diff_filler="#1a2040", popup="#0c0f22",
    mid="#0d0b22", bar="rgba(10,13,31,0.85)", bar2="rgba(10,13,31,0.80)", menu_bg="#0c0f22",
)
HELL = dict(
    bg="#f3f5fb", bg2="#e4e8f6",
    editor="#ffffff", panel="#ffffff", chrome="#eef1f9",
    fg="#1b2340", dim="#566089", faint="#98a2c4", muted="#7b86a8",
    cyan="#00789a", violet="#7a35c9", pink="#d6247a",
    border="#c9d0e6", glow="rgba(0,137,173,0.30)",
    green="#0b7f45", red="#d93025", warn="#9a5b00", info="#0b72a8",
    select="#cfe6f5", hover="rgba(0,137,173,0.10)",
    editor_fg="#1b2340", seltext="#0b1230", icon="#3a4670", curline="#eef3ff", input="#ffffff", btn="rgba(0,0,0,0.04)",
    track="rgba(0,0,0,0.08)", edge="#b7c2e0", grid="rgba(120,135,180,0.35)", gutter_cur="#0b72a8",
    diff_add="#dcf5e6", diff_del="#fbe0e6", diff_span_l="#f3a6b8", diff_span_r="#8fd9b0", diff_filler="#e3e7f3", popup="#ffffff",
    mid="#eef1fa", bar="rgba(247,248,253,0.96)", bar2="rgba(240,243,251,0.96)", menu_bg="#ffffff",
)
THEMES = {"neon": NEON, "hell": HELL}
NAMES = {"neon": "Neon (dunkel)", "hell": "Hell"}
C: dict = dict(NEON)                                   # aktive Palette (Schlüssel bleiben gleich, Werte wechseln)
EDITOR_FONT = "Cascadia Code, Cascadia Mono, Consolas, JetBrains Mono, DejaVu Sans Mono, monospace"

# Syntax-Farben
TOKENS_NEON = dict(keyword="#4dd2ff", control="#c792ff", string="#ffc474", comment="#5f6d94", number="#ff8f6b",
                   type="#4df0b4", function="#ffe27a", variable="#9ad7ff", operator="#cbd5f5", preproc="#8a95bd")
TOKENS_HELL = dict(keyword="#0a6fb8", control="#7a35c9", string="#b25a00", comment="#7b86a8", number="#c2410c",
                   type="#0b7a52", function="#8a6d00", variable="#1f5fa8", operator="#3b4570", preproc="#667099")
TOKENS: dict = dict(TOKENS_NEON)
current = "neon"


def stored_theme() -> str:
    """Gespeichertes Farbschema (Umgebungsvariable VDS_THEME hat Vorrang, z. B. für Tests)."""
    import os
    name = os.environ.get("VDS_THEME")
    if not name:
        from PySide6.QtCore import QSettings
        from .branding import SETTINGS_APP, SETTINGS_ORG
        name = str(QSettings(SETTINGS_ORG, SETTINGS_APP).value("ui/theme", "neon"))
    return name if name in THEMES else "neon"


def set_theme(name: str):
    """Aktive Palette wechseln. Muss vor dem Aufbau der Oberfläche geschehen (beim Import wird das gespeicherte Schema gesetzt)."""
    global current
    name = name if name in THEMES else "neon"
    C.clear(); C.update(THEMES[name])
    TOKENS.clear(); TOKENS.update(TOKENS_HELL if name == "hell" else TOKENS_NEON)
    current = name


def is_light() -> bool:
    return current == "hell"


def adapt(color: str) -> str:
    """Akzentfarben (Status, Syntax, Symbole) sind für dunklen Grund entworfen; im hellen Schema werden sie abgedunkelt, damit sie lesbar bleiben."""
    if not is_light():
        return color
    from PySide6.QtGui import QColor
    c = QColor(color)
    h, s, l, a = c.hslHueF(), c.hslSaturationF(), c.lightnessF(), c.alphaF()
    out = QColor.fromHslF(max(h, 0.0), min(1.0, s * 1.05), min(l, 0.36), a)
    return out.name()


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_LIGHT_MAP = {   # dunkle Neon-Flächen/-Texte -> Palette-Schlüssel oder feste helle Werte
    "#0c0f22": "panel", "#080a16": "editor", "#0a0d1f": "chrome", "#0f1530": "curline", "#dbe6ff": "fg", "#d7e3ff": "fg", "#e6eeff": "fg", "#f1f1f1": "fg",
    "#8fa3c7": "dim", "#9fb3d9": "dim", "#7f93bd": "dim", "#6f7fa6": "muted", "#6f82ad": "muted", "#4d5b82": "faint", "#c8d6f5": "icon", "#00e5ff": "cyan",
    "#00b8d9": "cyan", "#9ad7ff": "gutter_cur", "#10372d": "diff_add", "#3b1829": "diff_del", "#8c2c55": "diff_span_l", "#1c7a58": "diff_span_r",
    "#1a2040": "diff_filler", "#161b3a": "#e8ecf8", "#2a3a6a": "#c3cbe6", "#1b2a5c": "#dbe7ff", "#121a3d": "#f0f3fb", "#33427a": "#b7c2e0", "#ffffff": "#ffffff",
}


def _one(m) -> str:
    h = m.group(0).lower()
    v = _LIGHT_MAP.get(h)
    if v is None:
        return adapt(h)
    return C[v] if v in C else v


def t(value):
    """Farbliteral oder Stylesheet-/HTML-Text: im Neon-Schema unverändert, im hellen Schema werden dunkle Flächen und helle Akzentfarben ersetzt."""
    if not is_light() or not isinstance(value, str):
        return value
    return _HEX.sub(_one, value)


set_theme(stored_theme())


def apply_palette(app):
    p = QPalette()
    for role, key in [(QPalette.Window, "bg"), (QPalette.Base, "editor"), (QPalette.AlternateBase, "panel"),
                      (QPalette.Button, "chrome"), (QPalette.ToolTipBase, "panel"), (QPalette.Highlight, "select")]:
        p.setColor(role, QColor(C[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText, QPalette.HighlightedText):
        p.setColor(role, QColor(C["fg"]))
    p.setColor(QPalette.PlaceholderText, QColor(C["faint"]))
    app.setPalette(p)


def stylesheet() -> str:
    c = C
    close, close_hover = (ASSETS / "close.svg").as_posix(), (ASSETS / "close-hover.svg").as_posix()
    check = (ASSETS / "check.svg").as_posix()
    grad = "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(0,229,255,0.34), stop:1 rgba(180,76,255,0.30))"
    return f"""
* {{ font-family: "Segoe UI", "Noto Sans", "Cantarell", sans-serif; font-size: 12px; }}
QMainWindow, QDialog {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {c['bg']}, stop:0.6 {c['mid']}, stop:1 {c['bg2']}); color: {c['fg']}; }}
QMainWindow::separator {{ background: transparent; width: 5px; height: 5px; }}
QMainWindow::separator:hover {{ background: {c['cyan']}; }}
QWidget {{ color: {c['fg']}; }}

/* Menüleiste & Menüs */
QMenuBar {{ background: {c['bar']}; color: {c['fg']}; border-bottom: 1px solid {c['border']}; }}
QMenuBar::item {{ padding: 6px 11px; background: transparent; border-radius: 6px; margin: 2px 1px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {grad}; color: {c['seltext']}; }}
QMenu {{ background: {c['panel']}; border: 1px solid rgba(0,229,255,0.45); padding: 5px 0; }}
QMenu::item {{ padding: 6px 28px 6px 30px; margin: 1px 5px; border-radius: 6px; }}
QMenu::item:selected {{ background: {grad}; color: {c['seltext']}; }}
QMenu::item:disabled {{ color: {c['faint']}; }}
QMenu::separator {{ height: 1px; background: rgba(0,229,255,0.18); margin: 5px 10px; }}

/* Werkzeugleiste */
QToolBar {{ background: {c['bar2']}; border: 0; border-bottom: 1px solid {c['border']}; spacing: 3px; padding: 3px 8px; }}
QToolBar::separator {{ width: 1px; background: rgba(0,229,255,0.22); margin: 5px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 8px; padding: 3px 6px; color: {c['fg']}; }}
QToolButton:hover {{ background: {c['hover']}; border-color: rgba(0,229,255,0.55); }}
QToolButton:pressed, QToolButton:checked {{ background: {grad}; border-color: {c['cyan']}; }}
QToolButton:disabled {{ color: {c['faint']}; }}

/* Eingabefelder */
QComboBox, QLineEdit, QSpinBox {{ background: {c['input']}; border: 1px solid {c['edge']}; border-radius: 8px; padding: 3px 9px; min-height: 18px; selection-background-color: {c['select']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c['cyan']}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid rgba(0,229,255,0.45); selection-background-color: {c['select']}; outline: 0; }}
QPushButton {{ background: {c['btn']}; border: 1px solid {c['edge']}; border-radius: 8px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {c['cyan']}; background: {c['hover']}; }}
QPushButton:pressed {{ background: {grad}; }}
QPushButton:disabled {{ color: {c['faint']}; border-color: {c['edge']}; }}
QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c['cyan']}, stop:1 {c['violet']}); border: none; color: #fff; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {c['track']}; color: {c['faint']}; }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['edge']}; border-radius: 4px; background: {c['input']}; }}
QCheckBox::indicator:checked {{ background: {c['cyan']}; border-color: {c['cyan']}; image: url({check}); }}

/* Docks */
QDockWidget {{ color: {c['fg']}; }}
QDockWidget::title {{ background: rgba(0,229,255,0.07); padding: 6px 12px; border-bottom: 1px solid rgba(0,229,255,0.30); letter-spacing: 1px; }}
QDockWidget[active="true"]::title {{ background: {grad}; border-bottom: 1px solid {c['cyan']}; color: {c['seltext']}; }}

/* Listen, Bäume, Tabellen */
QTreeView, QListView, QTableView, QTableWidget, QTreeWidget, QListWidget {{ background: {c['panel']}; border: 0; outline: 0; alternate-background-color: {c['panel']}; }}
QTreeView::item, QListView::item {{ height: 24px; border-radius: 6px; margin: 0 4px; }}
QTreeView::item:hover, QListView::item:hover, QListWidget::item:hover {{ background: {c['hover']}; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected, QListWidget::item:selected {{ background: {grad}; color: {c['seltext']}; }}
QTreeView::item:selected:!active {{ background: rgba(0,229,255,0.14); }}
QTableView::item:selected {{ border-radius: 0; }}
QHeaderView::section {{ background: rgba(0,229,255,0.06); color: {c['dim']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 4px 10px; letter-spacing: 1px; }}
QTableView {{ gridline-color: {c['grid']}; }}

/* Tabs (Dokumente oben, Tool-Fenster unten) */
QTabWidget::pane {{ border: 0; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {c['dim']}; padding: 7px 14px; margin-right: 2px; border-top-left-radius: 8px; border-top-right-radius: 8px; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ background: {c['hover']}; color: {c['seltext']}; }}
QTabBar::tab:selected {{ background: rgba(0,229,255,0.10); color: {c['seltext']}; border-bottom: 2px solid {c['cyan']}; }}
QTabBar::tab:bottom {{ border-radius: 0; border-bottom: 0; border-top: 2px solid transparent; padding: 5px 13px; }}
QTabBar::tab:bottom:selected {{ background: rgba(0,229,255,0.10); border-top: 2px solid {c['cyan']}; }}
QTabBar::close-button {{ image: url({close}); subcontrol-position: right; padding: 2px; border-radius: 8px; }}
QTabBar::close-button:hover {{ image: url({close_hover}); }}

/* Statusleiste */
QStatusBar {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00a8c8, stop:0.55 #5b3df5, stop:1 #a63cf0); color: #fff; }}
QStatusBar[busy="true"] {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #d4147a, stop:1 #ff2d95); }}
QStatusBar[debug="true"] {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #c24d00, stop:0.6 #ff7a00, stop:1 #ffb000); }}
QStatusBar[debug="true"] QLabel {{ color: #1a0f00; font-weight: 600; }}
QStatusBar QLabel {{ color: #fff; padding: 0 8px; }}
QStatusBar::item {{ border: 0; }}

/* Editoren */
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {c['editor']}; color: {c['editor_fg']}; border: 0; selection-background-color: rgba(0,229,255,0.30); }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {c['panel']}; color: {c['fg']}; border: 1px solid {c['cyan']}; padding: 4px 8px; border-radius: 6px; }}

/* Scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {c['edge']}; border-radius: 4px; min-height: 28px; min-width: 28px; margin: 2px; }}
QScrollBar::handle:hover {{ background: rgba(0,229,255,0.65); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: 0; height: 0; width: 0; }}
QProgressBar {{ background: {c['track']}; border: 0; border-radius: 3px; text-align: center; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00e5ff, stop:1 #b44cff); border-radius: 3px; }}
QLabel#sub {{ color: {c['dim']}; }}
"""
