"""Projekteinstellungen (.vds/project.json): Startdatei, Argumente, Arbeitsordner, Umgebung, Interpreter, eigene Build-/Test-Befehle."""
import json
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ProjectSettings:
    startup: str = ""                 # Startdatei, relativ zum Projektordner (leer = aktive Datei)
    args: str = ""                    # Programmargumente als Kommandozeile
    cwd: str = ""                     # Arbeitsordner (leer = Ordner der Startdatei)
    env: dict = field(default_factory=dict)
    python: str = ""                  # Interpreter (leer = .venv des Projekts bzw. System)
    build_cmd: str = ""               # eigener Build-Befehl (leer = automatische Erkennung)
    clean_cmd: str = ""
    test_cmd: str = ""
    run_cmd: str = ""                 # eigener Startbefehl (z. B. Dev-Server): ersetzt F5/Strg+F5 für das ganze Projekt

    @staticmethod
    def path(root: Path) -> Path:
        return Path(root) / ".vds" / "project.json"

    @classmethod
    def load(cls, root: Path) -> "ProjectSettings":
        try:
            d = json.loads(cls.path(root).read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, root: Path):
        p = self.path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    def arg_list(self) -> list:
        try:
            return shlex.split(self.args)
        except ValueError:
            return self.args.split()

    def startup_path(self, root: Path) -> Path | None:
        p = (Path(root) / self.startup) if self.startup else None
        return p if p and p.is_file() else None

    def work_dir(self, root: Path, file: Path) -> Path:
        if self.cwd:
            c = Path(self.cwd)
            c = c if c.is_absolute() else Path(root) / c
            if c.is_dir():
                return c
        return file.parent
