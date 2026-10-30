"""Export (Qt Creator, Visual Studio, VS Code, ZIP) und Git-Push/Pull."""
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from vds.app import MainWindow
from vds.diff import changes as C
from vds.project import ProjectSettings
from vds.projects import exporter, importer


def w(root: Path, name: str, text: str = "x") -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_cpp_qt_project_gets_cmake_for_qt_creator_and_visual_studio(tmp_path):
    w(tmp_path, "main.cpp", '#include <QApplication>\nint main(){}\n')
    w(tmp_path, "win.h"); w(tmp_path, "build/gen.cpp")
    r = exporter.export_project(tmp_path, "qtcreator")
    cm = (tmp_path / "CMakeLists.txt").read_text()
    assert "find_package(Qt6" in cm and "main.cpp" in cm and "gen.cpp" not in cm and r.files
    again = exporter.export_project(tmp_path, "visualstudio")
    assert not again.files and any("CMakeLists.txt" in n for n in again.notes)


def test_python_project_gets_pyproject_for_qt_creator(tmp_path):
    w(tmp_path, "main.py"); w(tmp_path, "venv/x.py"); w(tmp_path, "Form1.form.json", "{}")
    exporter.export_project(tmp_path, "qtcreator")
    files = json.loads(next(tmp_path.glob("*.pyproject")).read_text())["files"]
    assert files == ["main.py"]


def test_dotnet_project_gets_sln_that_the_importer_reads_back(tmp_path):
    w(tmp_path, "App/App.csproj", "<Project/>")
    exporter.export_project(tmp_path, "visualstudio")
    sln = next(tmp_path.glob("*.sln"))
    assert [p[:2] for p in importer.parse_sln(sln)] == [("App", "App/App.csproj")]
    assert "\r\n" in sln.read_text(newline="") and "Release|Any CPU.Build.0" in sln.read_text()


def test_vscode_tasks_and_launch_follow_the_project_settings(tmp_path):
    w(tmp_path, "main.py")
    ProjectSettings(build_cmd="make all", run_cmd="python main.py").save(tmp_path)
    exporter.export_project(tmp_path, "vscode")
    tasks = json.loads((tmp_path / ".vscode/tasks.json").read_text())["tasks"]
    assert [t["label"] for t in tasks] == ["Erstellen", "Starten"] and tasks[0]["command"] == "make all"
    assert json.loads((tmp_path / ".vscode/launch.json").read_text())["configurations"][0]["program"].endswith("main.py")


def test_export_never_overwrites_and_empty_project_is_refused(tmp_path):
    with pytest.raises(exporter.ProjectExportError):
        exporter.export_project(tmp_path, "qtcreator")
    w(tmp_path, "CMakeLists.txt", "mein cmake")
    exporter.export_project(tmp_path, "qtcreator")
    assert (tmp_path / "CMakeLists.txt").read_text() == "mein cmake"


def test_zip_skips_environments(tmp_path):
    p = tmp_path / "proj"
    w(p, "a.py"); w(p, "venv/lib.py"); w(p, "node_modules/x.js"); w(p, ".git/HEAD"); w(p, "src/b.py")
    out = tmp_path / "out.zip"
    exporter.export_project(p, "zip", out)
    assert sorted(zipfile.ZipFile(out).namelist()) == ["proj/a.py", "proj/src/b.py"]


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path):
    bare = tmp_path / "remote.git"; bare.mkdir(); git(bare, "init", "-q", "--bare", "-b", "main")
    a = tmp_path / "a"; a.mkdir(); git(a, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@t"), ("user.name", "T")):
        git(a, "config", k, v)
    w(a, "f.txt"); git(a, "add", "."); git(a, "commit", "-qm", "eins")
    return a, bare


def test_push_without_remote_then_first_push_sets_upstream_and_pull(repos, tmp_path):
    a, bare = repos
    assert C.push(a)[0] == 1
    C.add_remote(a, str(bare))
    assert C.remotes(a) == {"origin": str(bare)} and C.upstream(a) == ""
    rc, out = C.push(a)
    assert rc == 0 and C.upstream(a) == "origin/main"
    b = tmp_path / "b"; subprocess.run(["git", "clone", "-q", str(bare), str(b)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "T")):
        git(b, "config", k, v)
    w(b, "g.txt"); git(b, "add", "."); git(b, "commit", "-qm", "zwei"); git(b, "push", "-q")
    rc, _ = C.pull(a)
    assert rc == 0 and (a / "g.txt").exists()


def test_failed_push_explains_authentication(monkeypatch):
    assert "gh auth login" in C._explain("fatal: could not read Username for 'https://github.com': terminal prompts disabled")


def test_changes_panel_pushes_in_background(qapp, repos, pump):
    a, bare = repos
    C.add_remote(a, str(bare))
    win = MainWindow()
    try:
        win.set_root(a)
        got = []
        win.changes.net_done.connect(lambda op, rc, out: got.append((op, rc)))
        win.changes._net("push")
        pump(lambda: got)
        assert got == [("push", 0)] and C.upstream(a) == "origin/main"
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()


def test_intellij_and_eclipse_export_roundtrip_through_the_importer(tmp_path):
    w(tmp_path, "src/demo/App.java", "package demo;\npublic class App { public static void main(String[] a) {} }\n")
    exporter.export_project(tmp_path, "intellij"); exporter.export_project(tmp_path, "eclipse")
    assert (tmp_path / ".idea/modules.xml").exists() and (tmp_path / ".project").exists()
    iml = next(tmp_path.glob("*.iml"))
    assert importer.import_project(iml).run_cmd.endswith("demo.App")
    assert importer.import_project(tmp_path / ".project").run_cmd.endswith("demo.App")
    py = tmp_path.parent / "pyproj"; py.mkdir(); (py / "main.py").write_text("x")
    exporter.export_project(py, "intellij")
    assert 'type="PYTHON_MODULE"' in next(py.glob("*.iml")).read_text()
    with pytest.raises(exporter.ProjectExportError):
        exporter.export_project(py, "eclipse")
