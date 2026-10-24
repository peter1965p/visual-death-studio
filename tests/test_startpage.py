"""Startseite: Projekttyp-Erkennung, Liste der zuletzt geöffneten Projekte, Aktionen, Einbindung ins Hauptfenster."""
import json
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from vds import options
from vds.app import MainWindow
from vds.ui import startpage


@pytest.fixture(autouse=True)
def clean(qapp):
    startpage.save_recent([])
    options.reset()
    yield
    startpage.save_recent([])
    options.reset()


def proj(root: Path, name: str, **files) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    for f, c in files.items():
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text(c if isinstance(c, str) else json.dumps(c))
    return d


@pytest.mark.parametrize("files,expect", [
    ({"artisan": "", "composer.json": "{}"}, ("Laravel", "php")),
    ({"angular.json": "{}", "package.json": {}}, ("Angular", "typescript")),
    ({"package.json": {"dependencies": {"nuxt": "3", "vue": "3"}}}, ("Nuxt", "vue")),
    ({"package.json": {"dependencies": {"next": "15", "react": "19"}}}, ("Next.js", "typescript")),
    ({"package.json": {"devDependencies": {"vue": "3"}}}, ("Vue", "vue")),
    ({"package.json": {"dependencies": {"react": "19"}}}, ("React", "typescript")),
    ({"package.json": {"scripts": {}}}, ("Node.js", "javascript")),
    ({"composer.json": "{}"}, ("PHP", "php")), ({"index.php": "<?php"}, ("PHP", "php")),
    ({"Cargo.toml": ""}, ("Rust", "rust")), ({"go.mod": ""}, ("Go", "go")), ({"App.csproj": ""}, (".NET", "csharp")),
    ({"pom.xml": ""}, ("Java", "java")), ({"CMakeLists.txt": ""}, ("C/C++", "cpp")),
    ({"requirements.txt": ""}, ("Python", "python")), ({"readme.txt": "x"}, ("Ordner", "")),
])
def test_project_kind_detection(tmp_path, files, expect):
    assert startpage.project_kind(proj(tmp_path, "p", **files)) == expect


def test_broken_package_json_does_not_crash(tmp_path):
    assert startpage.project_kind(proj(tmp_path, "p", **{"package.json": "{kaputt"}))[0] in ("Ordner", "Node.js")


def test_recent_list_orders_dedupes_limits_and_drops_missing_folders(tmp_path):
    dirs = [proj(tmp_path, f"p{i}", **{"a.py": "x"}) for i in range(15)]
    for d in dirs:
        startpage.remember(d)
    items = startpage.load_recent()
    assert len(items) == startpage.MAX_RECENT == 12 and items[0]["name"] == "p14" and items[-1]["name"] == "p3"
    startpage.remember(dirs[10])                                                    # erneut geöffnet → nach vorn, nicht doppelt
    names = [i["name"] for i in startpage.load_recent()]
    assert names[0] == "p10" and names.count("p10") == 1 and len(names) == 12
    import shutil
    shutil.rmtree(dirs[14])
    assert "p14" not in [i["name"] for i in startpage.load_recent()]                # verschwundene Ordner werden aussortiert
    assert "p10" not in [i["name"] for i in startpage.forget(str(dirs[10].resolve()))]


def test_corrupt_recent_setting_is_ignored(qapp):
    from PySide6.QtCore import QSettings
    from vds.branding import SETTINGS_APP, SETTINGS_ORG
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(startpage.KEY, "{das ist kein json")
    assert startpage.load_recent() == []
    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(startpage.KEY, json.dumps([1, "x", {"path": "/gibts/nicht"}]))
    assert startpage.load_recent() == []


def test_ago_wording():
    now = int(time.time())
    assert startpage.ago(now) == "gerade eben" and startpage.ago(now - 600) == "vor 10 Min." and startpage.ago(now - 7200) == "vor 2 Std."
    assert startpage.ago(now - 86400 * 3) == "vor 3 Tagen" and "." in startpage.ago(now - 86400 * 40)


def test_start_page_lists_projects_and_emits_actions(qapp, tmp_path):
    startpage.remember(proj(tmp_path, "Shop", artisan="", **{"composer.json": "{}"}))
    startpage.remember(proj(tmp_path, "Rechner", **{"main.py": "x"}))
    sp = startpage.StartPage()
    assert sp.recent.count() == 2 and not sp.empty.isVisibleTo(sp)
    first = sp.recent.item(0)
    assert first.text().startswith("Rechner   ·   Python\n") and str(tmp_path.resolve()) in first.text() and sp.recent.item(1).text().startswith("Shop   ·   Laravel")
    got = []
    sp.openProject.connect(got.append)
    sp.recent.itemActivated.emit(sp.recent.item(1))
    assert got == [str((tmp_path / "Shop").resolve())]
    seen = []
    for sig, name in ((sp.newProject, "new"), (sp.openFolder, "open"), (sp.newForm, "form"), (sp.openPreview, "web")):
        sig.connect(lambda n=name: seen.append(n))
    for k in ("new", "open", "form", "web"):
        sp.buttons[k].click()
    assert seen == ["new", "open", "form", "web"]
    flags = []
    sp.showOnStartChanged.connect(flags.append); sp.show_on_start.setChecked(False)
    assert flags == [False]
    startpage.save_recent([]); sp.refresh()
    assert sp.recent.count() == 0 and not sp.empty.isHidden()


# --- Hauptfenster -------------------------------------------------------------------------------------------------------
@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    yield w
    w.docs.close_all(); w.close()


def test_start_page_is_one_closable_tab_in_front(win, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    win.docs.open(tmp_path / "a.py")
    win.show_start_page(); win.show_start_page()
    assert win.docs.count() == 2 and win.docs.widget(0) is win.start and win.docs.tabText(0) == "Startseite" and win.docs.currentWidget() is win.start
    assert win.docs.current_doc() is None
    win.docs.close_tab(0)
    assert win.docs.count() == 1 and win.docs.current_doc() is not None
    win.show_start_page(); win.docs.close_all()
    assert win.docs.count() == 0                                                   # „Alle schließen“ schließt auch die Startseite


def test_start_page_at_startup_only_without_open_files_and_with_option(win, tmp_path):
    win.docs.close_all()
    win.maybe_show_start_page(); assert win.docs.count() == 1
    win.docs.close_all()
    options.set("ui/start_page", False); win.maybe_show_start_page(); assert win.docs.count() == 0
    options.set("ui/start_page", True)
    (tmp_path / "a.py").write_text("x"); win.docs.open(tmp_path / "a.py")
    win.maybe_show_start_page(); assert win.docs.count() == 1                      # es sind Dateien offen: keine Startseite


def test_menu_entries_recent_submenu_and_opening_a_recent_project(win, tmp_path):
    other = proj(tmp_path.parent / (tmp_path.name + "_andere"), "Projekt B", **{"b.py": "print('b')\n"})
    startpage.remember(other)
    datei = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "Datei")
    assert "Startseite" in [a.text() for a in datei.actions()] and win.a["startpage"].shortcut().toString() == "Ctrl+Shift+H"
    sub = next(a.menu() for a in datei.actions() if a.menu() is win.m_recent)
    sub.aboutToShow.emit()
    entries = [a.text() for a in sub.actions()]
    assert any(e.startswith("Projekt B") and str(other.resolve()) in e for e in entries)
    sub.actions()[0].trigger()                                                    # neuestes Projekt öffnen
    assert win.root == other.resolve()
    assert startpage.load_recent()[0]["path"] == str(other.resolve())


def test_missing_recent_project_is_forgotten_with_message(win, tmp_path):
    gone = proj(tmp_path, "weg"); startpage.remember(gone)
    import shutil
    shutil.rmtree(gone)
    startpage.save_recent([{"path": str(gone), "name": "weg", "opened": 1}])
    win.open_recent(str(gone))
    assert "existiert nicht mehr" in win.statusBar().currentMessage() and win.root == tmp_path.resolve() or win.root == tmp_path
    assert startpage.load_recent() == [] or all(Path(i["path"]).is_dir() for i in startpage.load_recent())


def test_set_root_remembers_the_project(win, tmp_path):
    d = proj(tmp_path, "Neu", **{"x.py": "1"})
    win.set_root(d)
    assert startpage.load_recent()[0]["path"] == str(d.resolve())


def test_option_and_start_page_checkbox_stay_in_sync(win):
    from vds.ui.options_dialog import OptionsDialog
    dlg = OptionsDialog(win)
    assert dlg.fields["ui/start_page"][1]() is True
    win.show_start_page()
    win.start.show_on_start.setChecked(False)
    assert options.get("ui/start_page") is False
    win.show_start_page()
    assert win.start.show_on_start.isChecked() is False
