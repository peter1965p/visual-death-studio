"""Test-Dienst: führt Entdeckung und Läufe der Frameworks asynchron aus und meldet Ergebnisse per Signal."""
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .frameworks import Framework, Result, TestCase, detect_frameworks


class TestService(QObject):
    __test__ = False
    discovered = Signal(list)         # [TestCase]
    resultsChanged = Signal(dict)     # {id: Result} (Stand: gesamt)
    running = Signal(bool)
    log = Signal(str)
    started = Signal(list)            # IDs, die gerade laufen

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.python = "python3"
        self.frameworks: list[Framework] = []
        self.cases: dict[str, tuple] = {}         # id -> (Framework, TestCase)
        self.results: dict[str, Result] = {}
        self.proc: QProcess | None = None
        self.custom_cmd = ""

    @property
    def busy(self) -> bool:
        return self.proc is not None

    def set_root(self, root: Path, python: str):
        self.root, self.python = Path(root), python
        self.frameworks, self.cases, self.results = [], {}, {}

    # --- Entdeckung ---------------------------------------------------------------------------------------------------
    def discover(self):
        if self.busy:
            return
        self.frameworks = detect_frameworks(self.root, self.python)
        self.cases = {}
        self.results = {}
        self.running.emit(True)
        self._discover_next(list(self.frameworks))

    def _discover_next(self, todo: list):
        if not todo:
            self.running.emit(False)
            self.discovered.emit([c for _, c in self.cases.values()])
            return
        fw = todo.pop(0)
        spec = fw.discover_cmd()
        if spec is None:                                  # statische Entdeckung
            self._add(fw, fw.parse_discovery("", "", 0))
            return self._discover_next(todo)
        self._exec(spec, lambda code, out, err: (self._add(fw, fw.parse_discovery(out, err, code)), self._discover_next(todo)))

    def _add(self, fw, cases):
        for c in cases:
            self.cases[c.id] = (fw, c)

    # --- Ausführen --------------------------------------------------------------------------------------------------------
    def run(self, ids: list | None = None):
        """ids None = alles. Gruppiert nach Framework; ein Lauf nach dem anderen."""
        if self.busy:
            return
        plan = []
        if ids is None:
            plan = [(fw, None) for fw in self.frameworks]
            running_ids = list(self.cases)
        else:
            by: dict = {}
            for i in ids:
                if i in self.cases:
                    by.setdefault(self.cases[i][0], []).append(i)
            plan = list(by.items())
            running_ids = [i for g in by.values() for i in g]
        if not plan:
            return self.log.emit("Keine Tests zum Ausführen.\n")
        self.started.emit(running_ids)
        self.running.emit(True)
        self._tmp = Path(tempfile.mkdtemp(prefix="vds-tests-"))
        self._run_next(plan)

    def _run_next(self, plan: list):
        if not plan:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self.running.emit(False)
            return
        fw, ids = plan.pop(0)
        cmd, cwd = fw.run_cmd(ids, self._tmp)

        def done(code, out, err):
            res = fw.parse_results(out, err, code, self._tmp, {i: c for i, (f, c) in self.cases.items() if f is fw})
            if not res and code != 0:
                self.log.emit(f"{fw.name}: Lauf ohne auswertbare Ergebnisse (Exit-Code {code}).\n{(err or out)[-800:]}\n")
            self.results.update(res)
            self.resultsChanged.emit(dict(self.results))
            self._run_next(plan)
        self._exec((cmd, cwd), done)

    def cancel(self):
        if self.proc:
            p, self.proc = self.proc, None
            p.kill()
            self.running.emit(False)

    # --- Prozess ----------------------------------------------------------------------------------------------------------
    def _exec(self, spec, cb):
        cmd, cwd = spec
        if not shutil.which(cmd[0]) and not Path(cmd[0]).exists():
            self.log.emit(f"'{cmd[0]}' ist nicht installiert.\n")
            return cb(127, "", "")
        p = QProcess(self)
        p.setWorkingDirectory(str(cwd))
        out, err = [], []
        p.readyReadStandardOutput.connect(lambda: out.append(bytes(p.readAllStandardOutput()).decode("utf-8", "replace")))
        p.readyReadStandardError.connect(lambda: err.append(bytes(p.readAllStandardError()).decode("utf-8", "replace")))

        def fin(code, status):
            if self.proc is not p:
                return
            self.proc = None
            cb(code, "".join(out), "".join(err))
        p.finished.connect(fin)
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and (setattr(self, "proc", None), cb(127, "", "Start fehlgeschlagen")))
        self.proc = p
        p.start(cmd[0], cmd[1:])
