"""Start-Seite: zuletzt geöffnete Projekte, Schnellaktionen und Einstieg – erscheint beim Start und über Datei → Startseite."""
import json
import time
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget)

from .. import __version__
from ..branding import APP_NAME, SETTINGS_APP, SETTINGS_ORG
from ..theme import C

MAX_RECENT = 12
KEY = "recent/projects"


def project_kind(path: Path) -> tuple:
    """(Anzeigename, Schlüssel für das Abzeichen) – grobe Erkennung des Projekttyps anhand typischer Dateien."""
    path = Path(path)

    def has(*names):
        return any((path / n).exists() for n in names)
    try:
        deps = {}
        pkg = json.loads((path / "package.json").read_text(encoding="utf-8")) if (path / "package.json").exists() else None
        if pkg:
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    except (OSError, ValueError):
        pkg = None
    if has("artisan") and has("composer.json"):
        return "Laravel", "php"
    from ..web.devserver import _spring_command
    if _spring_command(path):
        return "Spring Boot", "java"
    if has("angular.json") or "@angular/core" in deps:
        return "Angular", "typescript"
    if "nuxt" in deps:
        return "Nuxt", "vue"
    if "next" in deps:
        return "Next.js", "typescript"
    if "vue" in deps:
        return "Vue", "vue"
    if "react" in deps:
        return "React", "typescript"
    if pkg is not None:
        return "Node.js", "javascript"
    if has("composer.json") or any(path.glob("*.php")):
        return "PHP", "php"
    if has("Cargo.toml"):
        return "Rust", "rust"
    if has("go.mod"):
        return "Go", "go"
    if any(path.glob("*.csproj")) or any(path.glob("*.sln")):
        return ".NET", "csharp"
    if has("pom.xml", "build.gradle", "build.gradle.kts") or any(path.glob("*.java")):
        return "Java", "java"
    if has("CMakeLists.txt", "Makefile") or any(path.glob("*.c")) or any(path.glob("*.cpp")) or any(path.glob("*.pro")) or any(path.glob("*.vcxproj")):
        return "C/C++", "cpp"
    if has("pyproject.toml", "requirements.txt", "setup.py") or any(path.glob("*.py")):
        return "Python", "python"
    return "Ordner", ""


# --- Liste der zuletzt geöffneten Projekte ------------------------------------------------------------------
def load_recent() -> list:
    """[{path, name, opened}] – neueste zuerst; verschwundene Ordner werden aussortiert."""
    raw = QSettings(SETTINGS_ORG, SETTINGS_APP).value(KEY, "[]")
    try:
        items = json.loads(raw) if isinstance(raw, str) else []
    except ValueError:
        items = []
    return [i for i in items if isinstance(i, dict) and Path(i.get("path", "")).is_dir()][:MAX_RECENT]


def save_recent(items: list):
    s = QSettings(SETTINGS_ORG, SETTINGS_APP)
    s.setValue(KEY, json.dumps(items[:MAX_RECENT], ensure_ascii=False))
    s.sync()


def remember(path: Path) -> list:
    path = Path(path).resolve()
    items = [i for i in load_recent() if Path(i["path"]).resolve() != path]
    items.insert(0, {"path": str(path), "name": path.name, "opened": int(time.time())})
    save_recent(items)
    return items[:MAX_RECENT]


def forget(path: str) -> list:
    items = [i for i in load_recent() if i["path"] != str(path)]
    save_recent(items)
    return items


def ago(ts: int) -> str:
    d = max(0, int(time.time()) - int(ts))
    if d < 90:
        return "gerade eben"
    if d < 3600:
        return f"vor {d // 60} Min."
    if d < 86400:
        return f"vor {d // 3600} Std."
    if d < 86400 * 14:
        return f"vor {d // 86400} Tagen"
    return time.strftime("%d.%m.%Y", time.localtime(ts))


class StartPage(QWidget):
    openProject = Signal(str)
    newProject = Signal()
    openFolder = Signal()
    newForm = Signal()
    openPreview = Signal()
    openOptions = Signal()
    checkTools = Signal()
    openHelp = Signal()
    showOnStartChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("startpage")
        head = QLabel(f"<span style='font-size:30px; font-weight:300; color:{C['cyan']}'>Visual</span> "
                      f"<span style='font-size:30px; font-weight:600'>Death Studio</span>")
        sub = QLabel(f"{__version__}   ·   2026 by Peter Päffgen"); sub.setObjectName("sub")
        # links: zuletzt geöffnet
        self.recent = QListWidget(); self.recent.setIconSize(QSize(32, 32)); self.recent.setSpacing(2)
        self.recent.setContextMenuPolicy(Qt.CustomContextMenu)
        self.recent.itemActivated.connect(self._open_item)
        self.recent.customContextMenuRequested.connect(self._menu)
        self.empty = QLabel("Noch keine Projekte geöffnet – lege ein neues an oder öffne einen Ordner.")
        self.empty.setObjectName("sub"); self.empty.setWordWrap(True)
        left = QVBoxLayout()
        left.addWidget(self._title("Zuletzt geöffnet")); left.addWidget(self.recent, 1); left.addWidget(self.empty)
        # rechts: Starten
        right = QVBoxLayout(); right.setSpacing(8)
        right.addWidget(self._title("Loslegen"))
        self.buttons = {}
        for key, text, sig in (("new", "＋  Neues Projekt …", self.newProject), ("open", "▸  Ordner öffnen …", self.openFolder),
                               ("form", "▣  Neues Formular im Designer …", self.newForm), ("web", "◉  Web-Vorschau öffnen", self.openPreview)):
            b = QPushButton(text); b.setMinimumHeight(38); b.setStyleSheet("text-align:left; padding-left:16px;")
            b.clicked.connect(lambda _=False, s=sig: s.emit()); right.addWidget(b); self.buttons[key] = b
        self.buttons["new"].setObjectName("primary")
        right.addSpacing(10); right.addWidget(self._title("Mehr"))
        for text, sig in (("Optionen …", self.openOptions), ("Installierte Werkzeuge prüfen …", self.checkTools), ("Erste Schritte und Hilfe", self.openHelp)):
            b = QPushButton(text); b.setFlat(True); b.setCursor(Qt.PointingHandCursor); b.setStyleSheet("text-align:left; border:0; color:" + C["cyan"])
            b.clicked.connect(lambda _=False, s=sig: s.emit()); right.addWidget(b)
        right.addStretch()
        self.show_on_start = QCheckBox("Startseite beim Start anzeigen"); self.show_on_start.setChecked(True)
        self.show_on_start.toggled.connect(self.showOnStartChanged)
        right.addWidget(self.show_on_start)
        cols = QHBoxLayout(); cols.setSpacing(36); cols.addLayout(left, 3); cols.addLayout(right, 2)
        card = QFrame(); card.setObjectName("card"); cl = QVBoxLayout(card); cl.setContentsMargins(32, 28, 32, 24); cl.setSpacing(14)
        cl.addWidget(head); cl.addWidget(sub); cl.addSpacing(10); cl.addLayout(cols, 1)
        outer = QHBoxLayout(self); outer.setContentsMargins(40, 30, 40, 30)
        outer.addWidget(card)
        card.setMaximumWidth(1000)
        self.setStyleSheet(f"QFrame#card {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 16px; }}")
        self.refresh()

    @staticmethod
    def _title(text: str) -> QLabel:
        lab = QLabel(text.upper()); lab.setStyleSheet(f"color:{C['dim']}; letter-spacing:2px; font-size:11px;")
        return lab

    def refresh(self):
        from ..projects.wizard import badge
        self.recent.clear()
        for i in load_recent():
            kind, lang = project_kind(Path(i["path"]))
            it = QListWidgetItem(QIcon(badge(lang, 32)), f"{i['name']}   ·   {kind}\n{i['path']}   ·   {ago(i.get('opened', 0))}")
            it.setData(Qt.UserRole, i["path"]); it.setSizeHint(QSize(0, 50))
            it.setToolTip(i["path"])
            self.recent.addItem(it)
        self.empty.setVisible(self.recent.count() == 0)
        if self.recent.count():
            self.recent.setCurrentRow(0)

    def _open_item(self, it):
        self.openProject.emit(it.data(Qt.UserRole))

    def _menu(self, pos):
        it = self.recent.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        m.addAction("Öffnen", lambda: self._open_item(it))
        m.addAction("Aus der Liste entfernen", lambda: (forget(it.data(Qt.UserRole)), self.refresh()))
        m.exec(self.recent.mapToGlobal(pos))
