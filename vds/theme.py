"""Neon-Look: dunkler Violett-Verlauf, Cyan/Violett-Akzente, abgerundete Flächen. Ein Ort für Farben und das globale Stylesheet."""
from pathlib import Path

from PySide6.QtGui import QColor, QPalette

ASSETS = Path(__file__).parent / "assets"

C = dict(
    bg="#060813", bg2="#1c0f36",            # Fenster-Verlauf
    editor="#080a16", panel="#0c0f22", chrome="#0a0d1f",
    fg="#dbe6ff", dim="#8fa3c7", faint="#4d5b82",
    cyan="#00e5ff", violet="#b44cff", pink="#ff2d95",
    border="#1b2748", glow="rgba(0,229,255,0.35)",
    green="#3dffa1", red="#ff4d6d", warn="#ffc474", info="#5ee7ff",
    select="#0b3a5c", hover="rgba(0,229,255,0.10)",
)
EDITOR_FONT = "Cascadia Code, Cascadia Mono, Consolas, JetBrains Mono, DejaVu Sans Mono, monospace"

# Syntax-Farben (Neon-Dark)
TOKENS = dict(keyword="#4dd2ff", control="#c792ff", string="#ffc474", comment="#5f6d94", number="#ff8f6b",
              type="#4df0b4", function="#ffe27a", variable="#9ad7ff", operator="#cbd5f5", preproc="#8a95bd")


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
QMainWindow, QDialog {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {c['bg']}, stop:0.6 #0d0b22, stop:1 {c['bg2']}); color: {c['fg']}; }}
QMainWindow::separator {{ background: transparent; width: 5px; height: 5px; }}
QMainWindow::separator:hover {{ background: {c['cyan']}; }}
QWidget {{ color: {c['fg']}; }}

/* Menüleiste & Menüs */
QMenuBar {{ background: rgba(10,13,31,0.85); color: {c['fg']}; border-bottom: 1px solid {c['border']}; }}
QMenuBar::item {{ padding: 6px 11px; background: transparent; border-radius: 6px; margin: 2px 1px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {grad}; color: #fff; }}
QMenu {{ background: {c['panel']}; border: 1px solid rgba(0,229,255,0.45); padding: 5px 0; }}
QMenu::item {{ padding: 6px 28px 6px 30px; margin: 1px 5px; border-radius: 6px; }}
QMenu::item:selected {{ background: {grad}; color: #fff; }}
QMenu::item:disabled {{ color: {c['faint']}; }}
QMenu::separator {{ height: 1px; background: rgba(0,229,255,0.18); margin: 5px 10px; }}

/* Werkzeugleiste */
QToolBar {{ background: rgba(10,13,31,0.80); border: 0; border-bottom: 1px solid {c['border']}; spacing: 3px; padding: 3px 8px; }}
QToolBar::separator {{ width: 1px; background: rgba(0,229,255,0.22); margin: 5px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 8px; padding: 3px 6px; color: {c['fg']}; }}
QToolButton:hover {{ background: {c['hover']}; border-color: rgba(0,229,255,0.55); }}
QToolButton:pressed, QToolButton:checked {{ background: {grad}; border-color: {c['cyan']}; }}
QToolButton:disabled {{ color: {c['faint']}; }}

/* Eingabefelder */
QComboBox, QLineEdit, QSpinBox {{ background: rgba(0,0,0,0.38); border: 1px solid rgba(125,211,252,0.30); border-radius: 8px; padding: 3px 9px; min-height: 18px; selection-background-color: {c['select']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c['cyan']}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid rgba(0,229,255,0.45); selection-background-color: {c['select']}; outline: 0; }}
QPushButton {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(125,211,252,0.35); border-radius: 8px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {c['cyan']}; background: {c['hover']}; }}
QPushButton:pressed {{ background: {grad}; }}
QPushButton:disabled {{ color: {c['faint']}; border-color: rgba(125,211,252,0.15); }}
QPushButton#primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00e5ff, stop:1 #b44cff); border: none; color: #05060f; font-weight: 600; }}
QPushButton#primary:disabled {{ background: rgba(255,255,255,0.08); color: {c['faint']}; }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid rgba(125,211,252,0.5); border-radius: 4px; background: rgba(0,0,0,0.35); }}
QCheckBox::indicator:checked {{ background: {c['cyan']}; border-color: {c['cyan']}; image: url({check}); }}

/* Docks */
QDockWidget {{ color: {c['fg']}; }}
QDockWidget::title {{ background: rgba(0,229,255,0.07); padding: 6px 12px; border-bottom: 1px solid rgba(0,229,255,0.30); letter-spacing: 1px; }}
QDockWidget[active="true"]::title {{ background: {grad}; border-bottom: 1px solid {c['cyan']}; color: #fff; }}

/* Listen, Bäume, Tabellen */
QTreeView, QListView, QTableView, QTableWidget, QTreeWidget, QListWidget {{ background: {c['panel']}; border: 0; outline: 0; alternate-background-color: {c['panel']}; }}
QTreeView::item, QListView::item {{ height: 24px; border-radius: 6px; margin: 0 4px; }}
QTreeView::item:hover, QListView::item:hover, QListWidget::item:hover {{ background: {c['hover']}; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected, QListWidget::item:selected {{ background: {grad}; color: #fff; }}
QTreeView::item:selected:!active {{ background: rgba(0,229,255,0.14); }}
QTableView::item:selected {{ border-radius: 0; }}
QHeaderView::section {{ background: rgba(0,229,255,0.06); color: {c['dim']}; border: 0; border-bottom: 1px solid {c['border']}; padding: 4px 10px; letter-spacing: 1px; }}
QTableView {{ gridline-color: rgba(27,39,72,0.7); }}

/* Tabs (Dokumente oben, Tool-Fenster unten) */
QTabWidget::pane {{ border: 0; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {c['dim']}; padding: 7px 14px; margin-right: 2px; border-top-left-radius: 8px; border-top-right-radius: 8px; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ background: {c['hover']}; color: #fff; }}
QTabBar::tab:selected {{ background: rgba(0,229,255,0.10); color: #fff; border-bottom: 2px solid {c['cyan']}; }}
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
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {c['editor']}; color: #d7e3ff; border: 0; selection-background-color: rgba(0,229,255,0.30); }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {c['panel']}; color: {c['fg']}; border: 1px solid {c['cyan']}; padding: 4px 8px; border-radius: 6px; }}

/* Scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: rgba(125,211,252,0.30); border-radius: 4px; min-height: 28px; min-width: 28px; margin: 2px; }}
QScrollBar::handle:hover {{ background: rgba(0,229,255,0.65); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: 0; height: 0; width: 0; }}
QProgressBar {{ background: rgba(255,255,255,0.08); border: 0; border-radius: 3px; text-align: center; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00e5ff, stop:1 #b44cff); border-radius: 3px; }}
QLabel#sub {{ color: {c['dim']}; }}
"""
