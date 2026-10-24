"""Build/Run über QProcess: Compiler- und Programmausgabe landen live im Ausgabefenster."""
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..project import ProjectSettings
from .languages import lang_for


class Runner(QObject):
    output = Signal(str, str)        # text, kind: stdout|stderr|info|ok
    finished = Signal(int, str)      # exit code, gesammelte stderr/stdout für die Fehlerliste
    busyChanged = Signal(bool)

    def __init__(self, build_dir: Path, parent=None):
        super().__init__(parent)
        self.build_dir = build_dir
        self.proc: QProcess | None = None
        self._steps: list = []
        self._collected = ""
        self.project = ProjectSettings()          # vom Hauptfenster gesetzt
        self.root = Path(".")

    @property
    def busy(self) -> bool:
        return self.proc is not None

    def start_command(self, cmd: list, cwd: Path):
        """Beliebigen Befehl ausführen (Projekt-Build, Kompilieren, Aufräumen …); Ausgabe und Ende wie bei start()."""
        if self.busy:
            return
        self._steps = [(list(cmd), Path(cwd))]
        self._collected = ""
        self._next(0)

    def start_steps(self, steps: list):
        """Mehrere Schritte [(Befehl, Arbeitsordner)] nacheinander; bei einem Fehler wird abgebrochen."""
        if self.busy or not steps:
            return
        self._steps = [(list(c), Path(w)) for c, w in steps]
        self._collected = ""
        self._next(0)

    @staticmethod
    def python_for(file: Path) -> str:
        """Interpreter für ein Python-Programm: .venv/venv des Projekts (von der Datei aufwärts gesucht), sonst System-python3."""
        d = file.resolve().parent
        for _ in range(6):
            for name in (".venv", "venv"):
                py = d / name / "bin" / "python"
                if py.exists():
                    return str(py)
            if d.parent == d:
                break
            d = d.parent
        return shutil.which("python3") or sys.executable

    def interpreter(self, file: Path) -> str:
        """Python-Interpreter: Einstellung des Projekts, sonst .venv, sonst System."""
        return self.project.python if self.project.python and Path(self.project.python).exists() else self.python_for(file)

    def _expand(self, cmd, file, out):
        cmd = [c.replace("{file}", str(file)).replace("{out}", str(out)) for c in cmd]
        if cmd[0] == "python3":
            cmd[0] = self.interpreter(file)
        return cmd

    def start(self, file: Path, mode: str = "buildrun", config: str = "Debug"):
        """mode: build | run | buildrun"""
        if self.busy:
            return
        lang = lang_for(file)
        if not lang:
            self.output.emit(f"Keine Ausführungsumgebung für {file.name}\n", "stderr")
            self.finished.emit(1, "")
            return
        self.build_dir.mkdir(parents=True, exist_ok=True)
        out = self.build_dir / file.stem
        run_cwd = self.project.work_dir(self.root, file)
        self._steps = []
        proj = self._csproj(file) if lang.id == "csharp" else None
        if proj:
            return self._start_dotnet_project(proj, mode)
        if lang.build and mode in ("build", "buildrun"):
            cmd = self._expand(lang.build, file, out)
            if config == "Release":
                cmd = [c for c in cmd if c not in ("-g",)] + ["-O2"] if cmd[0] in ("gcc", "g++") else cmd
            self._steps.append((cmd, file.parent))
        if mode in ("run", "buildrun"):
            if lang.build and mode == "run" and not out.exists():
                self.output.emit("Noch nicht gebaut – zuerst Erstellen (Strg+Umschalt+B).\n", "stderr")
                self.finished.emit(1, "")
                return
            self._steps.append((self._expand(lang.run, file, out) + self.project.arg_list(), run_cwd))
        self._collected = ""
        self._next(0)

    @staticmethod
    def _csproj(file: Path):
        """Nächstgelegene .csproj oberhalb der Datei (max. 4 Ebenen)."""
        d = file.parent
        for _ in range(4):
            found = sorted(d.glob("*.csproj"))
            if found:
                return found[0]
            if d.parent == d:
                break
            d = d.parent
        return None

    def _start_dotnet_project(self, proj: Path, mode: str):
        cwd = proj.parent
        if "<UseMaui>true" in proj.read_text(encoding="utf-8", errors="replace"):
            self.output.emit("MAUI hat unter Linux keinen offiziellen Desktop-Zielpfad (nur ein experimentelles GTK4-Backend). Es wird für Android gebaut "
                             "(benötigt: dotnet workload install maui-android und ein Android-SDK).\n", "info")
            self._steps = [(["dotnet", "build", str(proj), "-f", "net10.0-android"], cwd)]
        elif mode == "build":
            self._steps = [(["dotnet", "build", str(proj)], cwd)]
        else:
            args = self.project.arg_list()
            self._steps = [(["dotnet", "run", "--project", str(proj)] + (["--"] + args if args else []), self.project.work_dir(self.root, proj))]
        self._collected = ""
        self._next(0)

    def _next(self, code: int):
        if code != 0 or not self._steps:
            self._done(code)
            return
        cmd, cwd = self._steps.pop(0)
        if not shutil.which(cmd[0]) and not Path(cmd[0]).exists():
            self.output.emit(f"'{cmd[0]}' ist auf diesem System nicht installiert.\n", "stderr")
            self._done(127)
            return
        self.output.emit("> " + " ".join(cmd) + "\n", "info")
        p = QProcess(self)
        p.setWorkingDirectory(str(cwd))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        for k, v in self.project.env.items():
            env.insert(str(k), str(v))
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(lambda: self._read(p, "stdout"))
        p.readyReadStandardError.connect(lambda: self._read(p, "stderr"))
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self._done(127))
        p.finished.connect(lambda c, st: self._finished_step(c if st == QProcess.NormalExit else 1))
        self.proc = p
        self.busyChanged.emit(True)
        p.start(cmd[0], cmd[1:])

    def _read(self, p, kind):
        data = bytes(p.readAllStandardOutput() if kind == "stdout" else p.readAllStandardError()).decode("utf-8", "replace")
        self._collected += data
        self.output.emit(data, kind)

    def _finished_step(self, code):
        self.proc = None
        self._next(code)

    def _done(self, code):
        if self.proc:
            self.proc = None
        self.busyChanged.emit(False)
        self.finished.emit(code, self._collected)

    def write(self, text: str):
        if self.proc:
            self.proc.write(text.encode())

    def stop(self):
        if self.proc:
            self._steps.clear()
            self.proc.kill()
