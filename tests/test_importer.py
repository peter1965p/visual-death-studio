"""Projekt-Import: Qt Creator (.pro, CMake), Visual Studio (.sln, .csproj, .vcxproj), Code::Blocks."""
import json
from pathlib import Path

import pytest

from vds.app import MainWindow
from vds.project import ProjectSettings
from vds.projects import importer


def w(root: Path, name: str, text: str = "") -> Path:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_parse_pro_handles_continuations_comments_and_ops():
    v = importer.parse_pro("QT += core gui \\\n  widgets  # Kommentar\nTARGET = demo\nSOURCES += a.cpp b.cpp\nSOURCES -= b.cpp\n")
    assert v["QT"] == ["core", "gui", "widgets"] and v["TARGET"] == ["demo"] and v["SOURCES"] == ["a.cpp"]


def test_qmake_project_builds_with_qmake_or_generated_cmake(tmp_path, monkeypatch):
    pro = w(tmp_path, "demo.pro", "QT += widgets\nTARGET = demo\nSOURCES += main.cpp\nHEADERS += win.h\nFORMS += win.ui\n")
    monkeypatch.setattr(importer.shutil, "which", lambda n: "/usr/bin/qmake6" if n == "qmake6" else None)
    r = importer.import_project(pro)
    assert r.kind == "Qt Creator (qmake)" and "qmake6" in r.build_cmd and r.run_cmd.endswith(".vds/build/demo")
    monkeypatch.setattr(importer.shutil, "which", lambda n: None)
    r = importer.import_project(tmp_path)                      # Ordner: .pro wird gefunden
    cm = (tmp_path / ".vds/import/CMakeLists.txt").read_text()
    assert "find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)" in cm and '${ROOT}/main.cpp' in cm and "add_executable(demo" in cm
    assert "cmake -S" in r.build_cmd


def test_qmake_subdirs_without_qmake_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(importer.shutil, "which", lambda n: None)
    with pytest.raises(importer.ProjectImportError):
        importer.import_project(w(tmp_path, "all.pro", "TEMPLATE = subdirs\nSUBDIRS = a b\n"))


def test_cmake_qt_creator_project(tmp_path):
    w(tmp_path, "CMakeLists.txt", "project(x)\nfind_package(Qt6 REQUIRED COMPONENTS Widgets)\nadd_executable(x main.cpp)\n")
    w(tmp_path, "CMakeLists.txt.user", "<xml/>")
    r = importer.import_project(tmp_path)
    assert r.kind == "Qt Creator (CMake)" and r.run_cmd.endswith("build/x") and any(".user" in n for n in r.notes)


SLN = '''Microsoft Visual Studio Solution File, Format Version 12.00
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "Ordner", "Ordner", "{AAA}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "App", "App\\App.csproj", "{BBB}"
EndProject
'''


def test_sln_with_dotnet_project(tmp_path):
    w(tmp_path, "My.sln", SLN)
    w(tmp_path, "App/App.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>')
    assert [p[0] for p in importer.parse_sln(tmp_path / "My.sln")] == ["App"]
    r = importer.import_project(tmp_path)
    assert r.kind == "Visual Studio (.NET)" and r.run_cmd == "dotnet run --project App/App.csproj" and r.build_cmd == ""


def test_windows_only_and_legacy_dotnet_projects_get_a_note(tmp_path):
    p = w(tmp_path, "Wpf.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>WinExe</OutputType><TargetFramework>net8.0-windows</TargetFramework></PropertyGroup></Project>')
    r = importer.import_project(p)
    assert r.run_cmd == "" and "nur unter Windows" in r.notes[0]
    old = w(tmp_path, "Old.csproj", '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003"><PropertyGroup><TargetFrameworkVersion>v4.8</TargetFrameworkVersion></PropertyGroup></Project>')
    assert "SDK-Stil" in importer.import_project(old).notes[0]


VCX = '''<?xml version="1.0"?><Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
<PropertyGroup><ConfigurationType>Application</ConfigurationType><ProjectName>Hallo</ProjectName></PropertyGroup>
<ItemDefinitionGroup><ClCompile><AdditionalIncludeDirectories>inc;$(SolutionDir)x;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
<PreprocessorDefinitions>WIN32;FOO=1;%(PreprocessorDefinitions)</PreprocessorDefinitions></ClCompile></ItemDefinitionGroup>
<ItemGroup><ClCompile Include="src\\main.cpp"/><ClInclude Include="inc\\a.h"/></ItemGroup></Project>'''


def test_vcxproj_becomes_cmake(tmp_path):
    p = w(tmp_path, "Hallo/Hallo.vcxproj", VCX)
    r = importer.import_project(p)
    cm = (tmp_path / "Hallo/.vds/import/CMakeLists.txt").read_text()
    assert r.kind == "Visual Studio (C++)" and "add_executable(Hallo" in cm and "src/main.cpp" in cm and "FOO=1" in cm and "WIN32" not in cm
    assert r.run_cmd.endswith(".vds/build/Hallo")


def test_sln_with_cpp_project_in_subfolder(tmp_path):
    w(tmp_path, "S.sln", 'Project("{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}") = "Hallo", "Hallo\\Hallo.vcxproj", "{C}"\nEndProject\n')
    w(tmp_path, "Hallo/Hallo.vcxproj", VCX)
    r = importer.import_project(tmp_path / "S.sln")
    cm = (tmp_path / ".vds/import/CMakeLists.txt").read_text()
    assert '${ROOT}/Hallo/src/main.cpp' in cm and r.run_cmd.endswith(".vds/build/Hallo")


def test_codeblocks_project(tmp_path):
    p = w(tmp_path, "cb.cbp", '<CodeBlocks_project_file><Project><Option title="Cb"/><Unit filename="main.cpp"/><Unit filename="readme.txt"/></Project></CodeBlocks_project_file>')
    r = importer.import_project(p)
    cm = (tmp_path / ".vds/import/CMakeLists.txt").read_text()
    assert "add_executable(Cb" in cm and "main.cpp" in cm and "readme" not in cm


def test_unknown_folder_is_refused(tmp_path):
    with pytest.raises(importer.ProjectImportError):
        importer.import_project(tmp_path)


def test_apply_keeps_existing_user_commands(tmp_path):
    w(tmp_path, "CMakeLists.txt", "add_executable(x main.cpp)\n")
    ProjectSettings(run_cmd="mein-befehl").save(tmp_path)
    importer.import_project(tmp_path).apply()
    assert ProjectSettings.load(tmp_path).run_cmd == "mein-befehl"


def test_main_window_imports_and_sets_project_commands(qapp, tmp_path):
    w(tmp_path, "CMakeLists.txt", "add_executable(x main.cpp)\n")
    win = MainWindow()
    try:
        assert win.import_project_path(tmp_path) is True
        assert win.root == tmp_path and win.project.run_cmd.endswith("build/x")
        assert any("Projekt" in a.text() for a in win.menuBar().actions()[0].menu().actions())
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()


def test_swift_package_and_xcode(tmp_path):
    w(tmp_path, "Package.swift", "// swift-tools-version:5.9")
    r = importer.import_project(tmp_path)
    assert r.kind == "Swift Package" and r.run_cmd == "swift run"
    (tmp_path / "Package.swift").unlink()
    x = tmp_path / "App.xcodeproj"; x.mkdir()
    r = importer.import_project(x)
    assert r.kind == "Xcode" and r.build_cmd == "" and "macOS" in r.notes[0]


JAVA = "package demo;\npublic class App { public static void main(String[] a) { System.out.println(\"hi\"); } }\n"


def test_intellij_and_eclipse_java_projects_build_with_javac(tmp_path):
    import shutil
    import subprocess
    w(tmp_path, "src/demo/App.java", JAVA)
    w(tmp_path, "p.iml", '<module><component><content url="file://$MODULE_DIR$"><sourceFolder url="file://$MODULE_DIR$/src" isTestSource="false" /></content></component></module>')
    r = importer.import_project(tmp_path / "p.iml")
    assert r.kind == "IntelliJ IDEA" and r.run_cmd.endswith("java -cp .vds/bin demo.App")
    (tmp_path / "p.iml").unlink()
    w(tmp_path, ".classpath", '<classpath><classpathentry kind="src" path="src"/><classpathentry kind="con" path="X"/></classpath>')
    r = importer.import_project(w(tmp_path, ".project", "<projectDescription/>"))
    assert r.kind == "Eclipse" and r.build_cmd.startswith("mkdir -p .vds/bin && javac")
    if shutil.which("javac") and shutil.which("java"):
        out = subprocess.run(["bash", "-c", r.run_cmd], cwd=tmp_path, capture_output=True, text=True)
        assert out.stdout.strip() == "hi", out.stderr
