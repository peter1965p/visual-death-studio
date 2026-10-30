"""Profiler: CPU- und Speichermessung eines Skripts im Projekt-Interpreter."""
import sys
from pathlib import Path

from PySide6.QtCore import Qt

from vds.app import MainWindow
from vds.docks.profiler import ProfilerPanel, fmt_bytes

SCRIPT = '''import sys
def slow():
    return sum(i * i for i in range(300000))
def hold():
    return [bytes(1000) for _ in range(2000)]
x = slow(); y = hold()
print("fertig", sys.argv[1:])
'''


def test_fmt_bytes():
    assert fmt_bytes(512) == "512 B" and fmt_bytes(2048) == "2.0 KB" and fmt_bytes(3 * 1024 ** 2) == "3.0 MB"


def run(qapp, pump, tmp_path, mode):
    s = tmp_path / "prog.py"; s.write_text(SCRIPT)
    p = ProfilerPanel(); p.set_root(tmp_path); p.interpreter = lambda: sys.executable
    p.mode.setCurrentIndex(mode)
    logs, done = [], []
    p.log.connect(logs.append); p.finished.connect(done.append)
    assert p.start(s, ["a"]) and not p.start(s)
    pump(lambda: done, 30)
    assert done == [True]
    return p, logs


def test_cpu_profile_lists_functions_sorted_by_time(qapp, pump, tmp_path):
    p, logs = run(qapp, pump, tmp_path, 0)
    names = [p.tree.topLevelItem(i).text(0) for i in range(p.tree.topLevelItemCount())]
    assert any(n.startswith("slow") for n in names) and "fertig ['a']" in "".join(logs)
    assert not any("runpy" in n or "pstats" in n for n in names)           # Fremdcode ist ausgeblendet
    p.only_project.setChecked(False)
    assert p.tree.topLevelItemCount() > len(names)


def test_memory_profile_reports_peak_and_lines(qapp, pump, tmp_path):
    p, _ = run(qapp, pump, tmp_path, 1)
    top = p.tree.topLevelItem(0)
    assert top.text(0).startswith("prog.py:") and "Spitze" in p.info.text()
    got = []
    p.jumpTo.connect(lambda f, l: got.append((f, l)))
    p._open(top)
    assert got and got[0][0].endswith("prog.py")


def test_main_window_profiler_refuses_non_python_and_runs_python(qapp, pump, tmp_path):
    (tmp_path / "prog.py").write_text(SCRIPT)
    win = MainWindow()
    try:
        win.set_root(tmp_path)
        assert win.start_profiler() is False and "Python" in win.profiler.info.text()
        win.docs.open(tmp_path / "prog.py")
        done = []
        win.profiler.finished.connect(done.append)
        assert win.start_profiler()
        pump(lambda: done, 30)
        assert done == [True] and win.profiler.tree.topLevelItemCount() > 0
    finally:
        win.docs.close_all(); win.preview.shutdown(); win.close()
