"""Profiler: CPU-Zeit (cProfile) und Speicher (tracemalloc) eines Python-Skripts, ausgewertet als Tabelle mit Sprung zum Code."""
import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

RUNNER = Path(__file__).resolve().parent.parent / "profile" / "_runner.py"


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class _Num(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn()
        a, b = self.data(col, Qt.UserRole), other.data(col, Qt.UserRole)
        return a < b if a is not None and b is not None else self.text(col) < other.text(col)


class ProfilerPanel(QWidget):
    jumpTo = Signal(str, int)
    log = Signal(str)
    finished = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.interpreter = lambda: "python3"
        self.proc: QProcess | None = None
        self.result: dict | None = None
        self.mode = QComboBox(); self.mode.addItems(["CPU-Zeit", "Speicher"])
        self.only_project = QCheckBox("Nur Projektcode"); self.only_project.setChecked(True)
        self.only_project.toggled.connect(lambda _: self._fill())
        self.btn = QPushButton("Profil erstellen")
        self.info = QLabel("Wähle eine Python-Datei und starte die Messung (Debuggen → Profiler).")
        self.info.setObjectName("sub"); self.info.setWordWrap(True)
        self.tree = QTreeWidget(); self.tree.setRootIsDecorated(False); self.tree.setSortingEnabled(True)
        self.tree.itemDoubleClicked.connect(self._open)
        top = QHBoxLayout()
        for w in (self.mode, self.only_project):
            top.addWidget(w)
        top.addStretch(1); top.addWidget(self.btn)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(top); lay.addWidget(self.info); lay.addWidget(self.tree, 1)
        self._heads("CPU-Zeit")

    def set_root(self, root: Path):
        self.root = Path(root)

    def _heads(self, mode):
        self.tree.setHeaderLabels(["Funktion", "Aufrufe", "Eigen (s)", "Gesamt (s)", "Datei"] if mode == "CPU-Zeit" else ["Stelle", "Größe", "Blöcke", "Datei"])
        self.tree.setColumnWidth(0, 260)

    def start(self, script: Path, args: list | None = None) -> bool:
        if self.proc is not None:
            return False
        mode = "cpu" if self.mode.currentIndex() == 0 else "memory"
        self._out = Path(tempfile.mkdtemp(prefix="vds-prof-")) / "profile.json"
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(Path(script).parent))
        self.proc.readyReadStandardOutput.connect(lambda: self.log.emit(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")))
        self.proc.readyReadStandardError.connect(lambda: self.log.emit(bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")))
        self.proc.finished.connect(self._done)
        self.btn.setEnabled(False)
        self.info.setText(f"Messung läuft: {Path(script).name} …")
        self.proc.start(self.interpreter(), [str(RUNNER), str(self._out), mode, str(script), *(args or [])])
        return True

    def _done(self, code, _status=None):
        self.proc, ok = None, False
        self.btn.setEnabled(True)
        try:
            self.result = json.loads(self._out.read_text(encoding="utf-8"))
            ok = True
        except (OSError, ValueError):
            self.result = None
            self.info.setText("Keine Messdaten – das Skript ist vermutlich beim Start abgestürzt (siehe Ausgabe).")
        if ok:
            self._fill()
        self.finished.emit(ok)

    def _is_project(self, f: str) -> bool:
        try:
            Path(f).resolve().relative_to(self.root.resolve())
        except (ValueError, OSError):
            return False
        return ".venv" not in Path(f).parts and "venv" not in Path(f).parts

    def _fill(self):
        r = self.result
        self.tree.clear()
        if not r:
            return
        cpu = r["mode"] == "cpu"
        self._heads("CPU-Zeit" if cpu else "Speicher")
        rows = [x for x in r["rows"] if not self.only_project.isChecked() or self._is_project(x["file"])]
        for x in rows[:300]:
            f = x["file"]
            short = Path(f).name if f.startswith("<") is False else f
            if cpu:
                it = _Num(self.tree, [f"{x['func']}  ({short}:{x['line']})", str(x["calls"]), f"{x['tottime']:.4f}", f"{x['cumtime']:.4f}", f])
                for col, key in ((1, "calls"), (2, "tottime"), (3, "cumtime")):
                    it.setData(col, Qt.UserRole, x[key])
            else:
                it = _Num(self.tree, [f"{short}:{x['line']}", fmt_bytes(x["size"]), str(x["count"]), f])
                it.setData(1, Qt.UserRole, x["size"]); it.setData(2, Qt.UserRole, x["count"])
            it.setData(0, Qt.UserRole + 1, (f, x["line"]))
        self.tree.sortItems(3 if cpu else 1, Qt.DescendingOrder)
        head = f"{Path(r['script']).name}: {r['seconds']:.2f} s"
        self.info.setText(head if cpu else f"{head} · Spitze {fmt_bytes(r['peak'])}, am Ende {fmt_bytes(r['current'])} (Doppelklick springt zum Code)")

    def _open(self, item, _col=0):
        d = item.data(0, Qt.UserRole + 1)
        if d and Path(d[0]).is_file():
            self.jumpTo.emit(d[0], int(d[1]))
