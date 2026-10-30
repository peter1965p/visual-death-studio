"""Import fremder Projekte: Qt Creator (.pro, CMake), Visual Studio (.sln, .csproj, .vcxproj), Code::Blocks (.cbp), Maven, Gradle …

Das Projekt bleibt, wo es ist. Die IDE legt nur `.vds/project.json` an (Build-/Start-Befehl) und, wo das Build-System nicht
selbst gebaut werden kann (.vcxproj, .cbp, .pro ohne qmake), eine abgeleitete CMake-Datei unter `.vds/import/`."""
import re
import shlex
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ..project import ProjectSettings

# Reihenfolge = Vorrang bei der Suche in einem Ordner
PATTERNS = ("*.sln", "*.pro", "CMakeLists.txt", "*.csproj", "*.fsproj", "*.vbproj", "*.vcxproj", "*.cbp", "pom.xml", "build.gradle", "build.gradle.kts")
FILE_FILTER = "Projekte (*.sln *.pro *.csproj *.fsproj *.vbproj *.vcxproj *.cbp CMakeLists.txt pom.xml build.gradle build.gradle.kts);;Alle Dateien (*)"
SLN_FOLDER = "{2150E333-8FDC-42A3-9474-1A3956D46DE8}"      # Projektmappen-Ordner, kein echtes Projekt
IGNORED_DEFINES = {"WIN32", "_WINDOWS", "_CONSOLE", "_DEBUG", "NDEBUG", "_UNICODE", "UNICODE"}
GEN = Path(".vds") / "import"
BUILD = Path(".vds") / "build"


class ProjectImportError(Exception):
    pass


@dataclass
class Imported:
    root: Path
    kind: str
    notes: list = field(default_factory=list)
    build_cmd: str = ""
    clean_cmd: str = ""
    run_cmd: str = ""
    source: Path | None = None

    def apply(self) -> ProjectSettings:
        """Schreibt .vds/project.json; bereits eingetragene Befehle des Benutzers bleiben unangetastet."""
        s = ProjectSettings.load(self.root)
        for name in ("build_cmd", "clean_cmd", "run_cmd"):
            if getattr(self, name) and not getattr(s, name).strip():
                setattr(s, name, getattr(self, name))
        s.save(self.root)
        return s


def find_project(path: Path) -> Path:
    """Projektdatei zu einer Datei oder einem Ordner; ein Ordner wird nach bekannten Projektdateien durchsucht."""
    path = Path(path)
    if path.is_file():
        return path
    if not path.is_dir():
        raise ProjectImportError(f"{path} gibt es nicht.")
    for pat in PATTERNS:
        hits = sorted(path.glob(pat))
        if hits:
            return hits[0]
    raise ProjectImportError(f"In {path.name} wurde keine Projektdatei gefunden (.sln, .pro, CMakeLists.txt, .csproj, .vcxproj, .cbp, pom.xml, build.gradle).")


def import_project(path: Path) -> Imported:
    f = find_project(path)
    n = f.name.lower()
    if n.endswith(".sln"):
        return _sln(f)
    if n.endswith(".pro"):
        return _qmake(f)
    if n == "cmakelists.txt":
        return _cmake(f)
    if n.endswith((".csproj", ".fsproj", ".vbproj")):
        return _dotnet_project(f)
    if n.endswith(".vcxproj"):
        return _vcxproj(f)
    if n.endswith(".cbp"):
        return _codeblocks(f)
    if n == "pom.xml":
        return Imported(f.parent, "Maven", _ide_notes(f.parent), source=f)
    if n.startswith("build.gradle"):
        return Imported(f.parent, "Gradle", _ide_notes(f.parent), source=f)
    raise ProjectImportError(f"{f.name} ist kein bekannter Projekttyp.")


def _ide_notes(root: Path) -> list:
    notes = []
    for marker, ide in ((".idea", "IntelliJ/CLion"), (".project", "Eclipse"), (".vscode", "VS Code"), (".vs", "Visual Studio")):
        if (root / marker).exists():
            notes.append(f"{ide}-Einstellungen ({marker}) bleiben unberührt; Build und Start erkennt die IDE selbst.")
    return notes


def _q(p) -> str:
    return shlex.quote(str(p))


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _xml(path: Path):
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        raise ProjectImportError(f"{path.name} lässt sich nicht lesen: {e}") from e


def _children(root, name: str):
    return [e for e in root.iter() if _tag(e) == name]


def _text(root, name: str, default: str = "") -> str:
    for e in _children(root, name):
        if e.text and e.text.strip():
            return e.text.strip()
    return default


# --- Qt Creator: qmake (.pro) -------------------------------------------------------------------------------
def parse_pro(text: str) -> dict:
    """Variablen einer .pro-Datei (=, +=, -=); Fortsetzungszeilen und Kommentare werden aufgelöst, Bedingungsblöcke ignoriert."""
    text = re.sub(r"\\\s*\n", " ", text)
    v: dict = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"^([A-Za-z_][\w.]*)\s*(\+=|-=|\*=|=)\s*(.*)$", line)
        if not m:
            continue
        key, op, val = m.groups()
        items = shlex.split(val) if val.count('"') % 2 == 0 else val.split()
        if op == "=":
            v[key] = items
        elif op == "-=":
            v[key] = [i for i in v.get(key, []) if i not in items]
        else:
            v.setdefault(key, []).extend(i for i in items if i not in v.get(key, []))
    return v


def _qmake(f: Path) -> Imported:
    root = f.parent
    v = parse_pro(f.read_text(encoding="utf-8", errors="replace"))
    template = (v.get("TEMPLATE") or ["app"])[0]
    target = (v.get("TARGET") or [f.stem])[0]
    notes = _ide_notes(root)
    if (root / (f.name + ".user")).exists():
        notes.append(f"{f.name}.user (Qt-Creator-Kits) wird nicht ausgewertet.")
    qmake = shutil.which("qmake6") or shutil.which("qmake")
    if qmake:
        b = BUILD
        build = f"mkdir -p {_q(b)} && cd {_q(b)} && {qmake} {_q('../../' + f.name)} && make -j$(nproc)"
        run = f"{build} && cd {_q(root)} && {_q(b / target)}" if template == "app" else ""
        return Imported(root, "Qt Creator (qmake)", notes, build, f"rm -rf {_q(b)}", run, f)
    if template == "subdirs":
        raise ProjectImportError("Für ein qmake-Projekt mit mehreren Unterprojekten (TEMPLATE = subdirs) wird qmake benötigt (Arch: qt6-base, Paket enthält qmake6).")
    notes.append("qmake ist nicht installiert: Die IDE baut mit einer aus der .pro abgeleiteten CMake-Datei (.vds/import/CMakeLists.txt).")
    qt = ["Core"]
    for m in v.get("QT", []):
        if m == "gui" or m == "core":
            continue
        comp = {"printsupport": "PrintSupport", "testlib": "Test", "opengl": "OpenGL", "openglwidgets": "OpenGLWidgets", "uitools": "UiTools"}.get(m, m.capitalize())
        qt.append(comp)
    if "widgets" in v.get("QT", []) or v.get("FORMS"):
        qt.append("Widgets")
    qt.insert(1, "Gui")
    srcs = [*v.get("SOURCES", []), *v.get("HEADERS", []), *v.get("FORMS", []), *v.get("RESOURCES", [])]
    cmake = _cmake_text(target, "app" if template == "app" else "lib", srcs, qt=list(dict.fromkeys(qt)), defines=v.get("DEFINES", []),
                        includes=v.get("INCLUDEPATH", []), std=_std_from_config(v.get("CONFIG", [])))
    return _generated(root, "Qt Creator (qmake)", notes, cmake, target, template == "app", f)


def _std_from_config(config: list) -> str:
    for c in config:
        m = re.fullmatch(r"c\+\+(\d\d)", c)
        if m:
            return m.group(1)
    return "17"


# --- CMake (Qt Creator, CLion, VS Code …) -------------------------------------------------------------------
def _cmake(f: Path) -> Imported:
    root = f.parent
    text = f.read_text(encoding="utf-8", errors="replace")
    qt = bool(re.search(r"find_package\s*\(\s*Qt\d?", text, re.I))
    kind = "Qt Creator (CMake)" if qt or (root / "CMakeLists.txt.user").exists() else "CMake"
    notes = _ide_notes(root)
    if (root / "CMakeLists.txt.user").exists():
        notes.append("CMakeLists.txt.user (Qt-Creator-Kits) wird nicht ausgewertet; gebaut wird nach build/.")
    exes = re.findall(r"add_executable\s*\(\s*([\w.${}-]+)", text, re.I)
    build = "cmake -S . -B build && cmake --build build -j"
    run = f"{build} && {_q('build/' + exes[0])}" if exes and "$" not in exes[0] else ""
    if exes and "$" in exes[0]:
        notes.append("Der Programmname in add_executable ist eine Variable; Startbefehl bitte unter Projekt → Eigenschaften eintragen.")
    return Imported(root, kind, notes, "", "", run, f)


# --- Visual Studio ------------------------------------------------------------------------------------------
def _dotnet_run(proj: Path, root: Path) -> tuple:
    """(Startbefehl oder '', Hinweis) für ein .NET-Projekt."""
    x = _xml(proj)
    out = _text(x, "OutputType", "Library")
    tfm = _text(x, "TargetFramework") + _text(x, "TargetFrameworks")
    windows = "windows" in tfm or _text(x, "UseWPF").lower() == "true" or _text(x, "UseWindowsForms").lower() == "true"
    legacy = bool(_children(x, "TargetFrameworkVersion"))
    note = ""
    if legacy:
        note = f"{proj.name} ist im alten .NET-Framework-Format; zum Bauen unter Linux muss es auf SDK-Stil (net8.0 o. ä.) umgestellt werden."
    elif windows:
        note = f"{proj.name} nutzt WPF/Windows Forms und läuft nur unter Windows."
    if out.lower() not in ("exe", "winexe") or legacy or windows:
        return "", note
    return f"dotnet run --project {_q(proj.relative_to(root))}", note


def _dotnet_project(f: Path) -> Imported:
    cmd, note = _dotnet_run(f, f.parent)
    return Imported(f.parent, ".NET", [n for n in (note, *_ide_notes(f.parent)) if n], "", "", cmd, f)


def parse_sln(f: Path) -> list:
    """[(Name, Pfad relativ zur .sln, Typ-GUID)] aller echten Projekte."""
    out = []
    text = f.read_text(encoding="utf-8-sig", errors="replace")
    for m in re.finditer(r'Project\("(\{[^}]+\})"\)\s*=\s*"([^"]*)"\s*,\s*"([^"]*)"', text):
        guid, name, rel = m.groups()
        if guid.upper() != SLN_FOLDER:
            out.append((name, rel.replace("\\", "/"), guid.upper()))
    return out


def _sln(f: Path) -> Imported:
    root = f.parent
    projects = parse_sln(f)
    if not projects:
        raise ProjectImportError(f"{f.name} enthält keine Projekte.")
    notes = _ide_notes(root)
    net = [(n, root / r) for n, r, _ in projects if r.lower().endswith((".csproj", ".fsproj", ".vbproj"))]
    cpp = [(n, root / r) for n, r, _ in projects if r.lower().endswith(".vcxproj")]
    skipped = [n for n, r, _ in projects if not r.lower().endswith((".csproj", ".fsproj", ".vbproj", ".vcxproj"))]
    if skipped:
        notes.append("Nicht unterstützte Projekte übersprungen: " + ", ".join(skipped))
    if net and not cpp:
        run = ""
        for n, p in net:
            if p.is_file():
                cmd, note = _dotnet_run(p, root)
                if note:
                    notes.append(note)
                run = run or cmd
        notes.append(f"{len(net)} .NET-Projekt(e); Erstellen baut die ganze Projektmappe.")
        return Imported(root, "Visual Studio (.NET)", notes, "", "", run, f)
    if cpp:
        notes.append("C++-Projekte (.vcxproj) werden über eine abgeleitete CMake-Datei gebaut; MSVC-spezifische Einstellungen und Windows-APIs werden nicht übernommen.")
        if net:
            notes.append(".NET-Projekte der Mappe werden dabei nicht mitgebaut: " + ", ".join(n for n, _ in net))
        items = [_vcx_info(p) for _, p in cpp if p.is_file()]
        if not items:
            raise ProjectImportError("Die .vcxproj-Dateien der Mappe fehlen.")
        return _generated_multi(root, "Visual Studio (C++)", notes, items, f)
    raise ProjectImportError("Die Projektmappe enthält keine unterstützten Projekte (.csproj, .vcxproj).")


def _vcx_info(f: Path) -> dict:
    x = _xml(f)
    d = f.parent
    srcs = [e.get("Include", "") for tag in ("ClCompile", "ClInclude", "ResourceCompile") for e in _children(x, tag) if e.get("Include")]
    srcs = [s.replace("\\", "/") for s in srcs if not s.startswith("$(")]
    kind = _text(x, "ConfigurationType", "Application")
    inc, defs = [], []
    for e in _children(x, "AdditionalIncludeDirectories"):
        for i in (e.text or "").split(";"):
            i = i.strip().replace("\\", "/").replace("$(ProjectDir)", "").replace("$(SolutionDir)", "../")
            if i and "$(" not in i and "%(" not in i:
                inc.append(i)
    for e in _children(x, "PreprocessorDefinitions"):
        for i in (e.text or "").split(";"):
            i = i.strip()
            if i and "%(" not in i and "$(" not in i and i not in IGNORED_DEFINES:
                defs.append(i)
    std = "17"
    m = re.search(r"stdcpp(\d\d)", _text(x, "LanguageStandard"))
    if m:
        std = m.group(1)
    return {"name": _text(x, "ProjectName") or f.stem, "dir": d, "sources": list(dict.fromkeys(srcs)),
            "type": {"StaticLibrary": "static", "DynamicLibrary": "shared"}.get(kind, "app"),
            "includes": list(dict.fromkeys(inc)), "defines": list(dict.fromkeys(defs)), "std": std}


def _vcxproj(f: Path) -> Imported:
    info = _vcx_info(f)
    notes = _ide_notes(f.parent) + ["C++-Projekt (.vcxproj) wird über eine abgeleitete CMake-Datei gebaut; MSVC-spezifische Einstellungen und Windows-APIs werden nicht übernommen."]
    return _generated_multi(f.parent, "Visual Studio (C++)", notes, [info], f)


# --- Code::Blocks -------------------------------------------------------------------------------------------
def _codeblocks(f: Path) -> Imported:
    x = _xml(f)
    title = next((e.get("title") for e in _children(x, "Option") if e.get("title")), None) or f.stem
    srcs = [e.get("filename", "").replace("\\", "/") for e in _children(x, "Unit") if e.get("filename")]
    srcs = [s for s in srcs if s.lower().endswith((".c", ".cpp", ".cc", ".cxx", ".h", ".hpp"))]
    if not srcs:
        raise ProjectImportError(f"{f.name} enthält keine Quelldateien.")
    kind_opt = next((e.get("type") for e in _children(x, "Option") if e.get("type") is not None), "1")
    ttype = {"2": "shared", "3": "static"}.get(kind_opt, "app")
    info = {"name": title, "dir": f.parent, "sources": srcs, "type": ttype, "includes": [], "defines": [], "std": "17"}
    return _generated_multi(f.parent, "Code::Blocks", ["Abgeleitete CMake-Datei unter .vds/import/; Compiler-Optionen des Projekts werden nicht übernommen."], [info], f)


# --- CMake-Erzeugung ------------------------------------------------------------------------------------------
def _cmake_text(name, kind, srcs, qt=None, defines=(), includes=(), std="17", base="") -> str:
    """CMake für ein Ziel; Pfade sind relativ zum Projektordner (${ROOT}), `base` ist der Unterordner des Projekts."""
    p = (base.rstrip("/") + "/") if base else ""
    lines = [f"cmake_minimum_required(VERSION 3.16)", f"project({name} LANGUAGES C CXX)", f"set(CMAKE_CXX_STANDARD {std})", "set(CMAKE_CXX_STANDARD_REQUIRED ON)"]
    if qt:
        lines += ["set(CMAKE_AUTOMOC ON)", "set(CMAKE_AUTOUIC ON)", "set(CMAKE_AUTORCC ON)", f"find_package(Qt6 REQUIRED COMPONENTS {' '.join(qt)})"]
    return "\n".join(lines) + "\n" + _target_text(name, kind, srcs, qt, defines, includes, p)


def _target_text(name, kind, srcs, qt, defines, includes, p) -> str:
    files = " ".join(f'"${{ROOT}}/{p}{s}"' for s in srcs if not s.startswith("$"))
    add = {"app": "add_executable", "static": "add_library", "shared": "add_library", "lib": "add_library"}[kind]
    extra = {"static": " STATIC", "shared": " SHARED"}.get(kind, "")
    out = f"set(ROOT \"${{CMAKE_CURRENT_LIST_DIR}}/../..\")\n{add}({name}{extra} {files})\n"
    out += f'target_include_directories({name} PRIVATE "${{ROOT}}/{p}")\n'
    for i in includes:
        if not i.startswith("$"):
            out += f'target_include_directories({name} PRIVATE "${{ROOT}}/{p}{i}")\n'
    ds = [d for d in defines if not d.startswith("$")]
    if ds:
        out += f"target_compile_definitions({name} PRIVATE {' '.join(ds)})\n"
    if qt:
        out += f"target_link_libraries({name} PRIVATE {' '.join('Qt6::' + c for c in qt)})\n"
    return out


def _generated(root, kind, notes, cmake, target, is_app, src) -> Imported:
    g = root / GEN
    g.mkdir(parents=True, exist_ok=True)
    (g / "CMakeLists.txt").write_text(cmake, encoding="utf-8")
    build = f"cmake -S {_q(GEN)} -B {_q(BUILD)} && cmake --build {_q(BUILD)} -j"
    run = f"{build} && cd {_q(root)} && {_q(BUILD / target)}" if is_app else ""
    return Imported(root, kind, notes, build, f"rm -rf {_q(BUILD)}", run, src)


def _generated_multi(root: Path, kind: str, notes: list, items: list, src: Path) -> Imported:
    head = ["cmake_minimum_required(VERSION 3.16)", f"project({_ident(src.stem)} LANGUAGES C CXX)",
            f"set(CMAKE_CXX_STANDARD {items[0]['std']})", "set(CMAKE_CXX_STANDARD_REQUIRED ON)"]
    body = ""
    first_app = None
    for it in items:
        name = _ident(it["name"])
        base = it["dir"].relative_to(root).as_posix()
        base = "" if base == "." else base
        body += _target_text(name, it["type"], it["sources"], None, it["defines"], it["includes"], (base + "/") if base else "")
        if it["type"] == "app" and not first_app:
            first_app = name
    cmake = "\n".join(head) + "\n" + body
    return _generated(root, kind, notes, cmake, first_app or "", bool(first_app), src)


def _ident(s: str) -> str:
    return re.sub(r"[^\w]", "_", s) or "app"
