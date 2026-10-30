"""Live Share: Anmeldung per Code, Dateien übertragen, Bearbeitungen verteilen, Pfad-Sicherheit."""
from pathlib import Path

import pytest

from vds.share import session as S


def test_safe_rel_blocks_escapes(tmp_path):
    assert S.safe_rel(tmp_path, "a/b.py") == (tmp_path / "a/b.py").resolve()
    for bad in ("../x", "/etc/passwd", "a/../../x", "", "C:/x", None, 5):
        assert S.safe_rel(tmp_path, bad) is None


def test_write_files_ignores_unsafe_paths(tmp_path):
    n = S.write_files(tmp_path / "g", [{"path": "ok/a.txt", "text": "1"}, {"path": "../evil", "text": "2"}, {"path": "/abs", "text": "3"}, {"path": "b", "text": 4}])
    assert n == 1 and (tmp_path / "g/ok/a.txt").read_text() == "1" and not (tmp_path / "evil").exists()


@pytest.fixture
def pair(qapp, tmp_path, pump):
    root = tmp_path / "host"; root.mkdir()
    (root / "a.py").write_text("print(1)\n"); (root / "venv").mkdir(); (root / "venv/x.py").write_text("x")
    h = S.ShareSession()
    h.host(root)
    yield h, root, tmp_path, pump
    h.stop()


def connect(h, tmp_path, pump, name="Anna", token=None):
    g = S.ShareSession()
    got = []
    g.welcome.connect(lambda p, f: got.append((p, f)))
    code = h.join_code("127.0.0.1")
    if token:
        code = code.rsplit("/", 1)[0] + "/" + token
    g.join(code, name, tmp_path / name)
    return g, got


def test_guest_receives_files_without_environments_and_edits_flow_both_ways(pair):
    h, root, tmp, pump = pair
    g, got = connect(h, tmp, pump)
    pump(lambda: got, 10)
    proj, files = got[0]
    assert proj == "host" and [f["path"] for f in files] == ["a.py"]
    pump(lambda: h.peers, 5)
    assert list(h.peers.values()) == ["Anna"]
    from_host, from_guest = [], []
    g.remoteEdit.connect(lambda *a: from_host.append(a)); h.remoteEdit.connect(lambda *a: from_guest.append(a))
    h.send_edit("a.py", "print(2)\n")
    g.send_edit("a.py", "print(3)\n")
    pump(lambda: from_host and from_guest, 10)
    assert from_host == [("a.py", "print(2)\n", "Host")] and from_guest == [("a.py", "print(3)\n", "Anna")]
    g.stop()


def test_wrong_token_is_denied(pair):
    h, root, tmp, pump = pair
    g, got = connect(h, tmp, pump, token="falsch")
    msgs = []
    g.status.connect(msgs.append)
    pump(lambda: msgs, 10)
    assert got == [] and h.peers == {} and "abgelehnt" in msgs[-1] and not g.active


def test_guest_edit_to_unknown_or_escaping_path_is_dropped_and_read_only_blocks(pair):
    h, root, tmp, pump = pair
    g, got = connect(h, tmp, pump)
    pump(lambda: got, 10); pump(lambda: h.peers, 5)
    seen = []
    h.remoteEdit.connect(lambda *a: seen.append(a))
    g.send_edit("../evil.py", "x"); g.send_edit("neu.py", "x")
    h.read_only = True
    g.send_edit("a.py", "blockiert")
    pump(lambda: False, 0.5)
    assert seen == []
    h.read_only = False
    g.send_edit("a.py", "ok")
    pump(lambda: seen, 5)
    assert seen == [("a.py", "ok", "Anna")]
    g.stop()


def test_bad_code_is_rejected(qapp):
    with pytest.raises(ValueError):
        S.ShareSession().join("keincode")


def test_two_windows_share_a_project_live(qapp, tmp_path, pump):
    from vds.app import MainWindow
    host_root = tmp_path / "proj"; host_root.mkdir()
    (host_root / "a.py").write_text("x = 1\n")
    hw, gw = MainWindow(), MainWindow()
    try:
        hw.set_root(host_root); hw.docs.open(host_root / "a.py")
        hw.share_host()
        gw.share_join(hw.share.join_code("127.0.0.1"), "Anna", tmp_path / "gast")
        pump(lambda: gw.root == tmp_path / "gast" / "proj", 10)
        assert (gw.root / "a.py").read_text() == "x = 1\n"
        gdoc = gw.docs.open(gw.root / "a.py")
        gdoc.view.setPlainText("x = 2\n")                                  # Gast tippt -> Host-Editor ändert sich
        pump(lambda: hw.docs.current_doc().view.toPlainText() == "x = 2\n", 10)
        hw.docs.current_doc().view.setPlainText("x = 3\n")                 # Host tippt -> Gast-Editor ändert sich
        pump(lambda: gdoc.view.toPlainText() == "x = 3\n", 10)
        assert hw.docs.current_doc().view.toPlainText() == "x = 3\n"
    finally:
        hw.share.stop(); gw.share.stop()
        for w in (hw, gw):
            w.docs.close_all(); w.preview.shutdown(); w.close()
