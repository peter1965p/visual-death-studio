"""Export: ein VDS-Projekt für andere Werkzeuge aufbereiten (Qt Creator, Visual Studio, VS Code) oder als sauberes ZIP weitergeben.

Vorhandene Dateien werden nie überschrieben; die Quelldateien des Projekts bleiben unverändert."""
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import project as _project
from ..build import projects as buildsys

TARGETS = {
    "qtcreator": "Qt Creator (CMakeLists.txt bzw. .pyproject)",
    "visualstudio": "Visual Studio (.sln bzw. CMake-Ordner)",
    "vscode": "VS Code (tasks.json, launch.json)",
    "intellij": "IntelliJ IDEA / PyCharm / CLion (.idea, .iml)",
    "eclipse": "Eclipse (.project, .classpath)",
    "zip": "ZIP-Archiv ohne Build- und Umgebungsordner",
}
SKIP_DIRS = {".vds", ".git", "venv", ".venv", "node_modules", "__pycache__", "build", "bin", "obj", "target", "dist", ".idea", ".vs", ".gradle", "vendor", "out"}
CPP = (".c", ".cc", ".cpp", ".cxx")
CPP_ALL = CPP + (".h", ".hpp", ".hh", ".ui", ".qrc")
DOTNET = {".csproj": "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}", ".fsproj": "{F2A71F9B-5D33-465A-A702-920D77279786}", ".vbproj": "{F184B08F-C81C-45F6-A57F-5ABD9991F28F}"}


class ProjectExportError(Exception):
    pass


@dataclass
class Exported:
    target: str
    files: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _walk(root: Path, exts: tuple) -> list:
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and p.suffix.lower() in exts and not any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            out.append(rel.as_posix())
    return out


def _name(root: Path) -> str:
    return re.sub(r"[^\w.-]", "_", root.name) or "projekt"


def _write(path: Path, text: str, res: Exported) -> bool:
    if path.exists():
        res.notes.append(f"{path.name} gibt es schon und bleibt unverändert.")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    res.files.append(path)
    return True


def export_project(root: Path, target: str, dest: Path | None = None) -> Exported:
    root = Path(root)
    res = Exported(target)
    if target == "zip":
        return _zip(root, dest or root.parent / f"{_name(root)}.zip", res)
    if target == "qtcreator":
        return _qtcreator(root, res)
    if target == "visualstudio":
        return _visualstudio(root, res)
    if target == "vscode":
        return _vscode(root, res)
    if target == "intellij":
        return _intellij(root, res)
    if target == "eclipse":
        return _eclipse(root, res)
    raise ProjectExportError(f"Unbekanntes Exportziel: {target}")


def cmake_for(root: Path) -> str | None:
    """CMakeLists.txt für die C/C++-Quellen im Projekt (Qt wird an `#include <Q…>` erkannt); None, wenn es keine gibt."""
    srcs = _walk(root, CPP_ALL)
    if not any(s.lower().endswith(CPP) for s in srcs):
        return None
    qt = any(re.search(r"#\s*include\s*<Q\w+", (root / s).read_text(encoding="utf-8", errors="replace")) for s in srcs if s.lower().endswith(CPP_ALL[:7]))
    cpp = any(s.lower().endswith((".cpp", ".cc", ".cxx", ".hpp", ".hh")) for s in srcs)
    name = _name(root)
    lines = ["cmake_minimum_required(VERSION 3.16)", f"project({name} LANGUAGES {'C CXX' if cpp else 'C'})"]
    if cpp:
        lines += ["set(CMAKE_CXX_STANDARD 17)", "set(CMAKE_CXX_STANDARD_REQUIRED ON)"]
    if qt:
        lines += ["set(CMAKE_AUTOMOC ON)", "set(CMAKE_AUTOUIC ON)", "set(CMAKE_AUTORCC ON)", "find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)"]
    lines.append(f"add_executable({name}\n    " + "\n    ".join(srcs) + "\n)")
    lines.append(f"target_include_directories({name} PRIVATE ${{CMAKE_CURRENT_SOURCE_DIR}})")
    if qt:
        lines.append(f"target_link_libraries({name} PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)")
    return "\n".join(lines) + "\n"


def _cmake_project(root: Path, res: Exported, ide: str) -> bool:
    if (root / "CMakeLists.txt").exists():
        res.notes.append(f"CMakeLists.txt ist vorhanden – in {ide} dieses Projekt über die CMakeLists.txt öffnen.")
        return True
    text = cmake_for(root)
    if text is None:
        return False
    _write(root / "CMakeLists.txt", text, res)
    res.notes.append(f"CMakeLists.txt angelegt – in {ide} die CMakeLists.txt öffnen.")
    return True


def _qtcreator(root: Path, res: Exported) -> Exported:
    if _cmake_project(root, res, "Qt Creator"):
        return res
    py = _walk(root, (".py", ".ui", ".qrc", ".json", ".qml"))
    py = [p for p in py if not p.endswith(".form.json")]
    if any(p.endswith(".py") for p in py):
        _write(root / f"{_name(root)}.pyproject", json.dumps({"files": py}, indent=2) + "\n", res)
        res.notes.append("Qt Creator öffnet Python-/PySide-Projekte über die .pyproject-Datei.")
        return res
    raise ProjectExportError("Für Qt Creator braucht das Projekt C/C++-Quellen oder Python-Dateien.")


def _visualstudio(root: Path, res: Exported) -> Exported:
    sln_name = f"{_name(root)}.sln"
    projs = [p for ext in DOTNET for p in sorted(root.rglob(f"*{ext}"))
             if not any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts[:-1])]
    if projs:
        if list(root.glob("*.sln")):
            res.notes.append("Eine .sln gibt es schon und bleibt unverändert.")
            return res
        _write(root / sln_name, _sln_text(root, projs), res)
        res.notes.append(f"{sln_name} angelegt – in Visual Studio öffnen (Windows-spezifische Teile wie WPF brauchen Windows).")
        return res
    if _cmake_project(root, res, "Visual Studio (Datei → Öffnen → CMake)"):
        return res
    raise ProjectExportError("Für Visual Studio braucht das Projekt eine .csproj/.fsproj/.vbproj oder C/C++-Quellen.")


def _sln_text(root: Path, projs: list) -> str:
    out = ["", "Microsoft Visual Studio Solution File, Format Version 12.00", "# Visual Studio Version 17"]
    guids = []
    for p in projs:
        g = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, p.relative_to(root).as_posix())).upper() + "}"
        guids.append(g)
        out += [f'Project("{DOTNET[p.suffix.lower()]}") = "{p.stem}", "{p.relative_to(root).as_posix().replace("/", chr(92))}", "{g}"', "EndProject"]
    out += ["Global", "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution",
            "\t\tDebug|Any CPU = Debug|Any CPU", "\t\tRelease|Any CPU = Release|Any CPU", "\tEndGlobalSection",
            "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution"]
    for g in guids:
        for c in ("Debug", "Release"):
            out += [f"\t\t{g}.{c}|Any CPU.ActiveCfg = {c}|Any CPU", f"\t\t{g}.{c}|Any CPU.Build.0 = {c}|Any CPU"]
    out += ["\tEndGlobalSection", "EndGlobal", ""]
    return "\r\n".join(out)


def _vscode(root: Path, res: Exported) -> Exported:
    s = _project.ProjectSettings.load(root)
    bs = buildsys.detect(root, s)
    tasks = []

    def shell(cmds: list) -> str:
        return " && ".join(buildsys.describe(c) if not (c[:2] == ["bash", "-c"]) else c[2] for c, _ in cmds)
    if bs:
        tasks.append({"label": "Erstellen", "type": "shell", "command": shell(bs.build), "group": {"kind": "build", "isDefault": True}, "problemMatcher": ["$gcc"]})
        if bs.clean:
            tasks.append({"label": "Bereinigen", "type": "shell", "command": shell(bs.clean), "problemMatcher": []})
    if s.run_cmd.strip():
        tasks.append({"label": "Starten", "type": "shell", "command": s.run_cmd.strip(), "problemMatcher": []})
    if s.test_cmd.strip():
        tasks.append({"label": "Testen", "type": "shell", "command": s.test_cmd.strip(), "group": "test", "problemMatcher": []})
    launch = []
    if any((root / p).suffix == ".py" for p in _walk(root, (".py",))):
        startup = s.startup or next((p for p in ("main.py", "app.py", "run.py") if (root / p).is_file()), "${file}")
        cfg = {"name": "Python", "type": "debugpy", "request": "launch", "program": startup if startup == "${file}" else "${workspaceFolder}/" + startup, "console": "integratedTerminal"}
        if s.args:
            cfg["args"] = s.arg_list()
        launch.append(cfg)
    if not tasks and not launch:
        raise ProjectExportError("Es wurde weder ein Build-System noch ein Python-Projekt erkannt.")
    if tasks:
        _write(root / ".vscode" / "tasks.json", json.dumps({"version": "2.0.0", "tasks": tasks}, indent=2, ensure_ascii=False) + "\n", res)
    if launch:
        _write(root / ".vscode" / "launch.json", json.dumps({"version": "0.2.0", "configurations": launch}, indent=2, ensure_ascii=False) + "\n", res)
    return res


def _java_src(root: Path) -> list:
    for cand in ("src/main/java", "src"):
        if (root / cand).is_dir() and any((root / cand).rglob("*.java")):
            return [cand]
    return ["."] if any(p.suffix == ".java" for p in root.glob("*.java")) else []


def _intellij(root: Path, res: Exported) -> Exported:
    name = _name(root)
    java, py = _java_src(root), bool(_walk(root, (".py",)))
    if not java and not py:
        raise ProjectExportError("Für IntelliJ-Produkte braucht das Projekt Java- oder Python-Dateien.")
    mtype = "JAVA_MODULE" if java else "PYTHON_MODULE"
    src = "".join(f'      <sourceFolder url="file://$MODULE_DIR$/{d}" isTestSource="false" />\n' for d in java)
    excl = "".join(f'      <excludeFolder url="file://$MODULE_DIR$/{d}" />\n' for d in (".vds", "venv", ".venv", "build", "node_modules") if (root / d).is_dir())
    iml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<module type="{mtype}" version="4">\n  <component name="NewModuleRootManager" inherit-compiler-output="true">\n'
           f'    <exclude-output />\n    <content url="file://$MODULE_DIR$">\n{src}{excl}    </content>\n    <orderEntry type="inheritedJdk" />\n    <orderEntry type="sourceFolder" forTests="false" />\n  </component>\n</module>\n')
    modules = (f'<?xml version="1.0" encoding="UTF-8"?>\n<project version="4">\n  <component name="ProjectModuleManager">\n    <modules>\n'
               f'      <module fileurl="file://$PROJECT_DIR$/{name}.iml" filepath="$PROJECT_DIR$/{name}.iml" />\n    </modules>\n  </component>\n</project>\n')
    _write(root / f"{name}.iml", iml, res)
    _write(root / ".idea" / "modules.xml", modules, res)
    res.notes.append("In IntelliJ-Produkten den Ordner öffnen; das SDK bzw. den Interpreter wählt die IDE beim ersten Öffnen.")
    return res


def _eclipse(root: Path, res: Exported) -> Exported:
    java = _java_src(root)
    if not java:
        raise ProjectExportError("Für Eclipse braucht das Projekt Java-Quellen.")
    name = _name(root)
    project = (f'<?xml version="1.0" encoding="UTF-8"?>\n<projectDescription>\n\t<name>{name}</name>\n\t<comment></comment>\n\t<projects></projects>\n'
               '\t<buildSpec>\n\t\t<buildCommand>\n\t\t\t<name>org.eclipse.jdt.core.javabuilder</name>\n\t\t\t<arguments></arguments>\n\t\t</buildCommand>\n\t</buildSpec>\n'
               '\t<natures>\n\t\t<nature>org.eclipse.jdt.core.javanature</nature>\n\t</natures>\n</projectDescription>\n')
    entries = "".join(f'\t<classpathentry kind="src" path="{d}"/>\n' for d in java)
    cp = ('<?xml version="1.0" encoding="UTF-8"?>\n<classpath>\n' + entries +
          '\t<classpathentry kind="con" path="org.eclipse.jdt.launching.JRE_CONTAINER"/>\n\t<classpathentry kind="output" path="bin"/>\n</classpath>\n')
    _write(root / ".project", project, res)
    _write(root / ".classpath", cp, res)
    res.notes.append("In Eclipse: Datei → Importieren → Vorhandene Projekte in den Arbeitsbereich.")
    return res


def _zip(root: Path, dest: Path, res: Exported) -> Exported:
    dest = Path(dest).resolve()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if p.is_file() and p.resolve() != dest and not any(part in SKIP_DIRS for part in rel.parts) and not p.name.endswith(".pyc"):
                z.write(p, Path(root.name) / rel)
    res.files.append(dest)
    res.notes.append("Nicht enthalten: .vds, .git, venv, node_modules, build, bin, obj, target, dist.")
    return res
