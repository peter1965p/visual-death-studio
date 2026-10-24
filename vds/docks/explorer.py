"""Projektmappen-Explorer auf Basis von QFileSystemModel."""
import shutil
from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileSystemModel, QInputDialog, QMenu, QMessageBox, QTreeView

from ..build.languages import lang_for
from ..icons import icon

LANG_COLOR = {"python": "#4b8bbe", "javascript": "#e8d44d", "typescript": "#3178c6", "c": "#6a9bd3", "cpp": "#6a9bd3",
              "csharp": "#68b723", "rust": "#dea584", "go": "#00add8", "java": "#e76f00", "shell": "#89e051", "php": "#8892bf", "vue": "#42b883"}


class _Model(QFileSystemModel):
    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DecorationRole and index.column() == 0:
            if self.isDir(index):
                return icon("folder", "#ffc474")
            lang = lang_for(self.filePath(index))
            return icon("file", LANG_COLOR.get(lang.id, "#c8d6f5") if lang else "#c8d6f5")
        return super().data(index, role)


class Explorer(QTreeView):
    fileOpened = Signal(str)
    selectionPath = Signal(str)
    fileDeleted = Signal(str)
    fileRenamed = Signal(str, str)
    analyzeRequested = Signal(str)
    markForCompare = Signal(str)
    compareWithMarked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_ = _Model(self)
        self.model_.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.Hidden)
        self.setModel(self.model_)
        for c in (1, 2, 3):
            self.hideColumn(c)
        self.setHeaderHidden(True)
        self.setEditTriggers(QTreeView.NoEditTriggers)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.doubleClicked.connect(self._activated)
        self.root = Path()

    def set_root(self, path: Path):
        self.root = path
        idx = self.model_.setRootPath(str(path))
        self.setRootIndex(idx)

    def path_at(self, idx: QModelIndex) -> Path:
        return Path(self.model_.filePath(idx)) if idx.isValid() else self.root

    def currentChanged(self, cur, prev):
        super().currentChanged(cur, prev)
        if cur.isValid():
            self.selectionPath.emit(self.model_.filePath(cur))

    def _activated(self, idx):
        if not self.model_.isDir(idx):
            self.fileOpened.emit(self.model_.filePath(idx))

    def _target_dir(self) -> Path:
        p = self.path_at(self.currentIndex())
        return p if p.is_dir() else p.parent

    def new_file(self, is_dir=False):
        name, ok = QInputDialog.getText(self, "Neuer Ordner" if is_dir else "Neues Element hinzufügen", "Name:")
        if not ok or not name.strip():
            return
        p = self._target_dir() / name.strip()
        if p.exists():
            return QMessageBox.warning(self, "Visual Death Studio", f"'{p.name}' existiert bereits.")
        p.mkdir(parents=True) if is_dir else (p.parent.mkdir(parents=True, exist_ok=True), p.touch())
        if not is_dir:
            self.fileOpened.emit(str(p))

    def rename(self):
        p = self.path_at(self.currentIndex())
        name, ok = QInputDialog.getText(self, "Umbenennen", "Neuer Name:", text=p.name)
        if ok and name.strip() and name != p.name:
            dst = p.with_name(name.strip())
            if dst.exists():
                return QMessageBox.warning(self, "Visual Death Studio", f"'{dst.name}' existiert bereits.")
            p.rename(dst)
            self.fileRenamed.emit(str(p), str(dst))

    def delete(self):
        p = self.path_at(self.currentIndex())
        if p == self.root:
            return
        if QMessageBox.question(self, "Löschen", f"'{p.name}' endgültig löschen?") == QMessageBox.Yes:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            self.fileDeleted.emit(str(p))

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("Neues Element hinzufügen…", self.new_file)
        m.addAction("Neuer Ordner…", lambda: self.new_file(True))
        m.addSeparator()
        m.addAction("Umbenennen", self.rename)
        m.addAction("Löschen", self.delete)
        m.addSeparator()
        cur = self.path_at(self.currentIndex())
        if cur.is_file():
            m.addAction("Zum Vergleichen auswählen", lambda: self.markForCompare.emit(str(cur)))
            m.addAction("Mit ausgewählter Datei vergleichen", lambda: self.compareWithMarked.emit(str(cur)))
            m.addSeparator()
        m.addAction("REA: Ordner analysieren", lambda: self.analyzeRequested.emit(str(self._target_dir())))
        m.exec(self.viewport().mapToGlobal(pos))
