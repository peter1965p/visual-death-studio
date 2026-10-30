"""Selbst-Update: Versionsvergleich, Release-Abfrage, Git-Update eines Klons, Hinweisdialog."""
import json
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabBar

from vds import options, updater
from vds.app import MainWindow


def test_version_compare():
    assert updater.is_newer("v0.10.0", "0.9.9") and updater.is_newer("v1.0.0", "0.3.0")
    assert not updater.is_newer("v0.3.0", "0.3.0") and not updater.is_newer("v0.2.9", "0.3.0")
    assert not updater.is_newer("nightly", "0.3.0") and updater.parse_version("v1.2") is None


def test_fetch_latest_parses_and_rejects(tmp_path, monkeypatch):
    class R:
        def __init__(self, d): self.d = d
        def read(self): return json.dumps(self.d).encode()
        def __enter__(self): return self
        def __exit__(self, *a): pass
    ok = {"tag_name": "v0.4.0", "html_url": "u", "body": "Neu"}
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: R(ok))
    assert updater.fetch_latest() == updater.Release("v0.4.0", "u", "Neu")
    for bad in ({**ok, "prerelease": True}, {**ok, "draft": True}, {**ok, "tag_name": "x"}, []):
        monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, bad=bad, **k: R(bad))
        assert updater.fetch_latest() is None
    def boom(*a, **k): raise OSError("offline")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    assert updater.fetch_latest() is None


def git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path):
    up = tmp_path / "up"; up.mkdir(); git(up, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@t"), ("user.name", "T")):
        git(up, "config", k, v)
    (up / "v.txt").write_text("1"); git(up, "add", "."); git(up, "commit", "-qm", "1"); git(up, "tag", "v0.1.0")
    cl = tmp_path / "cl"; subprocess.run(["git", "clone", "-q", str(up), str(cl)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "T")):
        git(cl, "config", k, v)
    (up / "v.txt").write_text("2"); git(up, "commit", "-qam", "2"); git(up, "tag", "v0.2.0")
    return up, cl


def test_apply_update_fast_forwards_to_the_tag(clone):
    up, cl = clone
    assert updater.blocker(cl) == ""
    ok, msg = updater.apply_update(cl, "v0.2.0")
    assert ok and (cl / "v.txt").read_text() == "2" and "v0.2.0" in msg


def test_update_is_refused_for_dirty_tree_own_commits_and_non_git(clone, tmp_path):
    up, cl = clone
    (cl / "v.txt").write_text("lokal")
    ok, msg = updater.apply_update(cl, "v0.2.0")
    assert not ok and "lokale Änderungen" in msg and (cl / "v.txt").read_text() == "lokal"
    git(cl, "checkout", "--", "v.txt")
    (cl / "eigen.txt").write_text("x"); git(cl, "add", "."); git(cl, "commit", "-qm", "eigen")
    (up / "w.txt").write_text("y"); git(up, "add", "."); git(up, "commit", "-qm", "3"); git(up, "tag", "v0.3.0")
    ok, msg = updater.apply_update(cl, "v0.3.0")
    assert not ok and "Vorspulen" in msg
    plain = tmp_path / "plain"; plain.mkdir()
    assert "kein Git-Klon" in updater.blocker(plain)
    assert updater.apply_update(cl, "main; rm -rf /")[0] is False


def test_window_offers_update_and_respects_daily_throttle(qapp, monkeypatch, pump):
    from PySide6.QtWidgets import QMessageBox
    win = MainWindow()
    try:
        monkeypatch.setattr(updater, "fetch_latest", lambda *a, **k: updater.Release("v9.9.9", "http://x", "Notizen"))
        monkeypatch.setattr(updater, "blocker", lambda root: "gesperrt")
        shown = []
        monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append((self.text(), self.informativeText())) or 0)
        options.set("update/check", True); options.set("update/last_check", 0)
        win.check_updates()
        pump(lambda: shown, 10)
        assert "v9.9.9" in shown[0][0] and "gesperrt" in shown[0][1]
        shown.clear(); win.check_updates(); pump(lambda: shown, 0.5)       # innerhalb eines Tages: keine zweite Abfrage
        assert shown == []
        options.set("update/check", False); options.set("update/last_check", 0)
        win.check_updates(); pump(lambda: shown, 0.5)
        assert shown == []
    finally:
        options.set("update/check", True)
        win.docs.close_all(); win.preview.shutdown(); win.close()


def test_dock_tab_bars_scroll_instead_of_eliding(qapp, pump):
    win = MainWindow()
    try:
        win.show()
        bars = lambda: [tb for tb in win.findChildren(QTabBar) if tb.parent() is win]
        pump(lambda: bars() and all(tb.elideMode() == Qt.ElideNone and tb.usesScrollButtons() for tb in bars()), 5)
        assert bars() and all(tb.elideMode() == Qt.ElideNone and tb.usesScrollButtons() for tb in bars()), [(tb.count(), tb.elideMode(), tb.usesScrollButtons(), tb.isVisible(), tb.tabText(0)) for tb in bars() if not (tb.elideMode() == Qt.ElideNone and tb.usesScrollButtons())]
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()
