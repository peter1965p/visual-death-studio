"""Laravel-Vorlage: 'composer create-project' im Projekt-Assistenten (mit gefälschtem composer, schnell und ohne Netz)."""
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PySide6.QtTest import QTest

from vds.projects.templates import BY_ID, create_project
from vds.web import devserver

FAKE = """#!/bin/sh
# argv: create-project laravel/laravel NAME ...
mkdir -p "$3/routes" "$3/app"
echo '{}' > "$3/composer.json"; touch "$3/artisan"; echo '<?php' > "$3/routes/web.php"; printf 'vendor/\\n.env\\n' > "$3/.gitignore"
echo "Creating a laravel/laravel project at $3"
[ -n "$FAKE_SLEEP" ] && sleep "$FAKE_SLEEP"
exit ${FAKE_EXIT:-0}
"""


@pytest.fixture
def fake_composer(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"; bin_.mkdir()
    exe = bin_ / "composer"; exe.write_text(FAKE); exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return exe


def test_sync_create_runs_composer_and_finishes_project(fake_composer, tmp_path):
    root, main, log = create_project(BY_ID["laravel"], "Shop", tmp_path / "ws", {"git": True})
    assert root == tmp_path / "ws" / "Shop" and main == root / "routes/web.php" and main.exists()
    assert (root / ".gitignore").read_text() == "vendor/\n.env\n"                         # die .gitignore von Laravel bleibt
    assert (root / ".git").is_dir() and "php artisan serve" in (root / ".vds/project.json").read_text()
    assert devserver.detect_command(root) == "php artisan serve"
    assert any("composer create-project laravel/laravel Shop" in l for l in log)


def test_sync_failure_removes_partial_project_but_not_preexisting_folder(fake_composer, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "3")
    with pytest.raises(RuntimeError, match="Code 3"):
        create_project(BY_ID["laravel"], "Shop", tmp_path, {})
    assert not (tmp_path / "Shop").exists()
    (tmp_path / "Leer").mkdir()
    with pytest.raises(RuntimeError):
        create_project(BY_ID["laravel"], "Leer", tmp_path, {})
    assert (tmp_path / "Leer").is_dir()                                                  # leerer Ordner war schon da: bleibt


def test_missing_composer_and_nonempty_target(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="composer"):
        create_project(BY_ID["laravel"], "Shop", tmp_path, {})
    (tmp_path / "Voll").mkdir(); (tmp_path / "Voll/x").write_text("x")
    with pytest.raises(FileExistsError):
        create_project(BY_ID["laravel"], "Voll", tmp_path, {})


def wait(cond, ms=10000):
    end = time.time() + ms / 1000
    while not cond() and time.time() < end:
        QTest.qWait(30)
    return cond()


def dialog(tmp_path, name="Shop"):
    from vds.projects.wizard import NewProjectDialog
    d = NewProjectDialog(None, tmp_path)
    d.tpl = BY_ID["laravel"]; d.name.setText(name); d.location.setText(str(tmp_path))
    d._go(2)
    return d


def test_wizard_runs_composer_in_background_and_finishes(qapp, fake_composer, tmp_path):
    d = dialog(tmp_path)
    assert d.checks["git"].isVisibleTo(d) is True and not d.checks["readme"].isVisibleTo(d)      # README bringt Laravel selbst mit
    d._create()
    assert d.stack.currentIndex() == 3 and d.proc is not None and not d.next.isEnabled()          # läuft, ohne die Oberfläche zu blockieren
    assert wait(lambda: d.result_data is not None)
    root, main, log = d.result_data
    assert main == tmp_path / "Shop/routes/web.php" and "Creating a laravel/laravel project" in d.ai_log.toPlainText()
    assert d.next.isEnabled() and d.bar.value() == 1 and d.prog_title.text() == "Projekt erstellt" and (root / ".git").is_dir()


def test_wizard_failure_cleans_up_and_allows_going_back(qapp, fake_composer, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "1")
    d = dialog(tmp_path)
    d._create()
    assert wait(lambda: d.proc is None)
    assert d.result_data is None and not (tmp_path / "Shop").exists() and not d.next.isEnabled()
    assert d.back.isVisibleTo(d) and "nicht angelegt" in d.prog_title.text()


def test_wizard_cancel_kills_composer_and_removes_folder(qapp, fake_composer, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "20")
    d = dialog(tmp_path)
    d._create()
    assert wait(lambda: (tmp_path / "Shop").exists())
    t0 = time.time()
    d._cancel()
    assert time.time() - t0 < 5 and d.proc is None and not (tmp_path / "Shop").exists() and d.result_data is None
    assert d.prog_title.text() == "Abgebrochen" and d.cancel.text() == "Schließen"


def test_wizard_hint_without_composer(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    from vds.projects.wizard import NewProjectDialog
    d = NewProjectDialog(None, tmp_path)
    d.tpl = BY_ID["laravel"]
    assert "composer" in d._tool_hint() and "nicht installiert" in d._tool_hint()
    d.name.setText("Shop"); d.location.setText(str(tmp_path)); d._go(2); d._create()
    assert d.stack.currentIndex() == 1 and "composer" in d.err.text() and d.proc is None


@pytest.mark.skipif(os.environ.get("VDS_SLOW_TESTS") != "1" or not shutil.which("composer") or not shutil.which("php"), reason="langsam: VDS_SLOW_TESTS=1 (composer, php, Netzwerk)")
def test_real_laravel_project_boots(tmp_path):
    root, main, _log = create_project(BY_ID["laravel"], "Echt", tmp_path, {"git": False})
    assert (root / "artisan").is_file() and (root / "vendor/autoload.php").is_file() and main.exists()
    r = subprocess.run(["php", "artisan", "--version"], cwd=root, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "Laravel Framework" in r.stdout
