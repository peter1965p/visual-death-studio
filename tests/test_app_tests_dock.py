"""Hauptfenster: Test-Explorer-Dock entdeckt und führt Tests eines Projekts aus."""
import textwrap

from vds.app import MainWindow


def test_test_explorer_in_main_window(qapp, pump, tmp_path):
    (tmp_path / "test_x.py").write_text(textwrap.dedent('''
        def test_gut():
            assert True

        def test_schlecht():
            assert 1 == 2
    '''))
    w = MainWindow()
    w.show()
    w.set_root(tmp_path)
    assert pump(lambda: len(w.p_tests.leaves) == 2, 30)
    w.tests.run(None)
    assert pump(lambda: not w.tests.busy and len(w.tests.results) == 2, 40)
    st = w.p_tests.status
    assert st["test_x.py::test_gut"] == "passed" and st["test_x.py::test_schlecht"] == "failed"
    assert "✓ 1" in w.p_tests.summary.text() and "✕ 1" in w.p_tests.summary.text()
    # Filter: nur Fehlgeschlagene
    w.p_tests.filter.setCurrentIndex(1)
    visible = [i for i, leaf in w.p_tests.leaves.items() if not leaf.isHidden()]
    assert visible == ["test_x.py::test_schlecht"]
    # Details zeigen die Fehlermeldung
    w.p_tests.tree.setCurrentItem(w.p_tests.leaves["test_x.py::test_schlecht"])
    assert "assert 1 == 2" in w.p_tests.detail.toPlainText()
    w.docs.close_all()
    w.close()
