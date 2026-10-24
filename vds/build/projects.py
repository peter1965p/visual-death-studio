"""Erkennung des Build-Systems eines Projektordners (Menü Erstellen): Schritte zum Erstellen und Bereinigen."""
import json
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..project import ProjectSettings


@dataclass
class BuildSystem:
    id: str
    name: str
    build: list                                       # [(Befehl, Arbeitsordner)]
    clean: list = field(default_factory=list)
    tool: str = ""                                    # benötigtes Programm (für die Fehlermeldung)

    def missing_tool(self) -> str | None:
        return self.tool if self.tool and not shutil.which(self.tool) else None


def _npm_has_script(root: Path, name: str) -> bool:
    try:
        return name in json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, ValueError):
        return False


def _custom(cmd: str, root: Path) -> list:
    """Eigener Befehl aus den Projekteigenschaften: läuft in einer Shell, damit && und Umgebungsvariablen funktionieren."""
    return [(["bash", "-c", cmd], root)] if cmd.strip() else []


def detect(root: Path, settings: ProjectSettings | None = None) -> BuildSystem | None:
    """Erkennt das Build-System anhand typischer Dateien im Projektordner; eigene Befehle der Projekteigenschaften haben Vorrang."""
    root = Path(root)
    s = settings or ProjectSettings()
    if s.build_cmd.strip():
        return BuildSystem("custom", "Eigener Befehl", _custom(s.build_cmd, root), _custom(s.clean_cmd, root), "bash")
    if (root / "CMakeLists.txt").exists():
        b = root / "build"
        return BuildSystem("cmake", "CMake", [(["cmake", "-S", ".", "-B", "build"], root), (["cmake", "--build", "build", "-j"], root)],
                           [(["cmake", "-E", "remove_directory", str(b)], root)], "cmake")
    if (root / "Cargo.toml").exists():
        return BuildSystem("cargo", "Cargo", [(["cargo", "build"], root)], [(["cargo", "clean"], root)], "cargo")
    if (root / "go.mod").exists():
        return BuildSystem("go", "Go", [(["go", "build", "./..."], root)], [(["go", "clean", "./..."], root)], "go")
    dn = sorted(root.glob("*.sln")) + sorted(root.glob("*.csproj"))
    if dn:
        t = str(dn[0])
        return BuildSystem("dotnet", ".NET", [(["dotnet", "build", t], root)], [(["dotnet", "clean", t], root)], "dotnet")
    if (root / "pom.xml").exists():
        return BuildSystem("maven", "Maven", [(["mvn", "-q", "compile"], root)], [(["mvn", "-q", "clean"], root)], "mvn")
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        g = "./gradlew" if (root / "gradlew").exists() else "gradle"
        return BuildSystem("gradle", "Gradle", [([g, "build"], root)], [([g, "clean"], root)], "" if g.startswith("./") else "gradle")
    if (root / "Makefile").exists() or (root / "makefile").exists():
        return BuildSystem("make", "Make", [(["make"], root)], [(["make", "clean"], root)], "make")
    if _npm_has_script(root, "build"):
        return BuildSystem("npm", "npm", [(["npm", "run", "build"], root)], [], "npm")
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return BuildSystem("python", "Python-Projekt", [(["python3", "-m", "compileall", "-q", "."], root)], [], "")
    return None


def describe(cmd: list) -> str:
    return " ".join(shlex.quote(c) for c in cmd)
