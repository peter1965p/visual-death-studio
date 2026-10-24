"""„Fertige Anwendung“: Katalog Anwendung × Technik, Auftrag für Claude, Zusammenspiel mit Grundgerüst und Laravel-Scaffold."""
import os
import time

import pytest
from PySide6.QtTest import QTest

from vds.projects import apps
from vds.projects.templates import BY_ID, TEMPLATES
from vds.projects.wizard import NewProjectDialog


def test_catalog_is_consistent():
    assert BY_ID["app"].kind == "Anwendung"
    for a in apps.APPS:
        assert a.techs and a.spec and a.blurb
        for t in a.techs:
            assert t in BY_ID and t in apps.TECH_LABEL and t in apps.TECH_NOTES, (a.id, t)
    web = {a.id for a in apps.APPS if "laravel" in a.techs}
    assert {"cms", "shop", "website"} <= web and all(set(apps.WEB) == set(apps.BY_ID[i].techs) for i in web)       # „alles mit allem“ bei Web-Anwendungen
    assert apps.BY_ID["browser"].techs == ("py-qt",)                                                               # Browser nur mit QtWebEngine
    p = apps.prompt("shop", "angular")
    assert "Online-Shop" in p and "Angular" in p and "localStorage" in p and apps.GENERAL in p


@pytest.fixture
def dlg(qapp, tmp_path, monkeypatch):
    from vds.ai import backend
    monkeypatch.setattr(backend, "available", lambda: True)
    d = NewProjectDialog(None, tmp_path)
    d.tpl = BY_ID["app"]; d.name.setText("Meine App"); d.location.setText(str(tmp_path))
    d.calls = []
    d.claude.run = lambda prompt, root, **kw: d.calls.append((prompt, root, kw))
    d._go(2)
    return d


def choose(d, app_id, tech_id):
    d.app.setCurrentIndex(d.app.findData(app_id))
    d.tech.setCurrentIndex(d.tech.findData(tech_id))


def test_page_offers_apps_and_only_matching_techs(dlg):
    assert dlg.app_box.isVisibleTo(dlg) and dlg.app.count() == len(apps.APPS) and dlg.tech.count() > 1
    choose(dlg, "browser", "py-qt")
    assert [dlg.tech.itemData(i) for i in range(dlg.tech.count())] == ["py-qt"] and "QtWebEngine" in dlg.desc.toPlainText()
    choose(dlg, "filemanager", "java-swing")
    assert [dlg.tech.itemData(i) for i in range(dlg.tech.count())] == ["py-qt", "java-swing"]
    assert dlg.eff is BY_ID["java-swing"] and "Swing" in dlg.desc.toPlainText() and dlg.next.isEnabled()


def test_description_follows_choice_but_keeps_user_edits(dlg):
    choose(dlg, "shop", "laravel")
    assert "Warenkorb" in dlg.desc.toPlainText() and "Laravel" in dlg.desc.toPlainText()
    choose(dlg, "shop", "vue-vite")
    assert "Vue 3" in dlg.desc.toPlainText() and "Laravel" not in dlg.desc.toPlainText()                       # Auftrag passt sich an
    dlg.desc.setPlainText("Mein eigener Auftrag: nur ein Warenkorb.")
    choose(dlg, "cms", "vue-vite")
    assert dlg.desc.toPlainText() == "Mein eigener Auftrag: nur ein Warenkorb."                                 # eigene Änderung bleibt
    dlg._go(1); dlg.tpl = BY_ID["php-web"]; dlg._go(2)
    assert not dlg.app_box.isVisibleTo(dlg)


def test_stale_app_prompt_is_cleared_for_other_templates(dlg):
    choose(dlg, "cms", "laravel")
    assert "CMS" in dlg.desc.toPlainText() or "Content-Management" in dlg.desc.toPlainText()
    dlg._go(1); dlg.tpl = BY_ID["php-web"]; dlg._go(2)
    assert dlg.desc.toPlainText() == ""


def test_next_needs_claude(qapp, tmp_path, monkeypatch):
    from vds.ai import backend
    monkeypatch.setattr(backend, "available", lambda: False)
    d = NewProjectDialog(None, tmp_path); d.tpl = BY_ID["app"]; d.name.setText("X"); d.location.setText(str(tmp_path)); d._go(2)
    assert not d.next.isEnabled()


def test_create_builds_base_template_then_starts_claude_with_app_prompt(dlg, tmp_path):
    choose(dlg, "website", "react-vite")
    dlg._create()
    root = tmp_path / "Meine App"
    assert (root / "package.json").is_file() and (root / "src/Form1.form.json").is_file()                       # Grundgerüst React/Vite
    assert len(dlg.calls) == 1
    prompt, cwd, kw = dlg.calls[0]
    assert cwd == root and "Unternehmens-Website" in prompt and "React + TypeScript" in prompt and "package.json" in prompt
    assert kw["max_turns"] == 100 and "vollständige" in kw["system"]
    assert dlg.stack.currentIndex() == 3


FAKE = """#!/bin/sh
mkdir -p "$3/routes"; echo '{}' > "$3/composer.json"; touch "$3/artisan"; echo '<?php' > "$3/routes/web.php"
echo "Creating project"
"""


def test_create_with_laravel_runs_scaffold_first_then_claude(dlg, tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"; bin_.mkdir()
    (bin_ / "composer").write_text(FAKE); (bin_ / "composer").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    choose(dlg, "cms", "laravel")
    dlg._create()
    assert dlg.proc is not None and not dlg.calls                                                                 # erst Composer, Claude noch nicht
    end = time.time() + 10
    while not dlg.calls and time.time() < end:
        QTest.qWait(30)
    assert len(dlg.calls) == 1 and (tmp_path / "Meine App/routes/web.php").is_file()
    assert "Laravel" in dlg.calls[0][0] and "pdo_sqlite" in dlg.calls[0][0]
    assert "vendor" not in dlg.calls[0][0].split("vorhandene Dateien:")[1].split(")")[0]                          # Dateiliste ohne vendor/


def test_template_list_filters_by_kind(qapp, tmp_path):
    from PySide6.QtCore import Qt
    d = NewProjectDialog(None, tmp_path)
    d.f_kind.setCurrentText("Anwendung")
    assert [d.list.item(i).data(Qt.UserRole).id for i in range(d.list.count())] == ["app"]
    assert any(t.id == "app" for t in TEMPLATES)
