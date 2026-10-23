"""Hauptfenster: Menüleiste, Toolbar, Docks und Statusleiste im Stil von Visual Studio 2022."""
import re
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QTabWidget, QToolBar, QToolButton, QWidget, QSizePolicy)

from .branding import APP_NAME, DESKTOP_ID, SETTINGS_APP, SETTINGS_ORG, app_icon, desktop_entry_exists, install_desktop_entry
from .build.languages import LANGS, lang_for, parse_problems
from .build.runner import Runner
from .docks.explorer import Explorer
from .designer import codegen
from .diff import changes as gitc
from .diff.view import DiffView
from .docks.changes import ChangesPanel, DiffRequest
from .debug.controller import DebugController
from .ai.completion import MODELS, AiCompletion
from .lsp.manager import LspManager
from .project import ProjectSettings
from .docks.references import ReferencesPanel
from . import refactor
from .docks.chat import ChatPanel
from .docks.debug_panels import CallStackPanel, ImmediatePanel, VariablesTree, WatchPanel
from .docks.output import ErrorList, OutputPane
from .docks.tests import TestExplorer
from .testing.service import TestService
from .docks.packages import PackagePanel
from .docks.props import PropertiesDock
from .docks.terminal import TerminalWidget
from .docks.tools import Breakpoints, Toolbox
from .editor import code_editor
from .editor.code_editor import set_default_font
from .editor.documents import FORM_SUFFIX, Documents
from .icons import icon
from .theme import C, apply_palette, stylesheet

# Import-Name -> PyPI-Paketname, wo beide abweichen
PIP_NAMES = {"cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml", "sklearn": "scikit-learn", "bs4": "beautifulsoup4",
             "dateutil": "python-dateutil", "serial": "pyserial", "Crypto": "pycryptodome", "dotenv": "python-dotenv",
             "skimage": "scikit-image", "attr": "attrs", "OpenSSL": "pyopenssl", "jwt": "pyjwt", "git": "gitpython", "usb": "pyusb"}

LAYOUT_VERSION = 5   # erhöhen, wenn sich das Dock-Layout ändert (verwirft gespeicherte Zustände)
ROOT = Path(__file__).resolve().parent.parent
SAMPLES = {
    "hello.py": 'def greet(name: str) -> str:\n    return f"Hallo, {name}!"\n\n\nif __name__ == "__main__":\n    print(greet("Visual Death Studio"))\n',
    "hello.c": '#include <stdio.h>\n\nint main(void) {\n    printf("Hallo aus C!\\n");\n    return 0;\n}\n',
    "hello.cpp": '#include <iostream>\n\nint main() {\n    std::cout << "Hallo aus C++!" << std::endl;\n}\n',
    "hello.js": 'console.log("Hallo aus Node.js!");\n',
    "hello.rs": 'fn main() {\n    println!("Hallo aus Rust!");\n}\n',
    "hello.go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hallo aus Go!")\n}\n',
    "Program.cs": 'Console.WriteLine("Hallo aus C#!");\n',
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.setWindowTitle("Visual Death Studio")
        self.resize(1500, 900)
        ef = self.settings.value("editor_font")
        if ef:
            f = QFont(); f.fromString(str(ef)); set_default_font(f)
        saved = self.settings.value("root")
        self.root = Path(saved) if saved and Path(saved).is_dir() else ROOT / "workspace"
        self.root.mkdir(parents=True, exist_ok=True)
        if not any(self.root.iterdir()) and self.root == ROOT / "workspace":
            for n, t in SAMPLES.items():
                (self.root / n).write_text(t, encoding="utf-8")
        self._marked = None
        self.runner = Runner(self.root / ".vds" / "bin", self)
        self.startup: Path | None = None

        self.lsp = LspManager(self)
        self.project = ProjectSettings()
        self.tests = TestService(self)
        self.ai = AiCompletion(self)
        self.docs = Documents()
        self.docs.intel = self.lsp
        self.setCentralWidget(self.docs)
        self._build_docks()
        self.dbg = DebugController(self, dict(locals=self.p_locals, watch=self.p_watch, stack=self.p_stack, immediate=self.p_imm))
        self._after_build = None
        self._lsp_status: dict = {}
        self._start_text = " Starten"
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status()
        self._wire()
        self.set_root(self.root)
        self._restore_session()
        self.restoreGeometry(self.settings.value("geometry") or b"")
        if self.settings.value("state") and self.settings.value("layout_version") == LAYOUT_VERSION:
            self.restoreState(self.settings.value("state"))

    # --- Aufbau -----------------------------------------------------------------
    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setProperty("active", False)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.explorer, self.props, self.toolbox = Explorer(), PropertiesDock(), Toolbox()
        self.chat = ChatPanel()
        self.changes = ChangesPanel()
        self.packages = PackagePanel()
        self.output, self.errors, self.bps = OutputPane(), ErrorList(), Breakpoints()
        self.terminal = TerminalWidget(self.root)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.setTabPosition(Qt.BottomDockWidgetArea, QTabWidget.South)
        L, R, B = Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea, Qt.BottomDockWidgetArea
        self.setTabPosition(Qt.LeftDockWidgetArea, QTabWidget.South)
        self.d_explorer = self._dock("Projektmappen-Explorer", self.explorer, L, "explorer")
        self.d_toolbox = self._dock("Toolbox", self.toolbox, L, "toolbox")
        self.d_changes = self._dock("Änderungen", self.changes, L, "changes")
        self.d_chat = self._dock("Claude", self.chat, R, "chat")
        self.d_props = self._dock("Eigenschaften", self.props, R, "props")
        self.splitDockWidget(self.d_chat, self.d_props, Qt.Vertical)
        self.tabifyDockWidget(self.d_explorer, self.d_toolbox)
        self.tabifyDockWidget(self.d_explorer, self.d_changes)
        self.d_explorer.raise_()
        self.d_output = self._dock("Ausgabe", self.output, B, "output")
        self.d_errors = self._dock("Fehlerliste", self.errors, B, "errors")
        self.d_terminal = self._dock("Terminal", self.terminal, B, "terminal")
        self.d_bps = self._dock("Haltepunkte", self.bps, B, "bps")
        self.d_packages = self._dock("Pakete", self.packages, B, "packages")
        self.p_locals, self.p_watch, self.p_stack, self.p_imm = VariablesTree(), WatchPanel(), CallStackPanel(), ImmediatePanel()
        self.p_tests = TestExplorer(self.tests)
        self.p_refs = ReferencesPanel()
        self.d_refs = self._dock("Verweise", self.p_refs, B, "refs")
        self.d_tests = self._dock("Tests", self.p_tests, B, "tests")
        self.d_locals = self._dock("Lokal", self.p_locals, B, "locals")
        self.d_watch = self._dock("Überwachung", self.p_watch, B, "watch")
        self.d_stack = self._dock("Aufrufliste", self.p_stack, B, "stack")
        self.d_imm = self._dock("Direktfenster", self.p_imm, B, "immediate")
        for d in (self.d_errors, self.d_terminal, self.d_bps, self.d_packages, self.d_tests, self.d_refs, self.d_locals, self.d_watch, self.d_stack, self.d_imm):
            self.tabifyDockWidget(self.d_output, d)
        self.d_output.raise_()
        self.resizeDocks([self.d_explorer], [280], Qt.Horizontal)
        self.resizeDocks([self.d_chat], [360], Qt.Horizontal)
        self.resizeDocks([self.d_chat, self.d_props], [520, 260], Qt.Vertical)
        self.resizeDocks([self.d_output], [230], Qt.Vertical)
        self.all_docks = [self.d_refs, self.d_tests, self.d_locals, self.d_watch, self.d_stack, self.d_imm, self.d_packages, self.d_chat, self.d_changes, self.d_toolbox, self.d_explorer, self.d_props, self.d_output, self.d_errors, self.d_terminal, self.d_bps]
        QApplication.instance().focusChanged.connect(self._focus_changed)

    def _focus_changed(self, _old, new):
        for d in self.all_docks:
            active = bool(new) and d.isAncestorOf(new)
            if d.property("active") != active:
                d.setProperty("active", active)
                d.style().unpolish(d); d.style().polish(d)

    def _act(self, text, slot, shortcut=None, ico=None, color="#c8d6f5"):
        a = QAction(icon(ico, color) if ico else QAction().icon(), text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ApplicationShortcut)
        a.triggered.connect(lambda _=False: slot())
        return a

    def _ed(self):
        """Aktiver Code-Editor (None bei Designer/ohne Dokument)."""
        d = self.docs.current_doc()
        return d.editor if d else None

    def _ed_call(self, name):
        """Bearbeiten-Befehle gelten für Code-Editor und Designer gleichermaßen."""
        def call():
            d = self.docs.current_doc()
            if d:
                fn = getattr(d.view, name, None)
                fn and fn()
        return call

    def _build_actions(self):
        A = self._act
        self.a = dict(
            new=A("Datei…", self.explorer.new_file, "Ctrl+N", "file"),
            newform=A("Formular…", self.new_form, "Ctrl+Shift+A", "file"),
            newproject=A("Projekt…", self.new_project, "Ctrl+Shift+N", "solution", "#b44cff"),
            viewcode=A("Code anzeigen", self.view_code, "F7"), viewdesigner=A("Designer anzeigen", self.view_designer, "Shift+F7"),
            openfolder=A("Ordner öffnen…", self.open_folder, "Ctrl+Shift+O", "folder"),
            save=A("Speichern", self.save, "Ctrl+S", "save"),
            saveall=A("Alle speichern", self.save_all, "Ctrl+Shift+S", "save"),
            close=A("Schließen", lambda: self.docs.count() and self.docs.close_tab(self.docs.currentIndex()), "Ctrl+F4"),
            exit=A("Beenden", self.close, "Alt+F4"),
            undo=A("Rückgängig", self._ed_call("undo"), "Ctrl+Z", "undo"), redo=A("Wiederholen", self._ed_call("redo"), "Ctrl+Y", "redo"),
            cut=A("Ausschneiden", self._ed_call("cut"), "Ctrl+X"), copy=A("Kopieren", self._ed_call("copy"), "Ctrl+C"),
            paste=A("Einfügen", self._ed_call("paste"), "Ctrl+V"), selall=A("Alles auswählen", self._ed_call("selectAll"), "Ctrl+A"),
            find=A("Suchen…", self.find, "Ctrl+F"), goto=A("Gehe zu Zeile…", self.goto_line, "Ctrl+G"),
            comment=A("Auswahl auskommentieren", self.toggle_comment, "Ctrl+K"),
            gotodef=A("Gehe zu Definition", self.goto_definition, "F12"),
            rename=A("Umbenennen…", self.rename_symbol, "F2"),
            findrefs=A("Alle Verweise suchen", self.find_references, "Shift+F12"),
            fmtdoc=A("Dokument formatieren", self.format_document, "Ctrl+Alt+F"),
            quickact=A("Schnelle Aktionen und Refactorings…", self.quick_actions, "Ctrl+."),
            aicomplete=A("Claude-Vervollständigung (Strg+Enter)", self.ai_complete),
            aimodel=A("Claude-Modell für Vervollständigung…", self.pick_ai_model),
            build=A("Projektmappe erstellen", lambda: self.run("build"), "Ctrl+Shift+B", "build"),
            clean=A("Projektmappe bereinigen", self.clean),
            start=A("Debugging starten", self.dbg.start, "F5", "play", C["green"]),
            startnd=A("Starten ohne Debugging", lambda: self.run("buildrun"), "Ctrl+F5", "play-outline", C["green"]),
            stop=A("Debugging beenden", self.stop_any, "Shift+F5", "stop", C["red"]),
            dpause=A("Alle unterbrechen", self.dbg.pause, "Ctrl+Alt+Pause", "pause", C["warn"]),
            drestart=A("Neu starten", self.dbg.restart, "Ctrl+Shift+F5", "restart", C["green"]),
            stepin=A("Einzelschritt", self.dbg.step_in, "F11", "step-in", C["info"]),
            stepover=A("Prozedurschritt", self.dbg.step_over, "F10", "step-over", C["info"]),
            stepout=A("Ausführen bis Rücksprung", self.dbg.step_out, "Shift+F11", "step-out", C["info"]),
            togglebp=A("Haltepunkt umschalten", self.dbg.toggle_here, "F9"),
            clearbp=A("Alle Haltepunkte löschen", self.dbg.clear_all, "Ctrl+Shift+F9"),
            testexp=A("Test-Explorer", self.open_tests, "Ctrl+E, T"),
            testall=A("Alle Tests ausführen", lambda: self._tests_run(None), "Ctrl+R, A", "t-run", C["info"]),
            testfailed=A("Fehlgeschlagene Tests erneut ausführen", lambda: self.p_tests.run_failed(), "Ctrl+R, F"),
            testdiscover=A("Tests neu entdecken", self.tests.discover),
            testcancel=A("Testlauf abbrechen", self.tests.cancel),
            pkgs=A("Paket-Manager", self.open_packages, "Ctrl+Alt+P"),
            editorfont=A("Editor-Schrift…", self.pick_editor_font),
            cmpfiles=A("Dateien vergleichen…", self.compare_files),
            cmpsaved=A("Mit gespeicherter Version vergleichen", self.compare_saved),
            cmphead=A("Mit Git-HEAD vergleichen", self.compare_head),
            analyze=A("REA: Ordner analysieren", lambda: self.rea_analyze(str(self.root))),
            askclaude=A("Claude fragen", self.ask_claude, "Ctrl+Shift+L"),
            about=A("Info über Visual Death Studio", self.about),
            reset=A("Fensterlayout zurücksetzen", self.reset_layout),
        )
        self.a["stop"].setEnabled(False)

    def _build_menus(self):
        mb, a = self.menuBar(), self.a
        def menu(title, items):
            m = mb.addMenu(title)
            for it in items:
                if it is None:
                    m.addSeparator()
                elif it == "NEU":
                    sub = m.addMenu("Neu")
                    for x in (a["newproject"], a["new"], a["newform"]):
                        sub.addAction(x)
                else:
                    m.addAction(it)
            return m
        menu("&Datei", ["NEU", a["openfolder"], None, a["close"], a["save"], a["saveall"], None, a["exit"]])
        menu("&Bearbeiten", [a["undo"], a["redo"], None, a["cut"], a["copy"], a["paste"], None, a["selall"], None, a["find"], a["goto"], a["gotodef"], a["findrefs"], None, a["rename"], a["quickact"], a["fmtdoc"], a["comment"], None, a["aicomplete"]])
        v = menu("&Ansicht", [])
        for d in self.all_docks:
            v.addAction(d.toggleViewAction())
        v.addSeparator()
        v.addAction(a["viewcode"]); v.addAction(a["viewdesigner"])
        v.addSeparator()
        v.addAction(a["reset"])
        menu("&Projekt", [a["newproject"], a["new"], a["newform"], None, a["analyze"]])
        menu("&Erstellen", [a["build"], a["clean"]])
        menu("&Test", [a["testexp"], None, a["testall"], a["testfailed"], a["testdiscover"], a["testcancel"]])
        menu("&Debuggen", [a["start"], a["startnd"], a["dpause"], a["stop"], a["drestart"], None, a["stepin"], a["stepover"], a["stepout"], None, a["togglebp"], a["clearbp"]])
        t = menu("E&xtras", [])
        t.addAction(a["pkgs"])
        t.addAction(a["editorfont"])
        t.addAction(a["askclaude"])
        t.addAction(a["aimodel"])
        t.addSeparator()
        for x in (a["cmpfiles"], a["cmpsaved"], a["cmphead"]):
            t.addAction(x)
        t.addSeparator()
        t.addAction(self._act("Terminal öffnen", lambda: (self.d_terminal.show(), self.d_terminal.raise_())))
        menu("&Fenster", [a["reset"]])
        menu("&Hilfe", [a["about"]])

    def _build_toolbar(self):
        tb = QToolBar("Standard", self)
        tb.setObjectName("toolbar"); tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(tb)
        a = self.a
        for x in (a["new"], a["save"], a["saveall"]):
            tb.addAction(x)
        tb.addSeparator()
        tb.addAction(a["undo"]); tb.addAction(a["redo"])
        tb.addSeparator()
        self.cfg = QComboBox(); self.cfg.addItems(["Debug", "Release"])
        self.plat = QComboBox(); self.plat.addItems(["Any CPU", "x64", "x86"])
        tb.addWidget(self.cfg); tb.addWidget(self.plat)
        self.start_btn = QToolButton()
        self.start_btn.setDefaultAction(a["start"])
        self.start_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.addWidget(self.start_btn)
        tb.addAction(a["startnd"]); tb.addAction(a["stop"]); tb.addAction(a["build"])
        tb.addSeparator()
        for k in ("dpause", "drestart", "stepin", "stepover", "stepout"):
            tb.addAction(a[k]); a[k].setVisible(False); a[k].setEnabled(False)

    def _build_status(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.st_state = QLabel("Bereit")
        self.st_lsp = QLabel("")
        self.st_pos, self.st_lang = QLabel("Z: 1  Zch: 1"), QLabel("Nur Text")
        sb.addWidget(self.st_state, 1)
        for w in (self.st_lsp, self.st_pos, self.st_lang, QLabel("UTF-8"), QLabel("LF")):
            sb.addPermanentWidget(w)

    # --- Verdrahtung -------------------------------------------------------------
    def _wire(self):
        e = self.explorer
        e.fileOpened.connect(lambda p: self._open_file(Path(p)))
        e.selectionPath.connect(self._explorer_selected)
        self.docs.docOpened.connect(lambda d: d.kind == "form" and d.view.eventRequested.connect(lambda cid, d=d: self._open_handler(d, cid)))
        e.fileDeleted.connect(lambda p: self.docs.close_path(Path(p)))
        e.fileRenamed.connect(lambda old, new: (self.docs.close_path(Path(old)), Path(new).is_file() and self.docs.open(Path(new))))
        e.analyzeRequested.connect(self.rea_analyze)
        e.markForCompare.connect(lambda p: setattr(self, "_marked", p) or self.statusBar().showMessage(f"Zum Vergleichen ausgewählt: {Path(p).name}", 4000))
        e.compareWithMarked.connect(self.compare_with_marked)
        self.changes.diffRequested.connect(self.show_diff)
        self.packages.filesChanged.connect(self.docs.reload_changed)
        self.changes.filesChanged.connect(self.docs.reload_changed)
        self.changes.pendingChanged.connect(lambda n: self.d_changes.setWindowTitle(f"Änderungen ({n} von Claude)" if n else "Änderungen"))
        self.docs.currentDocChanged.connect(self._doc_changed)
        self.docs.cursorInfo.connect(lambda l, c: self.st_pos.setText(f"Z: {l}  Zch: {c}"))
        self.docs.breakpointsChanged.connect(lambda: (self.bps.update_list(self.docs.all_breakpoints()), self.dbg.breakpoints_changed()))
        self.docs.docOpened.connect(self.dbg.apply_saved)
        self.bps.toggled.connect(lambda path, line, on: self._bp_edit(path, line, enabled=on))
        self.bps.removed.connect(lambda path, line: self._bp_edit(path, line, remove=True))
        self.dbg.stateChanged.connect(self._dbg_state)
        self.p_tests.jumpTo.connect(lambda p, l: self.goto(p, l, 1))
        self.p_tests.debugRequested.connect(lambda fw, ids: self.dbg.debug_test(fw, ids, self.root))
        self.tests.log.connect(lambda t: self.output.append(t, "info"))
        self.docs.docOpened.connect(self._code_opened)
        self.docs.docClosed.connect(lambda d: d.kind == "code" and self.lsp.detach(d.path))
        self.docs.saved.connect(lambda d: d.kind == "code" and self.lsp.did_save(d.path))
        self.lsp.diagnostics.connect(self._lsp_diagnostics)
        self.lsp.editRequested.connect(lambda edits, label: self._apply_refactor(edits, label, preview=len(edits) > 1))
        self.p_refs.activated.connect(lambda path, line, col: self.goto(path, line, col))
        self.lsp.statusChanged.connect(lambda lang, text: self._lsp_status.__setitem__(lang, text) or self._update_lsp_label())
        self.docs.currentDocChanged.connect(lambda _d: self._update_lsp_label())
        self.bps.activated.connect(lambda p, l: self.goto(p, l, 1))
        self.errors.activated.connect(self.goto)
        self.errors.countChanged.connect(lambda e_, w: self.d_errors.setWindowTitle(f"Fehlerliste ({e_} Fehler, {w} Warnungen)"))
        self.toolbox.insertSnippet.connect(lambda t: self._ed() and self._ed().insertPlainText(t))
        self.toolbox.controlActivated.connect(self._add_control)
        self.runner.output.connect(self.output.append)
        self.runner.busyChanged.connect(self._busy)
        self.runner.finished.connect(self._run_finished)
        self.output.inputSubmitted.connect(self._stdin)
        self.chat.active_file = self._chat_context
        self.chat.runStarting.connect(self.changes.begin_claude_run)
        self.chat.filesChanged.connect(self._claude_done)
        self.chat.busyChanged.connect(lambda b: self.st_state.setText("Claude arbeitet …" if b else "Bereit"))

    # --- Diff ---------------------------------------------------------------------------
    def _claude_done(self):
        self.docs.reload_changed()
        self.changes.end_claude_run()
        if self.changes.claude_changes:
            self.d_changes.show(); self.d_changes.raise_()
            self.statusBar().showMessage(f"Claude hat {len(self.changes.claude_changes)} Datei(en) geändert – siehe Änderungen.", 6000)

    def _write_disk(self, path: Path, text: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.docs.reload_changed()
        self.changes.refresh_claude()
        self.changes.refresh_git()

    def show_diff(self, req: DiffRequest):
        """Öffnet (oder aktualisiert) einen Diff-Tab. Veränderbare Seiten schreiben direkt in die Datei bzw. den Editor."""
        la = req.left_apply or (req.left_path and (lambda t, p=req.left_path: self._write_disk(Path(p), t)))
        ra = req.right_apply or (req.right_path and (lambda t, p=req.right_path: self._write_disk(Path(p), t)))
        view = self.docs.find_diff(req.key)
        if view is None:
            view = DiffView()
            self.docs.add_diff(req.key, req.title, view)
        else:
            self.docs.setCurrentWidget(view)
        view.set_sources(req.left, req.right, req.ltitle, req.rtitle, req.filename, la or None, ra or None)

    def compare_files(self):
        start = str(self.root)
        a, _ = QFileDialog.getOpenFileName(self, "Linke Datei wählen", start)
        if not a:
            return
        b, _ = QFileDialog.getOpenFileName(self, "Rechte Datei wählen", str(Path(a).parent))
        if b:
            self._compare_paths(Path(a), Path(b))

    def compare_with_marked(self, path):
        if not self._marked:
            return self.statusBar().showMessage("Zuerst eine Datei „Zum Vergleichen auswählen“.", 4000)
        self._compare_paths(Path(self._marked), Path(path))

    def _compare_paths(self, a: Path, b: Path):
        ta, tb = gitc.read_text(a), gitc.read_text(b)
        if ta is None or tb is None:
            return QMessageBox.information(self, "Vergleichen", "Nur Textdateien (unter 1 MB) lassen sich vergleichen.")
        self.show_diff(DiffRequest(f"cmp:{a}|{b}", f"{a.name} ↔ {b.name}", ta, tb, str(a), str(b), b.name, left_path=a, right_path=b))

    def compare_saved(self):
        d = self.docs.current_doc()
        if not d or d.kind != "code":
            return
        if not d.modified:
            return self.statusBar().showMessage("Keine ungespeicherten Änderungen.", 3000)
        disk = gitc.read_text(d.path) or ""
        req = DiffRequest(f"saved:{d.path}", f"{d.path.name} (ungespeichert)", disk, d.view.toPlainText(), "Gespeichert", "Editor", d.path.name)
        req.right_apply = lambda t, v=d.view: v.setPlainText(t)
        self.show_diff(req)

    def compare_head(self):
        d = self.docs.current_doc()
        if not d or d.kind != "code":
            return
        top = gitc.toplevel(d.path.parent)
        if not top:
            return self.statusBar().showMessage("Die Datei liegt in keinem Git-Repository.", 4000)
        rel = d.path.resolve().relative_to(top.resolve()).as_posix()
        req = DiffRequest(f"head:{d.path}", f"{d.path.name} (HEAD)", gitc.head_text(top, rel), d.view.toPlainText(), "HEAD", "Editor", d.path.name)
        req.right_apply = lambda t, v=d.view: v.setPlainText(t)
        self.show_diff(req)

    def pick_editor_font(self):
        from .ui.font_dialog import FontDialog
        ed = self._ed()
        cur = ed.font() if ed else (code_editor.DEFAULT_FONT or QFont("monospace", 11))
        f = FontDialog.get_font(cur, self, True, "Editor-Schrift")
        if f is None:
            return
        set_default_font(f)
        self.settings.setValue("editor_font", f.toString())
        for d in self.docs.docs.values():
            if d.kind == "code":
                d.view.refresh_font(f)
        self.statusBar().showMessage(f"Editor-Schrift: {f.family()}, {f.pointSize()} pt", 4000)

    def open_tests(self):
        self.d_tests.show(); self.d_tests.raise_()

    def _tests_run(self, ids):
        self.open_tests()
        self.tests.run(ids)

    def open_packages(self):
        self.d_packages.show(); self.d_packages.raise_()
        self.packages.search.setFocus()

    def _chat_context(self):
        d = self.docs.current_doc()
        if not d:
            return None, ""
        sel = d.view.textCursor().selectedText().replace("\u2029", "\n") if d.kind == "code" else ""
        return d.path, sel

    def ask_claude(self):
        self.d_chat.show(); self.d_chat.raise_()
        self.chat.input.setFocus()

    def _explorer_selected(self, path):
        d = self.docs.current_doc()
        if d is None or d.kind != "form":
            self.props.show_file(path)

    def set_root(self, path: Path):
        self.root = path
        self.dbg.store = {}
        self.project = ProjectSettings.load(path)
        self.runner.project, self.runner.root = self.project, path
        self.tests.set_root(path, self.runner.interpreter(path / "x.py"))
        QTimer.singleShot(1500, self.tests.discover)
        self.explorer.set_root(path)
        self.d_explorer.setWindowTitle(f"Projektmappen-Explorer – {path.name}")
        self.runner.build_dir = path / ".vds" / "bin"
        self.chat.set_root(path)
        self.lsp.set_root(path)
        self.ai.root = path
        self.changes.set_root(path)
        self.packages.set_root(path)
        self.statusBar().setStyleSheet("")

    def open_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Ordner öffnen", str(self.root))
        if p:
            self._save_session()
            if self.docs.close_all():
                self.set_root(Path(p))
                self._restore_session()

    # --- Öffnen / Sitzung -------------------------------------------------------------------
    def _open_file(self, path: Path):
        """Wie in Visual Studio: Gehört zu Form1.py ein Formular (Form1.form.json), öffnet der Doppelklick den Designer.
        Den Code zeigt F7 (Ansicht → Code anzeigen)."""
        form = path.with_name(path.stem + FORM_SUFFIX)
        if path.suffix == ".py" and form.is_file():
            return self.docs.open(form)
        return self.docs.open(path)

    def _session_key(self) -> str:
        import hashlib
        return "session/" + hashlib.md5(str(self.root).encode()).hexdigest()

    def _save_session(self):
        """Merkt sich die geöffneten Tabs (in Tab-Reihenfolge) und den aktiven Tab pro Projektordner."""
        by_view = {d.view: d for d in self.docs.docs.values() if d.kind != "diff"}
        files = [str(by_view[w].path) for w in (self.docs.widget(i) for i in range(self.docs.count())) if w in by_view]
        cur = self.docs.current_doc()
        k = self._session_key()
        self.settings.setValue(k + "/files", files)
        self.settings.setValue(k + "/current", str(cur.path) if cur and cur.kind != "diff" else "")
        self.dbg.save(self.settings, k + "/bps")

    def _restore_session(self):
        k = self._session_key()
        self.dbg.load(self.settings, k + "/bps")
        files = self.settings.value(k + "/files") or []
        files = [files] if isinstance(files, str) else list(files)
        for f in files:
            if Path(f).is_file():
                self.docs.open(Path(f))
        cur = self.settings.value(k + "/current") or ""
        if cur and Path(cur).resolve() in self.docs.docs:
            self.docs.setCurrentWidget(self.docs.docs[Path(cur).resolve()].view)

    def goto(self, path, line, col):
        d = self.docs.open(Path(path))
        if d and d.editor:
            d.editor.goto(line, col)

    def _doc_changed(self, doc):
        form = doc is not None and doc.kind == "form"
        target = doc.run_target if doc else None
        lang = lang_for(target) if target else None
        if target:
            self.toolbox.set_language(lang.id if lang else None)      # Codeausschnitte passend zur Sprache der aktuellen Datei
        self.st_lang.setText("Formular-Designer" if form else "Vergleich" if doc and doc.kind == "diff" else (lang.name if lang else "Nur Text"))
        self._start_text = f" {target.name}" if target else " Starten"
        self._refresh_run_state()
        self.setWindowTitle(f"{doc.path.name} – Visual Death Studio" if doc else "Visual Death Studio")
        if form:
            self.props.show_designer(doc.view)
            self.d_toolbox.show(); self.d_toolbox.raise_()
        elif doc and doc.kind == "code":
            self.props.show_file(str(doc.path))
        else:
            self.props.show_file(None)

    # --- Aktionen -------------------------------------------------------------------
    def save(self):
        self.docs.save()

    def save_all(self):
        self.docs.save_all()

    def run(self, mode, debug=False, _retry=False):
        doc = self.docs.current_doc()
        if not doc or doc.run_target is None or self.runner.busy:
            return
        self._last_run = (mode, debug)
        if not _retry:
            self._offered = set()      # pro manuellem Start höchstens ein Installationsangebot je Paket
        self.docs.save_all()
        if doc.kind == "form":
            doc.save()   # erzeugt/aktualisiert <Name>_designer.py und legt <Name>.py bei Bedarf an
        self.output.clear()
        self.errors.set_source("build", [])
        self.d_output.show(); self.d_output.raise_()
        self.runner.start(doc.run_target, mode, self.cfg.currentText())

    def _busy(self, busy):
        self._refresh_run_state()

    def stop_any(self):
        self.dbg.stop() if self.dbg.active else self.runner.stop()

    def _stdin(self, text):
        if not self.dbg.write_stdin(text):
            self.runner.write(text)

    def _bp_edit(self, path, line, enabled=None, remove=False):
        d = self.docs.docs.get(Path(path).resolve())
        if not d or d.kind != "code":
            return
        if remove:
            d.editor.toggle_breakpoint(line) if line in d.editor.breakpoints else None
        elif enabled is not None:
            d.editor.set_breakpoint_state(line, d.editor.bp_conditions.get(line, ""), not enabled)

    def _dbg_state(self, st):
        self._refresh_run_state()

    def _refresh_run_state(self):
        """Aktionen, Toolbar und Statusleiste aus Lauf- und Debug-Zustand ableiten."""
        a, st = self.a, self.dbg.state
        dbg_on = st != "idle"
        busy = self.runner.busy
        paused, running = st == "paused", st in ("starting", "running")
        a["start"].setText("Weiter" if paused else "Debugging starten")
        a["start"].setEnabled(paused or (not dbg_on and not busy))
        a["startnd"].setEnabled(not dbg_on and not busy)
        a["stop"].setEnabled(dbg_on or busy)
        for k in ("dpause", "drestart", "stepin", "stepover", "stepout"):
            a[k].setVisible(dbg_on)
        a["dpause"].setEnabled(st == "running")
        a["drestart"].setEnabled(dbg_on)
        for k in ("stepin", "stepover", "stepout"):
            a[k].setEnabled(paused)
        self.start_btn.setText(" Weiter" if paused else self._start_text)
        if paused:
            reason, text = self.dbg.pauseInfo
            names = {"breakpoint": "Haltepunkt", "step": "Schritt", "exception": "Ausnahme", "pause": "Unterbrochen", "entry": "Start"}
            f = self.dbg.session.frame if self.dbg.session else None
            self.st_state.setText(f"Debugging – angehalten ({names.get(reason, reason)}" + (f", Zeile {f.line}" if f else "") + ")")
        elif running:
            self.st_state.setText("Debugger startet …" if st == "starting" else "Debugging – läuft …")
        else:
            self.st_state.setText("Wird ausgeführt…" if busy else "Bereit")
        sb = self.statusBar()
        sb.setProperty("debug", dbg_on); sb.setProperty("busy", busy and not dbg_on)
        sb.style().unpolish(sb); sb.style().polish(sb)

    def _run_finished(self, code, text):
        kind = "ok" if code == 0 else "stderr"
        self.output.append(f"\nVorgang beendet mit Code {code}.\n", kind)
        cur = self.docs.current_doc()
        base = cur.run_target.parent if cur and cur.run_target else self.root
        probs = []
        for sev, msg, f, line, col in parse_problems(text):
            fp = Path(f)
            probs.append((sev, msg, str(fp if fp.is_absolute() else base / fp), line, col))
        self.errors.set_source("build", probs)
        for d in (x for x in self.docs.docs.values() if x.kind == "code"):
            d.editor.set_diagnostics([(s, m, l, c) for s, m, f, l, c in probs if Path(f).resolve() == d.path])
        if any(p[0] == "error" for p in probs):
            self.d_errors.show(); self.d_errors.raise_()
        cb, self._after_build = self._after_build, None
        if cb and code == 0:
            cb()
        m = re.search(r"ModuleNotFoundError: No module named '([\w.]+)'", text) if code != 0 else None
        if m:
            QTimer.singleShot(0, lambda mod=m.group(1).split(".")[0]: self._offer_install(mod))

    def _offer_install(self, mod: str):
        name = PIP_NAMES.get(mod, mod)
        if name in getattr(self, "_offered", set()):
            return
        self._offered = getattr(self, "_offered", set()) | {name}
        if QMessageBox.question(self, "Modul fehlt", f"Das Python-Modul '{mod}' ist nicht installiert.\n\nPaket '{name}' jetzt in der .venv dieses Projekts "
                                f"installieren (wird bei Bedarf angelegt) und danach erneut starten?") != QMessageBox.Yes:
            return
        self.d_packages.show(); self.d_packages.raise_()
        mode, debug = self._last_run
        self.packages.install_module(name, lambda ok: self.run(mode, debug, _retry=True) if ok else
                                     self.statusBar().showMessage(f"Installation von '{name}' fehlgeschlagen – siehe Paket-Protokoll.", 8000))

    # --- IntelliSense -------------------------------------------------------------------------------------
    def _code_opened(self, doc):
        if doc.kind != "code":
            return
        doc.view.datatip = self.dbg.datatip
        doc.view.ai = self.ai
        doc.view.aiStatus.connect(lambda m: self.statusBar().showMessage(m, 8000))
        doc.view.definitionFound.connect(self._open_definition)
        self.lsp.attach(doc)

    def _lsp_diagnostics(self, path: str, items: list):
        doc = self.docs.docs.get(Path(path).resolve()) or self.docs.docs.get(Path(path))
        if doc and doc.kind == "code":
            doc.editor.set_lsp_diagnostics([(s, m, l, c) for s, m, l, c in items])
        self.errors.set_source("lsp:" + path, [(s, m, path, l, c) for s, m, l, c in items])

    def _update_lsp_label(self):
        d = self.docs.current_doc()
        lang = lang_for(d.path) if d and d.kind == "code" else None
        txt = self._lsp_status.get(lang.id) if lang else None
        self.st_lsp.setText(f"IntelliSense: {txt}" if txt else "")

    def ai_complete(self):
        ed = self._ed()
        if ed:
            ed.request_ai()

    def pick_ai_model(self):
        from PySide6.QtWidgets import QInputDialog
        items = list(MODELS.values())
        cur = items[list(MODELS).index(self.ai.model)]
        text, ok = QInputDialog.getItem(self, "Claude-Vervollständigung", "Modell:", items, items.index(cur), False)
        if ok:
            self.ai.set_model(list(MODELS)[items.index(text)])
            self.statusBar().showMessage(f"Modell für die Vervollständigung: {self.ai.model}", 5000)

    # --- Refactoring --------------------------------------------------------------------------------------
    def _symbol(self):
        """(Editor, Wort, Zeile0, Spalte0) unter dem Cursor – nur für Bezeichner."""
        ed = self._ed()
        if not ed or not ed.doc_path:
            return None
        c = ed.textCursor()
        c.select(QTextCursor.WordUnderCursor)
        w = c.selectedText()
        if not re.fullmatch(r"[A-Za-z_]\w*", w):
            self.statusBar().showMessage("Setze den Cursor auf einen Namen.", 3000)
            return None
        return ed, w, c.blockNumber(), c.selectionStart() - c.block().position()

    def _apply_refactor(self, edits: dict, title: str, preview: bool = True):
        if not edits:
            return self.statusBar().showMessage("Keine Änderungen.", 3000)
        rows = refactor.preview_rows(edits)
        if not rows:
            return self.statusBar().showMessage("Keine Änderungen.", 3000)
        if preview:
            dlg = refactor.PreviewDialog(self, title, rows, self.root)
            if not dlg.exec():
                return
            edits = {p: e for p, e in edits.items() if p in set(dlg.selected())}
        done, errors = refactor.apply_edits_to_workspace(self, edits)
        self.docs.reload_changed()
        self.changes.refresh_git()
        msg = f"{title}: {done} Datei(en) geändert."
        self.statusBar().showMessage(msg + (f"  Fehler: {'; '.join(errors)}" if errors else ""), 8000)

    def rename_symbol(self):
        from PySide6.QtWidgets import QInputDialog
        sym = self._symbol()
        if not sym:
            return
        ed, word, line, col = sym
        new, ok = QInputDialog.getText(self, "Umbenennen", f"Neuer Name für „{word}“:", text=word)
        new = new.strip()
        if not ok or not new or new == word:
            return
        if not re.fullmatch(r"[A-Za-z_]\w*", new):
            return self.statusBar().showMessage("Ungültiger Name.", 4000)
        self.docs.save_all()
        path = ed.doc_path
        title = f"„{word}“ → „{new}“"
        if self.lsp.supports(path, "rename"):
            def got(edits, err):
                if err or not edits:
                    return self._text_rename(path, word, new, f"Der Language Server kann nicht umbenennen ({err or 'keine Änderungen'}).")
                self._apply_refactor(edits, title, preview=len(edits) > 1)
            self.lsp.rename(path, line, col, new, got)
        else:
            self._text_rename(path, word, new, "Für diese Sprache ist kein Language Server mit Umbenennen aktiv.")

    def _text_rename(self, path, word, new, reason):
        lang = lang_for(path)
        edits = refactor.word_edits(refactor.project_files(self.root, lang.id if lang else None), word, new)
        if not edits:
            return self.statusBar().showMessage(f"{reason} Keine Vorkommen gefunden.", 6000)
        n = sum(len(e) for e in edits.values())
        if QMessageBox.question(self, "Textuell umbenennen", f"{reason}\n\nStattdessen „{word}“ als ganzes Wort in allen {lang.name if lang else ''}-Dateien ersetzen "
                                f"({n} Stellen in {len(edits)} Dateien)? Das ist eine reine Textersetzung und berücksichtigt keine Gültigkeitsbereiche.") != QMessageBox.Yes:
            return
        self._apply_refactor(edits, f"„{word}“ → „{new}“", preview=True)

    def find_references(self):
        sym = self._symbol()
        if not sym:
            return
        ed, word, line, col = sym
        self.d_refs.show(); self.d_refs.raise_()
        path = ed.doc_path

        def show(refs):
            self.p_refs.show_results(word, refs, self.root)
        if self.lsp.supports(path, "references"):
            self.lsp.references(path, line, col, lambda refs: show(refs) if refs else self._word_refs(path, word, show))
        else:
            self._word_refs(path, word, show)

    def _word_refs(self, path, word, show):
        lang = lang_for(path)
        found = refactor.word_edits(refactor.project_files(self.root, lang.id if lang else None), word)
        refs = []
        for p, es in sorted(found.items()):
            lines = Path(p).read_text(encoding="utf-8", errors="replace").split("\n")
            refs += [(p, l0 + 1, c0 + 1, lines[l0].strip()) for l0, c0, _l1, _c1, _n in es]
        show(refs)

    def format_document(self):
        ed = self._ed()
        if not ed or not ed.doc_path:
            return
        path = ed.doc_path
        if not self.lsp.supports(path, "formatting"):
            return self.statusBar().showMessage("Der Language Server dieser Sprache kann nicht formatieren (Python: z. B. pylsp-Plugin black, C/C++: clangd).", 7000)

        def got(edits, err):
            if err or not edits:
                return self.statusBar().showMessage(f"Formatieren: {err or 'nichts zu ändern'}", 4000)
            self._apply_refactor({str(path): edits.get(str(path), [])}, "Dokument formatiert", preview=False)
        self.lsp.format_document(path, got)

    def quick_actions(self):
        ed = self._ed()
        if not ed or not ed.doc_path:
            return
        c = ed.textCursor()
        a, b = sorted((c.selectionStart(), c.selectionEnd()))
        doc = ed.document()
        ba, bb = doc.findBlock(a), doc.findBlock(b)
        path = ed.doc_path
        self.docs.save_all()

        def got(acts):
            from PySide6.QtWidgets import QMenu
            if not acts:
                return self.statusBar().showMessage("Keine Aktionen verfügbar.", 3000)
            m = QMenu(self)
            for act in acts:
                m.addAction(act["title"], lambda act=act: self._run_action(path, act))
            m.exec(ed.viewport().mapToGlobal(ed.cursorRect().bottomRight()))
        self.lsp.code_actions(path, ba.blockNumber(), a - ba.position(), bb.blockNumber(), b - bb.position(), got)

    def _run_action(self, path, act):
        if act.get("edits"):
            self._apply_refactor(act["edits"], act["title"], preview=len(act["edits"]) > 1)
        elif act.get("command"):
            self.lsp.execute_command(path, act["command"])        # der Server meldet Änderungen per workspace/applyEdit zurück

    def goto_definition(self):
        ed = self._ed()
        if ed:
            ed.jump_to_definition()

    def _open_definition(self, locs: list):
        if not locs:
            return self.statusBar().showMessage("Keine Definition gefunden.", 3000)
        path, line, col = locs[0]
        self.goto(path, line, col)

    def new_project(self):
        from .projects.wizard import NewProjectDialog
        dlg = NewProjectDialog(self, self.root.parent)
        if not dlg.exec() or not dlg.result_data:
            return
        root, main, log = dlg.result_data
        if not self.docs.close_all():
            return
        self.set_root(root)
        self.output.clear()
        self.d_output.show(); self.d_output.raise_()
        self.output.append("\n".join(log) + "\n", "ok")
        self.d_explorer.raise_()
        if main and main.exists():
            self.docs.open(main)

    # --- Formular-Designer ------------------------------------------------------------
    def new_form(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Neues Formular", "Name des Formulars:", text="Form1")
        name = name.strip()
        if not ok or not name:
            return
        if not codegen.class_name(name).isidentifier():
            return QMessageBox.warning(self, "Visual Death Studio", "Der Name muss ein gültiger Python-Bezeichner sein.")
        target = self.explorer._target_dir()
        path = target / f"{name}{FORM_SUFFIX}"
        if path.exists() or (target / f"{name}.py").exists():
            return QMessageBox.warning(self, "Visual Death Studio", f"'{name}' existiert bereits.")
        codegen.write_files(path, codegen.new_form(name))
        self.docs.open(path)

    def _add_control(self, ctype):
        d = self.docs.current_doc()
        if d and d.kind == "form":
            d.view.add_control(ctype)

    def _open_handler(self, doc, cid):
        from .designer.controls import BY_TYPE
        c = doc.view.canvas.control(cid)
        ev = BY_TYPE[c["type"]].event
        doc.save()
        if not ev:
            return self.statusBar().showMessage(f"{c['type']} hat kein Standardereignis.", 3000)
        user = codegen.write_files(doc.path, doc.view.model)
        line = codegen.add_handler(user, f"{cid}_{ev[1]}", ev[2])
        d = self.docs.open(user)
        if d:
            d.view.setPlainText(user.read_text(encoding="utf-8")); d.view.document().setModified(False)
            d.view.goto(line + 1)

    def view_code(self):
        d = self.docs.current_doc()
        if d and d.kind == "form":
            d.save()
            self.docs.open(d.run_target)

    def view_designer(self):
        d = self.docs.current_doc()
        if d and d.kind == "code":
            f = d.path.with_name(d.path.stem + FORM_SUFFIX)
            if f.exists():
                self.docs.open(f)

    def clean(self):
        import shutil
        shutil.rmtree(self.runner.build_dir, ignore_errors=True)
        self.output.append("Bereinigt.\n", "ok")

    def find(self):
        from PySide6.QtWidgets import QInputDialog
        ed = self._ed()
        if not ed:
            return
        t, ok = QInputDialog.getText(self, "Suchen", "Suchen nach:", text=ed.textCursor().selectedText())
        if ok and t and not ed.find(t):
            c = ed.textCursor(); c.movePosition(QTextCursor.MoveOperation.Start); ed.setTextCursor(c); ed.find(t)

    def goto_line(self):
        from PySide6.QtWidgets import QInputDialog
        ed = self._ed()
        if ed:
            n, ok = QInputDialog.getInt(self, "Gehe zu Zeile", "Zeilennummer:", 1, 1, ed.blockCount())
            ok and ed.goto(n)

    def toggle_comment(self):
        ed, doc = self._ed(), self.docs.current_doc()
        lang = lang_for(doc.path) if doc else None
        if not ed or not lang:
            return
        cur = ed.textCursor()
        a, b = sorted((cur.anchor(), cur.position()))
        c = ed.textCursor(); c.setPosition(a); first = c.blockNumber()
        c.setPosition(b); last = c.blockNumber()
        blocks = [ed.document().findBlockByNumber(i) for i in range(first, last + 1)]
        mark = lang.comment + " "
        un = all(bl.text().lstrip().startswith(lang.comment) for bl in blocks if bl.text().strip())
        cur.beginEditBlock()
        for bl in blocks:
            t = bl.text()
            if not t.strip():
                continue
            c = ed.textCursor(); c.setPosition(bl.position() + len(t) - len(t.lstrip()))
            if un:
                n = len(mark) if t.lstrip().startswith(mark) else len(lang.comment)
                c.setPosition(c.position() + n, QTextCursor.MoveMode.KeepAnchor); c.removeSelectedText()
            else:
                c.insertText(mark)
        cur.endEditBlock()

    def rea_analyze(self, path):
        from .rea import analyze_dir
        self.output.clear(); self.d_output.show(); self.d_output.raise_()
        self.output.append(analyze_dir(Path(path)), "stdout")

    def about(self):
        QMessageBox.about(self, "Visual Death Studio", "Visual Death Studio – eine Qt-IDE im Stil der klassischen Visual-Studio-Oberfläche.\nPySide6 · Pygments · pyte")

    def reset_layout(self):
        for d in self.all_docks:
            d.show(); d.setFloating(False)
        self.restoreState(self._default_state)

    def closeEvent(self, e):
        self._save_session()
        self.dbg.stop()
        self.tests.cancel()
        self.ai.cancel()
        self.lsp.shutdown()
        if not self.docs.close_all():
            return e.ignore()
        self.settings.setValue("root", str(self.root))
        self.runner.stop()
        self.terminal.shutdown()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("state", self.saveState())
        self.settings.setValue("layout_version", LAYOUT_VERSION)
        e.accept()


def install_qt_translations(app):
    """Deutsche Qt-Standardtexte (Farbwähler, Datei-Dialoge, Ja/Nein …), sofern PySide6 sie mitbringt."""
    from PySide6.QtCore import QLibraryInfo, QTranslator
    d = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    for name in ("qtbase_de", "qt_de"):
        t = QTranslator(app)
        if t.load(name, d):
            app.installTranslator(t)


def main():
    if "--install-desktop" in sys.argv:
        print("Starter angelegt:", install_desktop_entry())
        return
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if desktop_entry_exists():          # sonst meldet das Desktop-Portal „App info not found“
        app.setDesktopFileName(DESKTOP_ID)
    app.setWindowIcon(app_icon())
    install_qt_translations(app)
    app.setStyle("Fusion")
    apply_palette(app)
    app.setStyleSheet(stylesheet())
    w = MainWindow()
    w._default_state = w.saveState()
    w.show()
    sys.exit(app.exec())
