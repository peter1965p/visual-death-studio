"""Projekterkennung, Sprachserver-Auswahl und Startziele im Hauptfenster."""
import json
import os
from pathlib import Path

import pytest

from vds.debug import tools as dbg_tools
from vds.lsp import servers
from vds.project import ProjectSettings
from vds.projects.detect import analyze


def write(root: Path, files: dict):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def names(info):
    return [t.name for t in info.targets]


LARAVEL = {"artisan": "#!/usr/bin/env php\n", "composer.json": json.dumps({"require": {"laravel/framework": "^13"}, "scripts": {"dev": "x", "test": "y", "post-update-cmd": "z"}}),
           "package.json": json.dumps({"devDependencies": {"vite": "^7"}, "scripts": {"build": "vite build", "dev": "vite"}})}


def test_laravel_with_vite_starts_laravel_and_lists_tasks(tmp_path):
    write(tmp_path, LARAVEL)
    info = analyze(tmp_path)
    assert info.stacks[:2] == ["Laravel", "Vite"]
    assert info.default.name == "Laravel-Server" and "php artisan serve" in info.default.cmd
    assert {"composer dev", "npm run dev"} <= {t.name for t in info.startable}
    assert {"Migrationen ausführen", "composer test", "npm run build"} <= {t.name for t in info.tasks}
    assert not any("post-update" in n for n in names(info))
    assert not any("migrate:fresh" in t.cmd for t in info.targets)


def test_laravel_uses_the_project_php_ini(tmp_path):
    write(tmp_path, {**LARAVEL, ".vds/php/10-sqlite.ini": "extension=pdo_sqlite\n"})
    info = analyze(tmp_path)
    for name in ("Laravel-Server", "Migrationen ausführen", "Tests (artisan test)"):
        assert 'PHP_INI_SCAN_DIR=":$PWD/.vds/php"' in next(t for t in info.targets if t.name == name).cmd


def test_own_start_command_comes_first(tmp_path):
    write(tmp_path, LARAVEL)
    info = analyze(tmp_path, ProjectSettings(run_cmd="php artisan serve --port=9000"))
    assert info.default.name == "Eigener Startbefehl" and info.default.cmd.endswith("--port=9000")


@pytest.mark.parametrize("files,stack,start", [
    ({"Cargo.toml": '[package]\nname="x"\n', "src/main.rs": ""}, "Rust", "cargo run"),
    ({"go.mod": "module x\n", "cmd/api/main.go": ""}, "Go", "go run ./cmd/api"),
    ({"pubspec.yaml": "name: x\nflutter:\n  sdk: flutter\n"}, "Flutter", "flutter run"),
    ({"x.csproj": "<Project><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>"}, ".NET", "dotnet run --project x.csproj"),
    ({"pom.xml": "<dependency>spring-boot</dependency>"}, "Spring Boot", "mvn spring-boot:run"),
    ({"build.zig": ""}, "Zig", "zig build run"),
    ({"manage.py": "", "requirements.txt": "django\n"}, "Django", "python3 manage.py runserver"),
    ({"Gemfile": "gem 'rails'\n", "bin/rails": ""}, "Rails", "bin/rails server"),
    ({"mix.exs": ":phoenix"}, "Phoenix", "mix phx.server"),
    ({"index.php": ""}, "PHP", "php -S localhost:8000"),
    ({"app/__main__.py": ""}, "Python", "python3 -u -m app"),
])
def test_project_kinds(tmp_path, files, stack, start):
    write(tmp_path, files)
    info = analyze(tmp_path)
    assert stack in info.stacks
    assert info.default.cmd == start


def test_folder_without_project_has_no_target(tmp_path):
    write(tmp_path, {"notizen.txt": "x"})
    info = analyze(tmp_path)
    assert info.default is None and info.targets == [] and info.stacks == []


def test_package_manager_follows_lockfile_and_skips_lifecycle(tmp_path):
    write(tmp_path, {"pnpm-lock.yaml": "", "package.json": json.dumps({"scripts": {"dev": "vite", "postinstall": "x", "pretest": "y", "test": "z"}})})
    info = analyze(tmp_path)
    assert info.default.cmd.endswith("pnpm run dev") and info.default.tool == "pnpm"
    assert set(names(info)) == {"pnpm run dev", "pnpm run test"}


def test_subprojects_are_found_and_named(tmp_path):
    write(tmp_path, {"frontend/package.json": json.dumps({"scripts": {"dev": "vite"}}), "backend/go.mod": "module b\n", "backend/main.go": "",
                     "packages/ui/package.json": json.dumps({"scripts": {"build": "x"}}), "vendor/package.json": "{}"})
    info = analyze(tmp_path)
    assert {"frontend: npm run dev", "backend: go run .", "packages/ui: npm run build"} <= set(names(info))
    start = next(t for t in info.targets if t.name == "frontend: npm run dev")
    assert start.cwd == tmp_path / "frontend"
    assert sum(t.primary for t in info.targets) == 1
    assert not any(n.startswith("vendor") for n in names(info))


def test_flutter_platform_folders_are_no_projects(tmp_path):
    write(tmp_path, {"pubspec.yaml": "flutter:\n", "linux/CMakeLists.txt": "", "android/build.gradle": ""})
    assert analyze(tmp_path).stacks == ["Flutter"]


def test_cmake_tests_are_not_start_targets(tmp_path):
    write(tmp_path, {"CMakeLists.txt": "add_executable(foo_test a.c)\nadd_executable(tool b.c)\nadd_executable(${X} c.c)\n"})
    info = analyze(tmp_path)
    assert [t.name for t in info.startable] == ["tool bauen und starten"]


def test_make_just_task_and_compose(tmp_path):
    write(tmp_path, {"Makefile": "FOO := 1\n.PHONY: run\nrun:\n\tx\ntest: run\n\ty\n", "justfile": "set shell := ['bash']\nserve port:\n  x\n",
                     "Taskfile.yml": "version: '3'\ntasks:\n  lint:\n    cmds: [x]\nother:\n  no:\n", "compose.yaml": "services: {}\n", "PKGBUILD": ""})
    info = analyze(tmp_path)
    assert {"make run", "make test", "just serve", "task lint", "Docker: alles starten", "Paket bauen (makepkg)"} <= set(names(info))
    assert "make FOO" not in names(info) and "just set" not in names(info) and "task no" not in names(info)
    assert next(t for t in info.targets if t.name == "make run").kind == "server"
    assert not any("down -v" in t.cmd for t in info.targets)


def test_vscode_tasks_with_comments(tmp_path):
    write(tmp_path, {".vscode/tasks.json": '{\n  // Kommentar\n  "tasks": [{"label": "Bauen", "type": "shell", "command": "make", "args": ["all"]}, {"label": "Pfad", "type": "shell", "command": "${workspaceFolder}/x"}]\n}\n'})
    info = analyze(tmp_path)
    assert names(info) == ["Bauen"] and info.targets[0].cmd == "make all"


def test_broken_project_files_do_not_stop_the_scan(tmp_path):
    write(tmp_path, {"package.json": "{kaputt", "composer.json": "[1,2]", "Cargo.toml": "= kaputt", "pyproject.toml": "= kaputt", ".vscode/tasks.json": "nein"})
    assert "Rust" in analyze(tmp_path).stacks


def test_python_script_keeps_debugger_file(tmp_path):
    write(tmp_path, {"main.py": "", "venv/bin/python": ""})
    target = analyze(tmp_path).default
    assert target.cmd == "venv/bin/python -u main.py" and target.file == "main.py" and target.missing_tool() is None


def test_missing_tool_is_named(tmp_path):
    write(tmp_path, {"build.zig": ""})
    target = analyze(tmp_path).default
    os.environ["PATH"], old = "", os.environ["PATH"]
    try:
        assert target.missing_tool() == "zig"
    finally:
        os.environ["PATH"] = old


# --- Sprachserver --------------------------------------------------------------------------------------------
def test_language_tables():
    assert servers.lang_for("a.php").id == "php"
    assert servers.lang_for("x/home.blade.php").id == "blade"
    assert servers.lang_for("a.tsx").id == "typescriptreact"
    assert servers.lang_for("Dockerfile").id == "dockerfile" and servers.lang_for("Dockerfile.dev").id == "dockerfile"
    assert servers.lang_for("a.unbekannt") is None
    assert servers.suggestion("blade") is None


def test_first_installed_server_wins(monkeypatch):
    monkeypatch.setattr(servers.shutil, "which", lambda name: "/x" if name == "phpactor" else None)
    assert servers.choose("php").command[0] == "phpactor"
    monkeypatch.setattr(servers.shutil, "which", lambda name: None)
    assert servers.choose("php") is None and servers.suggestion("php").command[0] == "intelephense"


def test_only_passwordless_installs_run_inside_the_ide(monkeypatch):
    monkeypatch.setattr(servers.shutil, "which", lambda name: "/x")
    assert servers.can_run_install(servers.Server(("a",), "npm i -g a"))
    assert not servers.can_run_install(servers.Server(("a",), "sudo pacman -S a"))
    assert not servers.can_run_install(servers.Server(("a",), "yay -S a"))


def test_server_questions_are_always_answered():
    from vds.lsp.manager import LspManager

    class Client:
        sent = []
        def reply(self, req_id, result):
            self.sent.append((req_id, result))

    class Sv:
        client = Client()
    LspManager._server_request(None, Sv, "workspace/configuration", {"items": [{}, {}]}, 1)
    LspManager._server_request(None, Sv, "client/registerCapability", {}, 2)
    assert Client.sent == [(1, [None, None]), (2, None)]


# --- PATH beim Start aus dem Menü -----------------------------------------------------------------------------
def test_nvm_goes_first_and_uses_default_version(tmp_path, monkeypatch):
    for version in ("v9.0.0", "v18.1.0", "v22.3.0"):
        (tmp_path / ".nvm/versions/node" / version / "bin").mkdir(parents=True)
    (tmp_path / ".nvm/alias").mkdir()
    (tmp_path / ".nvm/alias/default").write_text("18\n")
    monkeypatch.setattr(dbg_tools.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("PATH", "/usr/bin")
    dbg_tools.extend_path()
    assert os.environ["PATH"].split(os.pathsep)[:2] == [str(tmp_path / ".nvm/versions/node/v18.1.0/bin"), "/usr/bin"]


def test_nvm_without_default_takes_newest_not_alphabetic(tmp_path, monkeypatch):
    for version in ("v9.0.0", "v22.3.0"):
        (tmp_path / ".nvm/versions/node" / version / "bin").mkdir(parents=True)
    assert dbg_tools._nvm_bin(tmp_path).parent.name == "v22.3.0"
    assert dbg_tools._nvm_bin(tmp_path / "gibt-es-nicht") is None


def test_build_menu_falls_back_to_detected_build(tmp_path):
    from vds.build.projects import detect
    write(tmp_path, {"meson.build": ""})
    assert detect(tmp_path).name == "Meson"
    (tmp_path / "leer").mkdir()
    assert detect(tmp_path / "leer") is None


# --- Startziele im Hauptfenster -------------------------------------------------------------------------------
@pytest.fixture
def window(qapp, tmp_path):
    from vds.app import MainWindow
    w = MainWindow()
    calls = []
    w.run_target = lambda target: calls.append(target.name) or True       # nichts wirklich starten
    w.calls = calls
    yield w
    w.docs.close_all()
    w.close()


def box_items(w):
    return [w.target_box.itemText(i) for i in range(w.target_box.count())]


def test_toolbar_follows_project_and_remembers_choice(window, tmp_path):
    w = window
    write(tmp_path, LARAVEL)
    w.set_root(tmp_path)
    assert box_items(w)[:2] == ["Aktive Datei", "Laravel-Server"] and w.target_box.currentText() == "Laravel-Server"
    assert w.st_project.text() == "Laravel · Vite"
    assert not w.cfg_action.isVisible()
    assert w.run_project_command("buildrun") and w.calls == ["Laravel-Server"]

    i = w.target_box.findText("npm run dev")
    w.target_box.setCurrentIndex(i); w._target_picked(i)
    w.scan_project()
    assert w.active_target()[0].name == "npm run dev" and w.active_target()[1] is True

    i = w.target_box.findData("file")
    w.target_box.setCurrentIndex(i); w._target_picked(i)
    assert w.run_project_command("buildrun") is False                     # „Aktive Datei“ gewählt: Der Eintrag läuft wie bisher


def test_file_of_another_language_runs_itself_and_the_box_says_so(window, tmp_path):
    w = window
    write(tmp_path, {"package.json": json.dumps({"scripts": {"dev": "vite"}}), "tool.py": "print(1)\n", "main.js": ""})
    w.set_root(tmp_path)
    w.docs.open(tmp_path / "tool.py")
    assert w.active_target() == (None, False) and w.target_box.currentText() == "Aktive Datei"
    w.docs.open(tmp_path / "main.js")
    assert w.active_target()[0].name == "npm run dev" and w.target_box.currentText() == "npm run dev"
    i = w.target_box.findText("npm run dev")
    w.target_box.setCurrentIndex(i); w._target_picked(i)
    w.docs.open(tmp_path / "tool.py")
    assert w.active_target()[0].name == "npm run dev"                     # ausdrücklich gewählt: gilt immer


def test_vanished_choice_falls_back_to_recommendation(window, tmp_path):
    w = window
    write(tmp_path, LARAVEL)
    w.settings.setValue(f"project/target/{tmp_path}", "gibt::es-nicht")
    w.set_root(tmp_path)
    assert w.active_target() == (w.project_info.default, False)


def test_breakpoints_send_f5_to_the_debugger(window, tmp_path):
    w = window
    write(tmp_path, {"Cargo.toml": '[package]\nname="x"\n', "src/main.rs": "fn main() {}\n"})
    w.set_root(tmp_path)
    assert w.run_project_command("buildrun", debug=True) and w.calls == ["cargo run"]
    w.docs.all_breakpoints = lambda: [("a", 1, "", True)]
    assert w.run_project_command("buildrun", debug=True) is False
    assert w.run_project_command("buildrun") is True                      # Strg+F5 bleibt ohne Debugger


def test_python_target_debugs_its_script(window, tmp_path):
    w = window
    write(tmp_path, {"main.py": "print(1)\n"})
    w.set_root(tmp_path)
    assert w.target_script() == tmp_path / "main.py"
    assert w.run_project_command("buildrun", debug=True) is False
    assert w.run_project_command("buildrun") is True


def test_missing_tool_is_reported_in_output(qapp, tmp_path, monkeypatch):
    from vds.app import MainWindow
    write(tmp_path, {"build.zig": ""})
    w = MainWindow()
    w.set_root(tmp_path)
    monkeypatch.setenv("PATH", "")
    assert w.run_target(w.project_info.default) is True
    assert "zig" in w.output.text.toPlainText() and not w.runner.busy
    w.close()
