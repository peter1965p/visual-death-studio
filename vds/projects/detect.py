"""Versteht einen Projektordner: Welche Techniken stecken drin, was lässt sich starten, was gibt es an Aufgaben?

Liest nur Dateien und führt nichts aus; die Befehle laufen erst, wenn jemand sie anklickt. Ein Ordner kann mehreres zugleich sein
(Laravel + Vite + Docker), und Unterprojekte wie frontend/ oder packages/* werden mit erkannt."""
import json
import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..project import ProjectSettings
from ..web import devserver

SUBPROJECT_PARENTS = ("packages", "apps", "services", "crates", "modules")
SKIP_DIRS = {"node_modules", "vendor", "venv", "build", "dist", "target", "bin", "obj", "public", "resources", "storage", "bootstrap", "config", "database",
             "routes", "tests", "test", "docs", "lang", "__pycache__", "src", "lib", "app", "assets", "static", "cmake-build-debug"}
MAKE_TARGET = re.compile(r"^([A-Za-z0-9][\w.-]*)\s*:(?!=)", re.M)
JUST_RECIPE = re.compile(r"^@?([a-zA-Z_][\w-]*)(?:\s+[^:=\n]*)?:(?!=)", re.M)
RUN_WORDS = {"run", "dev", "serve", "server", "start", "watch"}
_JS, _PY, _PHP = {"javascript", "typescript"}, {"python"}, {"php"}
# Welche Dateien zu einem Ziel gehören. Eine Datei einer anderen Sprache (tool.py im Node-Projekt) startet sich selbst, solange niemand das Ziel ausdrücklich gewählt hat.
GROUP_LANGS = {"Projekt": None, "Laravel": _PHP, "Symfony": _PHP, "WordPress": _PHP, "PHP": _PHP, "Composer": _PHP, "npm": _JS, "pnpm": _JS, "yarn": _JS, "bun": _JS, "Deno": _JS, "Node.js": _JS,
               "Python": _PY, "Django": _PY, "FastAPI": _PY, "Flask": _PY, "Streamlit": _PY, "Cargo": {"rust"}, "Go": {"go"}, ".NET": {"csharp"}, "Maven": {"java"}, "Gradle": {"java"},
               "Android": {"java"}, "CMake": {"c", "cpp"}}
MAX_PER_FILE = 30                                     # mehr Einträge aus einem Makefile o. Ä. wären keine Hilfe mehr


@dataclass(frozen=True)
class Target:
    name: str
    cmd: str
    kind: str                                         # server | run | build | test | task
    cwd: Path
    group: str = ""
    tool: str = ""                                    # benötigtes Programm; leer = erstes Wort des Befehls
    primary: bool = False                             # gute Standardwahl für den Start-Knopf
    file: str = ""                                    # Python-Skript, das F5 im Debugger startet

    @property
    def key(self) -> str:
        return f"{self.cwd}::{self.cmd}"

    @property
    def startable(self) -> bool:
        return self.kind in ("server", "run")

    def covers(self, lang_id: str) -> bool:
        """Gehört eine Datei dieser Sprache zum Ziel? Ein eigener Startbefehl gilt für alle."""
        langs = GROUP_LANGS.get(self.group, set())
        return langs is None or lang_id in langs

    def missing_tool(self) -> str | None:
        tool = self.tool or self.cmd.split()[0]
        return tool if not tool.startswith((".", "/")) and "=" not in tool and not shutil.which(tool) else None


@dataclass
class ProjectInfo:
    root: Path
    stacks: list = field(default_factory=list)
    targets: list = field(default_factory=list)

    @property
    def startable(self) -> list:
        return [t for t in self.targets if t.startable]

    @property
    def tasks(self) -> list:
        return [t for t in self.targets if not t.startable]

    @property
    def default(self) -> Target | None:
        return next((t for t in self.targets if t.primary), None)

    def find(self, key: str) -> Target | None:
        return next((t for t in self.targets if t.key == key), None)

    def signature(self) -> tuple:
        return tuple(self.stacks), tuple(self.targets)


class _Scan:
    """Sammelt für einen Ordner; `prefix` kennzeichnet Unterprojekte in den Namen."""

    def __init__(self, info: ProjectInfo, folder: Path, prefix: str = ""):
        self.info, self.dir, self.prefix = info, folder, prefix

    def stack(self, *names):
        for n in names:
            if n and n not in self.info.stacks:
                self.info.stacks.append(n)

    def add(self, name: str, cmd: str, kind: str = "task", group: str = "", tool: str = "", primary: bool = False, file: str = ""):
        if any(t.cmd == cmd and t.cwd == self.dir for t in self.info.targets):
            return
        label = f"{self.prefix}: {name}" if self.prefix else name
        self.info.targets.append(Target(label, cmd, kind, self.dir, group, tool, primary and not self.prefix, file))

    def has(self, *names) -> bool:
        return any((self.dir / n).exists() for n in names)

    def text(self, name: str) -> str:
        try:
            return (self.dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def json(self, name: str) -> dict:
        try:
            data = json.loads(self.text(name))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def toml(self, name: str) -> dict:
        try:
            return tomllib.loads(self.text(name))
        except ValueError:
            return {}


# --- Web und Skriptsprachen ---------------------------------------------------------------------------------
def _php(s: _Scan):
    composer = s.json("composer.json")
    require = {**composer.get("require", {}), **composer.get("require-dev", {})} if composer else {}
    plain_index = s.has("index.php", "public/index.php")
    if not composer and not plain_index:
        return
    install = "[ -d vendor ] || composer install; " if composer else ""
    tool = "php"
    ini = 'PHP_INI_SCAN_DIR=":$PWD/.vds/php" ' if s.has(".vds/php") else ""      # vom Projekt-Assistenten angelegt, wenn dem System-PHP Treiber wie SQLite fehlen
    if s.has("artisan"):
        s.stack("Laravel")
        s.add("Laravel-Server", install + ini + (devserver.detect_command(s.dir) or "php artisan serve"), "server", "Laravel", tool, primary=True)
        s.add("Tests (artisan test)", ini + "php artisan test", "test", "Laravel", tool)
        s.add("Migrationen ausführen", ini + "php artisan migrate", "task", "Laravel", tool)
        s.add("Routen anzeigen", ini + "php artisan route:list", "task", "Laravel", tool)
        s.add("Warteschlange abarbeiten", ini + "php artisan queue:work", "task", "Laravel", tool)
        s.add("Cache leeren", ini + "php artisan optimize:clear", "task", "Laravel", tool)
    elif s.has("bin/console"):
        s.stack("Symfony")
        s.add("PHP-Server", install + "php -S localhost:8000 -t public", "server", "Symfony", tool, primary=True)
        s.add("Cache leeren", "php bin/console cache:clear", "task", "Symfony", tool)
    elif s.has("wp-config.php", "wp-config-sample.php"):
        s.stack("WordPress")
        s.add("PHP-Server", "php -S localhost:8000", "server", "WordPress", tool, primary=True)
    elif plain_index:
        s.stack("PHP")
        s.add("PHP-Server", install + ("php -S localhost:8000 -t public" if s.has("public/index.php") else "php -S localhost:8000"), "server", "PHP", tool, primary=True)
    else:
        s.stack("PHP")
    for script, body in composer.get("scripts", {}).items():
        if not script.startswith(("pre-", "post-")) and not script.startswith("_"):
            kind = "server" if script in ("dev", "serve", "start") else "test" if script == "test" else "task"
            s.add(f"composer {script}", f"composer {script}", kind, "Composer")
    if "phpunit/phpunit" in require and not s.has("artisan"):
        s.add("Tests (PHPUnit)", "vendor/bin/phpunit", "test", "PHP", tool)
    for package, name, cmd in (("laravel/pint", "Code formatieren (Pint)", "vendor/bin/pint"), ("phpstan/phpstan", "Statische Analyse (PHPStan)", "vendor/bin/phpstan analyse")):
        if package in require:
            s.add(name, cmd, "task", "PHP", tool)


NODE_STACKS = (("next", "Next.js"), ("nuxt", "Nuxt"), ("@angular/core", "Angular"), ("astro", "Astro"), ("@remix-run/react", "Remix"), ("svelte", "Svelte"),
               ("vue", "Vue"), ("react", "React"), ("@nestjs/core", "NestJS"), ("express", "Express"), ("electron", "Electron"), ("@tauri-apps/api", "Tauri"), ("vite", "Vite"))


NPM_LIFECYCLE = {"preinstall", "install", "postinstall", "prepare", "prepublish", "prepublishOnly", "prepack", "postpack"}


def _node(s: _Scan):
    pkg = s.json("package.json")
    if s.has("deno.json", "deno.jsonc"):
        s.stack("Deno")
        for name in s.json("deno.json").get("tasks", {}):
            s.add(f"deno task {name}", f"deno task {name}", "server" if name in RUN_WORDS else "task", "Deno", primary=name in ("dev", "start"))
    if not pkg:
        return
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    s.stack(*[label for dep, label in NODE_STACKS if dep in deps] or ["Node.js"])
    manager = "pnpm" if s.has("pnpm-lock.yaml") else "yarn" if s.has("yarn.lock") else "bun" if s.has("bun.lockb", "bun.lock") else "npm"
    prefix = f"[ -d node_modules ] || {manager} install; "
    scripts = pkg.get("scripts", {})
    lead = next((n for n in ("dev", "start", "serve") if n in scripts), None)
    for name in scripts:
        if name in NPM_LIFECYCLE or (name.startswith(("pre", "post")) and name[3 if name.startswith("pre") else 4:] in scripts):
            continue                                  # läuft von selbst vor bzw. nach dem eigentlichen Skript
        run = f"{manager} run {name}"
        low = name.lower()
        if name == lead or low in RUN_WORDS:
            s.add(run, prefix + run, "server", manager, manager, primary=name == lead)
        elif low.startswith("test") or low == "e2e":
            s.add(run, prefix + run, "test", manager, manager)
        elif low.startswith("build"):
            s.add(run, prefix + run, "build", manager, manager)
        else:
            s.add(run, prefix + run, "task", manager, manager)
    if not scripts and pkg.get("main") and s.has(pkg["main"]):
        s.add(f"node {pkg['main']}", f"node {pkg['main']}", "run", "Node.js", primary=True)


def _python_runner(s: _Scan, settings: ProjectSettings) -> tuple:
    """(Befehl für `python`, Präfix für installierte Programme)."""
    if s.has("uv.lock"):
        return "uv run python", "uv run "
    if s.has("poetry.lock"):
        return "poetry run python", "poetry run "
    if s.has("Pipfile"):
        return "pipenv run python", "pipenv run "
    if settings.python:
        return settings.python, ""
    for venv in (".venv", "venv"):
        if s.has(f"{venv}/bin/python"):
            return f"{venv}/bin/python", f"{venv}/bin/"
    return "python3", ""


def _python(s: _Scan, settings: ProjectSettings):
    markers = s.has("pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "manage.py")
    mains = [n for n in ("main.py", "run.py", "app.py") if s.has(n)]
    packages = sorted(p.parent.name for p in s.dir.glob("*/__main__.py"))        # python -m paket
    if not markers and not mains and not packages:
        return
    s.stack("Python")
    meta = s.text("pyproject.toml") + s.text("requirements.txt") + s.text("requirements-dev.txt") + s.text("Pipfile")
    meta = meta.lower()
    py, bin_prefix = _python_runner(s, settings)
    tool = "." if "/" in py else py.split()[0]         # ein Pfad im Projekt braucht keine PATH-Prüfung, siehe missing_tool
    use = lambda program: f"{bin_prefix}{program}" if bin_prefix else f"{py} -m {program}"
    if s.has("manage.py"):
        s.stack("Django")
        s.add("Django-Server", f"{py} manage.py runserver", "server", "Django", tool, primary=True)
        s.add("Tests (manage.py test)", f"{py} manage.py test", "test", "Django", tool)
        s.add("Migrationen ausführen", f"{py} manage.py migrate", "task", "Django", tool)
    fastapi = next((f for f in ("main.py", "app.py", "app/main.py", "src/main.py") if "FastAPI(" in s.text(f)), None)
    if fastapi:
        s.stack("FastAPI")
        module = fastapi.removesuffix(".py").replace("/", ".")
        s.add("FastAPI-Server", f"{use('uvicorn')} {module}:app --reload", "server", "FastAPI", tool, primary=True)
    elif "flask" in meta and s.has("app.py", "wsgi.py"):
        s.stack("Flask")
        s.add("Flask-Server", f"{use('flask')} run --debug", "server", "Flask", tool, primary=True)
    if "streamlit" in meta and mains:
        s.stack("Streamlit")
        s.add("Streamlit", f"{use('streamlit')} run {mains[0]}", "server", "Streamlit", tool, primary=True)
    for main in mains:
        s.add(main, f"{py} -u {main}", "run", "Python", tool, primary=True, file=main)
    for package in packages[:MAX_PER_FILE]:
        s.add(f"python -m {package}", f"{py} -u -m {package}", "run", "Python", tool, primary=not mains and package == packages[0])
    scripts = s.toml("pyproject.toml").get("project", {}).get("scripts", {}) if s.has("pyproject.toml") else {}
    for name in list(scripts)[:MAX_PER_FILE]:
        if bin_prefix:
            s.add(name, f"{bin_prefix}{name}", "run", "Python", tool)
    if "pytest" in meta or s.has("pytest.ini", "conftest.py", "tests/conftest.py"):
        s.add("Tests (pytest)", use("pytest"), "test", "Python", tool)
    elif s.has("tests"):
        s.add("Tests (unittest)", f"{py} -m unittest discover", "test", "Python", tool)
    for package, name, cmd in (("ruff", "Code prüfen (ruff)", "ruff check ."), ("mypy", "Typen prüfen (mypy)", "mypy ."), ("black", "Code formatieren (black)", "black .")):
        if package in meta:
            s.add(name, use(cmd), "task", "Python", tool)
    if s.has("pyproject.toml", "setup.py"):
        s.add("Paket bauen", f"{py} -m build", "build", "Python", tool)


def _ruby(s: _Scan):
    if not s.has("Gemfile"):
        return
    s.stack("Ruby")
    gems = s.text("Gemfile")
    if s.has("bin/rails"):
        s.stack("Rails")
        s.add("Rails-Server", "bin/rails server", "server", "Rails", "ruby", primary=True)
        s.add("Tests (rails test)", "bin/rails test", "test", "Rails", "ruby")
        s.add("Migrationen ausführen", "bin/rails db:migrate", "task", "Rails", "ruby")
    elif s.has("config.ru"):
        s.add("Rack-Server", "bundle exec rackup", "server", "Ruby", "bundle", primary=True)
    if "rspec" in gems:
        s.add("Tests (RSpec)", "bundle exec rspec", "test", "Ruby", "bundle")
    s.add("Gems installieren", "bundle install", "task", "Ruby")


def _elixir(s: _Scan):
    if not s.has("mix.exs"):
        return
    s.stack("Elixir")
    if "phoenix" in s.text("mix.exs"):
        s.stack("Phoenix")
        s.add("Phoenix-Server", "mix phx.server", "server", "Phoenix", primary=True)
    s.add("mix compile", "mix compile", "build", "Elixir")
    s.add("mix test", "mix test", "test", "Elixir")


# --- Kompilierte Sprachen -----------------------------------------------------------------------------------
def _rust(s: _Scan):
    if not s.has("Cargo.toml"):
        return
    s.stack("Rust")
    cargo = s.toml("Cargo.toml")
    bins = [b["name"] for b in cargo.get("bin", []) if b.get("name")] + sorted(p.stem for p in (s.dir / "src" / "bin").glob("*.rs"))
    if bins:
        for name in bins[:MAX_PER_FILE]:
            s.add(f"cargo run --bin {name}", f"cargo run --bin {name}", "run", "Cargo", primary=name == bins[0])
    elif s.has("src/main.rs"):
        s.add("cargo run", "cargo run", "run", "Cargo", primary=True)
        s.add("cargo run --release", "cargo run --release", "run", "Cargo")
    s.add("cargo build", "cargo build", "build", "Cargo")
    s.add("cargo build --release", "cargo build --release", "build", "Cargo")
    s.add("cargo test", "cargo test", "test", "Cargo")
    s.add("cargo clippy", "cargo clippy", "task", "Cargo")
    s.add("cargo fmt", "cargo fmt", "task", "Cargo")


def _go(s: _Scan):
    if not s.has("go.mod"):
        return
    s.stack("Go")
    commands = sorted(p.parent.name for p in (s.dir / "cmd").glob("*/main.go"))
    if s.has("main.go"):
        s.add("go run .", "go run .", "run", "Go", primary=True)
    for name in commands[:MAX_PER_FILE]:
        s.add(f"go run ./cmd/{name}", f"go run ./cmd/{name}", "run", "Go", primary=not s.has("main.go") and name == commands[0])
    s.add("go build", "go build ./...", "build", "Go")
    s.add("go test", "go test ./...", "test", "Go")
    s.add("go vet", "go vet ./...", "task", "Go")


def _dotnet(s: _Scan):
    projects = sorted(s.dir.glob("*.csproj")) + sorted(s.dir.glob("*.fsproj")) + sorted(s.dir.glob("*/*.csproj")) + sorted(s.dir.glob("*/*.fsproj"))
    solutions = sorted(s.dir.glob("*.sln"))
    if not projects and not solutions:
        return
    s.stack(".NET")
    first = True
    for proj in projects[:MAX_PER_FILE]:
        try:
            text = proj.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "<OutputType>Exe" in text or "<OutputType>WinExe" in text or 'Sdk="Microsoft.NET.Sdk.Web"' in text:
            rel = proj.relative_to(s.dir).as_posix()
            server = 'Sdk="Microsoft.NET.Sdk.Web"' in text
            s.add(f"dotnet run ({proj.stem})", f"dotnet run --project {rel}", "server" if server else "run", ".NET", primary=first)
            s.add(f"dotnet watch ({proj.stem})", f"dotnet watch --project {rel}", "server", ".NET")
            first = False
    s.add("dotnet build", "dotnet build", "build", ".NET")
    s.add("dotnet test", "dotnet test", "test", ".NET")
    s.add("dotnet format", "dotnet format", "task", ".NET")


def _java(s: _Scan):
    if s.has("pom.xml"):
        mvn = "./mvnw" if s.has("mvnw") else "mvn"
        tool = "java" if mvn == "./mvnw" else "mvn"
        s.stack("Maven", "Spring Boot" if "spring-boot" in s.text("pom.xml") else "")
        if "spring-boot" in s.text("pom.xml"):
            s.add("Spring-Boot-Server", f"{mvn} spring-boot:run", "server", "Maven", tool, primary=True)
        s.add("mvn compile", f"{mvn} compile", "build", "Maven", tool)
        s.add("mvn package", f"{mvn} package", "build", "Maven", tool)
        s.add("mvn test", f"{mvn} test", "test", "Maven", tool)
    script = "build.gradle.kts" if s.has("build.gradle.kts") else "build.gradle" if s.has("build.gradle") else ""
    if not script:
        return
    gradle = "./gradlew" if s.has("gradlew") else "gradle"
    tool = "java" if gradle == "./gradlew" else "gradle"
    text = s.text(script)
    s.stack("Gradle", "Kotlin" if script.endswith(".kts") or "kotlin" in text else "")
    if "com.android.application" in text or s.has("app/build.gradle", "app/build.gradle.kts") and "com.android" in s.text("app/build.gradle") + s.text("app/build.gradle.kts"):
        s.stack("Android")
        s.add("App auf Gerät installieren", f"{gradle} installDebug", "run", "Android", tool, primary=True)
        s.add("Debug-APK bauen", f"{gradle} assembleDebug", "build", "Android", tool)
    if "org.springframework.boot" in text:
        s.stack("Spring Boot")
        s.add("Spring-Boot-Server", f"{gradle} bootRun", "server", "Gradle", tool, primary=True)
    elif "application" in text:
        s.add("gradle run", f"{gradle} run", "run", "Gradle", tool, primary=True)
    s.add("gradle build", f"{gradle} build", "build", "Gradle", tool)
    s.add("gradle test", f"{gradle} test", "test", "Gradle", tool)


def _dart(s: _Scan):
    if not s.has("pubspec.yaml"):
        return
    if "flutter:" in s.text("pubspec.yaml"):
        s.stack("Flutter")
        s.add("flutter run", "flutter run", "run", "Flutter", primary=True)
        s.add("flutter run (Linux)", "flutter run -d linux", "run", "Flutter")
        s.add("flutter build linux", "flutter build linux", "build", "Flutter")
        s.add("flutter test", "flutter test", "test", "Flutter")
        s.add("flutter analyze", "flutter analyze", "task", "Flutter")
    else:
        s.stack("Dart")
        s.add("dart run", "dart run", "run", "Dart", primary=True)
        s.add("dart test", "dart test", "test", "Dart")
        s.add("dart analyze", "dart analyze", "task", "Dart")


def _native(s: _Scan):
    """C/C++ und alles andere, was CMake, Meson oder Autotools baut."""
    if s.has("CMakeLists.txt"):
        s.stack("CMake")
        build = "cmake -S . -B build && cmake --build build -j"
        text = s.text("CMakeLists.txt")
        programs = re.findall(r"add_executable\s*\(\s*([\w.-]+)", text, re.I)
        apps = [a for a in programs if "test" not in a.lower() and "$" not in a]      # Testprogramme laufen über ctest
        for name in apps[:MAX_PER_FILE]:
            s.add(f"{name} bauen und starten", f"{build} && ./build/{name}", "run", "CMake", "cmake", primary=name == apps[0])
        if re.search(r"find_package\s*\(\s*Qt\d?", text, re.I):
            s.stack("Qt")
        s.add("cmake --build", build, "build", "CMake", "cmake")
        s.add("ctest", "ctest --test-dir build --output-on-failure", "test", "CMake", "ctest")
    if s.has("meson.build"):
        s.stack("Meson")
        s.add("meson compile", "[ -d builddir ] || meson setup builddir; meson compile -C builddir", "build", "Meson", "meson")
        s.add("meson test", "[ -d builddir ] || meson setup builddir; meson test -C builddir", "test", "Meson", "meson")
    if s.has("configure") and not s.has("Makefile"):
        s.stack("Autotools")
        s.add("./configure && make", "./configure && make -j$(nproc)", "build", "Autotools", "make")
    if s.has("build.zig"):
        s.stack("Zig")
        s.add("zig build run", "zig build run", "run", "Zig", primary=True)
        s.add("zig build", "zig build", "build", "Zig")
        s.add("zig build test", "zig build test", "test", "Zig")
    if s.has("Package.swift"):
        s.stack("Swift")
        s.add("swift run", "swift run", "run", "Swift", primary=True)
        s.add("swift build", "swift build", "build", "Swift")
        s.add("swift test", "swift test", "test", "Swift")
    if s.has("stack.yaml"):
        s.stack("Haskell")
        s.add("stack run", "stack run", "run", "Stack", primary=True)
        s.add("stack test", "stack test", "test", "Stack")
    elif list(s.dir.glob("*.cabal")):
        s.stack("Haskell")
        s.add("cabal run", "cabal run", "run", "Cabal", primary=True)
        s.add("cabal test", "cabal test", "test", "Cabal")


# --- Sprachunabhängige Aufgaben und Linux-Werkzeuge --------------------------------------------------------
def _kind_of(name: str) -> str:
    low = name.lower()
    return "server" if low in RUN_WORDS else "test" if low.startswith("test") or low == "check" else "build" if low in ("all", "build", "compile") else "task"


def _runners(s: _Scan):
    for file in ("Makefile", "makefile", "GNUmakefile"):
        if s.has(file):
            s.stack("Make")
            for name in dict.fromkeys(MAKE_TARGET.findall(s.text(file))[:MAX_PER_FILE]):
                s.add(f"make {name}", f"make {name}", _kind_of(name), "Make", "make")
            s.add("make", "make -j$(nproc)", "build", "Make", "make")
            break
    for file in ("justfile", "Justfile", ".justfile"):
        if s.has(file):
            s.stack("just")
            for name in dict.fromkeys(JUST_RECIPE.findall(s.text(file))[:MAX_PER_FILE]):
                if name not in ("set", "alias", "export", "import", "mod"):
                    s.add(f"just {name}", f"just {name}", _kind_of(name), "just", "just")
            break
    for file in ("Taskfile.yml", "Taskfile.yaml"):
        if s.has(file):
            s.stack("Task")
            block = re.search(r"^tasks:\n((?:[ \t].*\n|\n)*)", s.text(file) + "\n", re.M)
            for name in re.findall(r"^  ([\w:.-]+):", block.group(1) if block else "", re.M)[:MAX_PER_FILE]:
                s.add(f"task {name}", f"task {name}", _kind_of(name), "Task", "task")
            break
    for line in s.text("Procfile").splitlines():
        m = re.match(r"^([\w-]+):\s*(.+)$", line)
        if m:
            s.add(f"Procfile: {m[1]}", m[2].strip(), "server", "Procfile", "bash")
    for name in ("run.sh", "start.sh", "dev.sh"):
        if s.has(name):
            s.add(f"./{name}", f"bash {name}", "run", "Skripte", "bash")
    for name in ("build.sh", "test.sh", "install.sh"):
        if s.has(name):
            s.add(f"./{name}", f"bash {name}", {"build.sh": "build", "test.sh": "test"}.get(name, "task"), "Skripte", "bash")


def _vscode_tasks(s: _Scan):
    """Aufgaben aus .vscode/tasks.json, soweit es einfache Shell-Befehle sind. VS Code erlaubt dort Kommentare, sie fliegen vor dem Einlesen raus."""
    raw = s.text(".vscode/tasks.json")
    if not raw:
        return
    try:
        tasks = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M)).get("tasks", [])
    except (ValueError, AttributeError):
        return
    for task in tasks[:MAX_PER_FILE]:
        if isinstance(task, dict) and isinstance(task.get("command"), str) and task.get("type") in ("shell", "process") and "${" not in task["command"]:
            args = [a for a in task.get("args", []) if isinstance(a, str)]
            if not any("${" in a for a in args):
                s.add(task.get("label") or task["command"], " ".join([task["command"], *args]), "task", "VS Code", task["command"].split()[0])


def _linux(s: _Scan):
    compose = next((f for f in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml") if s.has(f)), None)
    if compose:
        s.stack("Docker Compose")
        s.add("Docker: alles starten", "docker compose up", "server", "Docker", "docker")
        s.add("Docker: im Hintergrund starten", "docker compose up -d", "task", "Docker", "docker")
        s.add("Docker: anhalten", "docker compose down", "task", "Docker", "docker")
        s.add("Docker: Status", "docker compose ps", "task", "Docker", "docker")
        s.add("Docker: Protokolle", "docker compose logs -f", "task", "Docker", "docker")
        s.add("Docker: Images bauen", "docker compose build", "build", "Docker", "docker")
    elif s.has("Dockerfile"):
        s.stack("Docker")
        s.add("Docker-Image bauen", f"docker build -t {_image_name(s.dir)} .", "build", "Docker", "docker")
    if s.has("flake.nix"):
        s.stack("Nix")
        s.add("nix build", "nix build", "build", "Nix")
        s.add("nix run", "nix run", "run", "Nix")
    if s.has("PKGBUILD"):
        s.stack("Arch-Paket")
        s.add("Paket bauen (makepkg)", "makepkg -f", "build", "Arch", "makepkg")
    if s.has(".pre-commit-config.yaml"):
        s.add("Pre-commit-Prüfungen", "pre-commit run --all-files", "test", "Git", "pre-commit")


def _image_name(folder: Path) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", folder.name.lower()).strip("-._") or "app"


# --- Gesamter Ordner ----------------------------------------------------------------------------------------
def _scan_folder(info: ProjectInfo, folder: Path, settings: ProjectSettings, prefix: str = ""):
    s = _Scan(info, folder, prefix)
    # Reihenfolge = Vorrang für die Standardwahl: bei Laravel + Vite startet der Laravel-Server, nicht Vite
    _php(s); _python(s, settings); _ruby(s); _elixir(s); _java(s); _dotnet(s); _rust(s); _go(s); _dart(s); _node(s); _native(s); _runners(s); _vscode_tasks(s); _linux(s)


def _subprojects(root: Path) -> list:
    """Unterordner mit eigenen Projektdateien: frontend/, backend/ …, dazu packages/*, apps/* usw."""
    markers = ("package.json", "composer.json", "pyproject.toml", "requirements.txt", "manage.py", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "pubspec.yaml", "CMakeLists.txt", "Gemfile", "mix.exs")
    platform = {"android", "ios", "linux", "macos", "windows", "web"} if (root / "pubspec.yaml").is_file() else set()      # gehören bei Flutter zum selben Projekt
    try:
        folders = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
        for parent in SUBPROJECT_PARENTS:
            if (root / parent).is_dir():
                folders += [d for d in (root / parent).iterdir() if d.is_dir() and not d.name.startswith(".")]
    except OSError:
        return []
    return sorted(d for d in folders if d.name not in SKIP_DIRS and d.name not in platform and any((d / m).is_file() for m in markers))


def analyze(root: Path, settings: ProjectSettings | None = None) -> ProjectInfo:
    root, settings = Path(root), settings or ProjectSettings()
    info = ProjectInfo(root)
    if settings.run_cmd.strip():
        info.targets.append(Target("Eigener Startbefehl", settings.run_cmd.strip(), "server", root, "Projekt", "bash", primary=True))
    _scan_folder(info, root, settings)
    subprojects = _subprojects(root)
    for sub in subprojects[:MAX_PER_FILE]:
        _scan_folder(info, sub, settings, sub.relative_to(root).as_posix())
    if info.default is None:                          # nur Unterprojekte: das erste mit Startmöglichkeit nehmen
        lead = next((t for t in info.targets if t.kind == "server" or t.kind == "run"), None) if subprojects else None
        auto = devserver.detect_command(root)
        if auto and not any(t.cmd == auto for t in info.targets):
            info.targets.append(Target("Dev-Server", auto, "server", root, "Projekt", "bash", primary=True))
        elif lead:
            info.targets[info.targets.index(lead)] = Target(lead.name, lead.cmd, lead.kind, lead.cwd, lead.group, lead.tool, True, lead.file)
    return info
