"""Dokument-Tabs: Code-Editor oder Formular-Designer (*.form.json) je Datei."""
import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QTabWidget

from ..designer import codegen, targets
from ..designer.canvas import FormDesigner
from .code_editor import CodeEditor

FORM_SUFFIX = ".form.json"


class Document:
    def __init__(self, path: Path, view, kind: str):
        self.path, self.view, self.kind = path, view, kind

    @property
    def editor(self) -> CodeEditor | None:
        """Nur für Code-Dokumente."""
        return self.view if self.kind == "code" else None

    @property
    def modified(self) -> bool:
        if self.kind == "diff":
            return False
        return self.view.document().isModified() if self.kind == "code" else self.view.modified

    @property
    def run_target(self) -> Path | None:
        if self.kind == "diff":
            return None
        if self.kind == "form":
            return targets.user_file(self.path, self.view.model)
        return self.path

    @property
    def target(self) -> str:
        return targets.target_of(self.view.model) if self.kind == "form" else ""

    warnings: list = []

    def save(self):
        if self.kind == "diff":
            return
        if self.kind == "code":
            self.path.write_text(self.view.toPlainText(), encoding="utf-8")
            self.view.document().setModified(False)
        else:
            codegen.write_files(self.path, self.view.model)
            self.warnings = targets.unsupported(self.view.model)
            self.view.mark_clean()


class Documents(QTabWidget):
    currentDocChanged = Signal(object)   # Document|None
    breakpointsChanged = Signal()
    cursorInfo = Signal(int, int)
    docOpened = Signal(object)
    docClosed = Signal(object)
    saved = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setDocumentMode(True)
        self.tabCloseRequested.connect(self.close_tab)
        self.currentChanged.connect(lambda _i: (self.currentDocChanged.emit(self.current_doc()), self._emit_cursor()))
        self.docs: dict[Path, Document] = {}
        self.intel = None            # LspManager (vom Hauptfenster gesetzt)

    def current_doc(self) -> Document | None:
        w = self.currentWidget()
        return next((d for d in self.docs.values() if d.view is w), None)

    def open(self, path: Path) -> Document | None:
        path = path.resolve()
        if path in self.docs:
            self.setCurrentWidget(self.docs[path].view)
            return self.docs[path]
        if path.name.endswith(FORM_SUFFIX):
            try:
                model = json.loads(path.read_text(encoding="utf-8"))
                view, kind = FormDesigner(model), "form"
            except (ValueError, KeyError) as e:
                QMessageBox.warning(self, "Visual Death Studio", f"Formular '{path.name}' ist ungültig: {e}")
                return None
            view.modifiedChanged.connect(lambda _m, p=path: self._retitle(self.docs.get(p)))
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                QMessageBox.warning(self, "Visual Death Studio", f"'{path.name}' ist keine Textdatei.")
                return None
            view, kind = CodeEditor(path.name), "code"
            view.intel, view.doc_path = self.intel, path
            view.setPlainText(text)
            view.document().setModified(False)
            view.document().modificationChanged.connect(lambda _m, p=path: self._retitle(self.docs.get(p)))
            view.breakpointsChanged.connect(self.breakpointsChanged)
            view.cursorInfo.connect(lambda l, c, e=view: e is self.currentWidget() and self.cursorInfo.emit(l, c))
        doc = Document(path, view, kind)
        self.docs[path] = doc
        self.addTab(view, path.name)
        self.setTabToolTip(self.indexOf(view), str(path))
        self.setCurrentWidget(view)
        self.docOpened.emit(doc)
        return doc

    def add_diff(self, key: str, title: str, view) -> Document:
        """Fügt einen Diff-Tab hinzu (oder aktiviert den vorhandenen mit gleichem Schlüssel)."""
        path = Path("diff://" + key)
        if path in self.docs:
            self.setCurrentWidget(self.docs[path].view)
            return self.docs[path]
        doc = Document(path, view, "diff")
        self.docs[path] = doc
        self.addTab(view, "⇄ " + title)
        self.setTabToolTip(self.indexOf(view), title)
        self.setCurrentWidget(view)
        return doc

    def find_diff(self, key: str):
        d = self.docs.get(Path("diff://" + key))
        return d.view if d else None

    def _retitle(self, doc):
        i = self.indexOf(doc.view) if doc else -1
        if i >= 0:
            self.setTabText(i, doc.path.name + (" ●" if doc.modified else ""))

    def _emit_cursor(self):
        d = self.current_doc()
        if d and d.kind == "code":
            c = d.view.textCursor()
            self.cursorInfo.emit(c.blockNumber() + 1, c.positionInBlock() + 1)

    def save(self, doc: Document | None = None) -> bool:
        doc = doc or self.current_doc()
        if not doc:
            return False
        doc.save()
        self.saved.emit(doc)
        return True

    def save_modified_code(self):
        """Für Autospeichern: nur geänderte Code-Dokumente (Formulare werden bewusst nicht im Hintergrund neu erzeugt)."""
        n = 0
        for d in list(self.docs.values()):
            if d.kind == "code" and d.modified:
                d.save(); self.saved.emit(d); n += 1
        return n

    def save_all(self):
        for d in list(self.docs.values()):
            if d.modified:
                d.save()
                self.saved.emit(d)

    def close_tab(self, index: int) -> bool:
        view = self.widget(index)
        doc = next(d for d in self.docs.values() if d.view is view)
        if doc.modified:
            r = QMessageBox.question(self, "Visual Death Studio", f"Änderungen an '{doc.path.name}' speichern?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save:
                doc.save()
        self.removeTab(index)
        del self.docs[doc.path]
        self.docClosed.emit(doc)
        view.deleteLater()
        self.breakpointsChanged.emit()
        return True

    def close_path(self, path: Path):
        doc = self.docs.get(path.resolve())
        if doc:
            self.removeTab(self.indexOf(doc.view)); del self.docs[doc.path]; doc.view.deleteLater()

    def close_all(self) -> bool:
        while self.count():
            if not self.close_tab(0):
                return False
        return True

    def reload_changed(self):
        """Lädt unveränderte Dokumente neu, deren Datei auf der Platte (z. B. durch Claude) geändert wurde."""
        for d in list(self.docs.values()):
            if d.kind == "diff" or d.modified or not d.path.exists():
                continue
            if d.kind == "code":
                text = d.path.read_text(encoding="utf-8", errors="replace")
                if text != d.view.toPlainText():
                    line = d.view.textCursor().blockNumber()
                    d.view.setPlainText(text)
                    d.view.document().setModified(False)
                    c = d.view.textCursor(); c.setPosition(d.view.document().findBlockByNumber(line).position()); d.view.setTextCursor(c)
            else:
                try:
                    model = json.loads(d.path.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if model != d.view.model:
                    d.view.canvas.load(model); d.view.canvas.set_sel([])

    def all_breakpoints(self):
        return [(str(d.path), l, d.view.bp_conditions.get(l, ""), l not in d.view.bp_disabled)
                for d in self.docs.values() if d.kind == "code" for l in sorted(d.view.breakpoints)]
