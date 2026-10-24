"""Spring-Boot-Vorlage (Maven-Wrapper), Erkennung von Start-Befehl und Adresse; echter Build nur mit VDS_SLOW_TESTS=1."""
import os
import shutil
import subprocess

import pytest

from vds.projects.templates import BY_ID, create_project
from vds.web import devserver


def make(tmp_path, name="Mein Shop"):
    return create_project(BY_ID["java-spring"], name, tmp_path, {"git": False, "readme": True})


def test_spring_template_files_wrapper_and_run_command(tmp_path):
    root, main, _log = make(tmp_path)
    pkg = root / "src/main/java/com/example/mein_shop"
    assert main == pkg / "HelloController.java" and main.is_file()                      # Platzhalter im Pfad ersetzt
    assert (pkg / "Application.java").read_text().startswith("package com.example.mein_shop;")
    assert "__" not in "".join(p.read_text() for p in root.rglob("*") if p.is_file() and ".vds" not in p.parts)
    assert os.access(root / "mvnw", os.X_OK) and (root / "mvnw").read_text().startswith("#!/bin/sh")
    assert subprocess.run(["sh", "-n", str(root / "mvnw")]).returncode == 0
    assert "<artifactId>mein_shop</artifactId>" in (root / "pom.xml").read_text()
    from vds.project import ProjectSettings
    assert ProjectSettings.load(root).run_cmd == "./mvnw spring-boot:run"


def test_spring_start_command_and_port_detection(tmp_path):
    root, _m, _l = make(tmp_path)
    assert devserver.detect_command(root) == "./mvnw spring-boot:run"
    (root / "mvnw").unlink()
    assert devserver.detect_command(root) == "mvn spring-boot:run"
    g = tmp_path / "g"; g.mkdir()
    (g / "build.gradle").write_text("plugins { id 'org.springframework.boot' version '4.1.2' }")
    assert devserver.detect_command(g) == "gradle bootRun"
    (g / "gradlew").write_text("")
    assert devserver.detect_command(g) == "./gradlew bootRun"
    plain = tmp_path / "p"; plain.mkdir(); (plain / "pom.xml").write_text("<project/>")
    assert devserver.detect_command(plain) is None                                       # Maven ohne Spring Boot: kein Raten
    log = "Tomcat initialized with port 8081 (http)\n... Tomcat started on port 8081 (http) with context path '/'\n"
    assert devserver.find_url(log) == "http://localhost:8081"
    assert devserver.find_url("Netty started on port 9000") == "http://localhost:9000"


@pytest.mark.skipif(os.environ.get("VDS_SLOW_TESTS") != "1" or not shutil.which("java") or not shutil.which("curl"), reason="langsam: VDS_SLOW_TESTS=1 (JDK, curl, Netzwerk)")
def test_spring_template_builds_and_passes_its_test(tmp_path):
    root, _m, _l = make(tmp_path)
    r = subprocess.run(["./mvnw", "-q", "test"], cwd=root, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def test_start_page_recognises_spring_boot(tmp_path):
    from vds.ui.startpage import project_kind
    root, _m, _l = make(tmp_path)
    assert project_kind(root) == ("Spring Boot", "java")
