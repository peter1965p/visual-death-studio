"""Test-Explorer-Dienst: Entdecken und Ausführen mit pytest, unittest und node:test."""
import sys
import textwrap

from conftest import needs
from vds.testing.service import TestService

PYTEST_FILE = textwrap.dedent('''
    import pytest

    def test_plus():
        assert 1 + 1 == 2

    def test_kaputt():
        assert 1 + 1 == 3

    @pytest.mark.skip(reason="absichtlich")
    def test_uebersprungen():
        pass

    class TestKlasse:
        def test_in_klasse(self):
            assert "a".upper() == "A"
''')

UNITTEST_FILE = textwrap.dedent('''
    import unittest

    class Rechnen(unittest.TestCase):
        def test_ok(self):
            self.assertEqual(2 * 3, 6)

        def test_fehler(self):
            self.assertEqual(2 * 3, 7)

        @unittest.skip("weg")
        def test_skip(self):
            pass
''')


def _discover_and_run(svc, pump, ids=None):
    svc.discover()
    assert pump(lambda: not svc.busy and svc.cases is not None, 30)
    n = len(svc.cases)
    svc.run(ids)
    assert pump(lambda: not svc.busy and bool(svc.results), 60)
    return n


def test_pytest_discovery_and_results(qapp, pump, tmp_path):
    (tmp_path / "test_beispiel.py").write_text(PYTEST_FILE)
    svc = TestService()
    svc.set_root(tmp_path, sys.executable)
    pytest_ok = svc.python and __import__("subprocess").run([sys.executable, "-c", "import pytest"], capture_output=True).returncode == 0
    assert pytest_ok
    n = _discover_and_run(svc, pump)
    assert n == 4
    r = svc.results
    assert r["test_beispiel.py::test_plus"].status == "passed"
    assert r["test_beispiel.py::test_kaputt"].status == "failed" and "assert" in r["test_beispiel.py::test_kaputt"].message
    assert r["test_beispiel.py::test_uebersprungen"].status == "skipped"
    assert r["test_beispiel.py::TestKlasse::test_in_klasse"].status == "passed"
    case = svc.cases["test_beispiel.py::test_kaputt"][1]
    assert case.file == "test_beispiel.py" and case.line == 7           # Sprung zur Definition


def test_selected_run_only_runs_selection(qapp, pump, tmp_path):
    (tmp_path / "test_beispiel.py").write_text(PYTEST_FILE)
    svc = TestService()
    svc.set_root(tmp_path, sys.executable)
    _discover_and_run(svc, pump, ["test_beispiel.py::test_plus"])
    assert list(svc.results) == ["test_beispiel.py::test_plus"]


def test_unittest_fallback_without_pytest(qapp, pump, tmp_path, monkeypatch):
    (tmp_path / "test_rechnen.py").write_text(UNITTEST_FILE)
    from vds.testing import frameworks
    monkeypatch.setattr(frameworks.Pytest, "detect", lambda self: False)      # so tun, als gäbe es kein pytest
    svc = TestService()
    svc.set_root(tmp_path, sys.executable)
    n = _discover_and_run(svc, pump)
    assert n == 3 and svc.frameworks[0].name == "unittest"
    r = svc.results
    assert r["test_rechnen.Rechnen.test_ok"].status == "passed"
    assert r["test_rechnen.Rechnen.test_fehler"].status == "failed" and "6 != 7" in r["test_rechnen.Rechnen.test_fehler"].message
    assert r["test_rechnen.Rechnen.test_skip"].status == "skipped"


@needs("node")
def test_node_test_runner(qapp, pump, tmp_path):
    (tmp_path / "rechnen.test.js").write_text(
        "const test = require('node:test');\nconst assert = require('node:assert');\n"
        "test('addiert', () => { assert.strictEqual(1 + 2, 3); });\n"
        "test('kaputt', () => { assert.strictEqual(1 + 2, 4); });\n")
    svc = TestService()
    svc.set_root(tmp_path, sys.executable)
    n = _discover_and_run(svc, pump)
    assert n == 2
    assert svc.results["rechnen.test.js::addiert"].status == "passed"
    assert svc.results["rechnen.test.js::kaputt"].status == "failed"
