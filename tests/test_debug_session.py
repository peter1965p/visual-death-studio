"""Debug-Sitzung gegen echte Adapter: Python (debugpy) und C (gdb)."""
from pathlib import Path

from conftest import needs
from vds.debug.session import Bp, DebugSession, native_spec, python_spec


def _run(qapp, pump, spec, root, bps, on_pause, secs=40):
    s = DebugSession()
    log = {"paused": [], "out": [], "ended": None, "frames": None}
    s.output.connect(lambda t, k: log["out"].append(t))
    s.framesChanged.connect(lambda fr, sel: log.__setitem__("frames", [(f.name, f.line) for f in fr]))
    s.paused.connect(lambda reason, text: (log["paused"].append((reason, text)), on_pause(s, len(log["paused"]), reason)))
    s.ended.connect(lambda code: log.__setitem__("ended", code))
    s.start(spec, root, bps)
    pump(lambda: log["ended"] is not None, secs)
    return s, log


def test_python_breakpoint_step_and_exception(qapp, pump, tmp_path):
    f = tmp_path / "demo.py"
    f.write_text("def fak(n):\n    ergebnis = 1\n    for i in range(2, n + 1):\n        ergebnis *= i\n    return ergebnis\n\n\ny = fak(3)\nprint('fertig', y)\nraise ValueError('absichtlich')\n")
    seen = {}

    def on_pause(s, n, reason):
        if n == 1:
            s.scopes(lambda sc: s.variables(sc[0][1], lambda vs: seen.setdefault("locals", {v["name"]: v["value"] for v in vs})))
            s.evaluate("ergebnis + 1000", lambda ok, r, t, ref: seen.setdefault("eval", r))
            qapp.processEvents()
            s.step_over()
        elif reason == "exception":
            s.stop()
        else:
            s.resume()
    import sys
    s, log = _run(qapp, pump, python_spec(f, sys.executable), tmp_path, {str(f): [Bp(4)]}, on_pause)
    assert log["paused"][0][0] == "breakpoint"
    assert seen["locals"]["n"] == "3" and seen["eval"] == "1001"
    assert any(p[0] == "step" for p in log["paused"])
    assert log["paused"][-1] == ("exception", "ValueError: absichtlich")
    assert "fertig 6" in "".join(log["out"])


@needs("gdb")
@needs("gcc")
def test_c_breakpoint_locals_and_exit(qapp, pump, tmp_path):
    src = tmp_path / "prog.c"
    src.write_text("#include <stdio.h>\n\nint fak(int n) {\n    int e = 1;\n    for (int i = 2; i <= n; i++) {\n        e *= i;\n    }\n    return e;\n}\n\nint main(void) {\n    printf(\"fertig %d\\n\", fak(4));\n    return 0;\n}\n")
    import subprocess
    subprocess.run(["gcc", "-g", "-O0", str(src), "-o", str(tmp_path / "prog")], check=True)
    seen = {}

    def on_pause(s, n, reason):
        if n == 1:
            s.scopes(lambda sc: [s.variables(ref, lambda vs, nm=nm: seen.setdefault(nm, {v["name"]: v["value"] for v in vs})) for nm, ref in sc if nm != "Registers"])
            qapp.processEvents()
            from time import sleep; sleep(0.3); qapp.processEvents()
            s.step_over()
        elif n == 2:
            s.set_breakpoints(str(src), [])
            s.resume()
        else:
            s.resume()
    s, log = _run(qapp, pump, native_spec(tmp_path / "prog", tmp_path), tmp_path, {str(src): [Bp(6)]}, on_pause)
    assert log["frames"][0][0] in ("fak", "main")
    assert seen.get("Arguments", {}).get("n") == "4"
    assert log["ended"] == 0 and "fertig 24" in "".join(log["out"])


def test_python_module_launch_debugs_a_single_test(qapp, pump, tmp_path):
    """python -m pytest <Test-ID> unter dem Debugger – Haltepunkt im getesteten Code."""
    import sys
    from vds.debug.session import python_module_spec
    (tmp_path / "rechner.py").write_text("def add(a, b):\n    ergebnis = a + b\n    return ergebnis\n")
    (tmp_path / "test_rechner.py").write_text("from rechner import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    seen = {}

    def on_pause(s, n, reason):
        s.scopes(lambda sc: s.variables(sc[0][1], lambda vs: seen.setdefault("locals", {v["name"]: v["value"] for v in vs})))
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1000, s.resume)
    spec = python_module_spec("pytest", ["-p", "no:cacheprovider", "test_rechner.py::test_add"], tmp_path, sys.executable)
    s, log = _run(qapp, pump, spec, tmp_path, {str(tmp_path / "rechner.py"): [Bp(3)]}, on_pause)
    assert log["paused"][0][0] == "breakpoint" and log["frames"][0] == ("add", 3)
    assert seen["locals"]["ergebnis"] == "5" and log["ended"] == 0


@needs("gdb")
@needs("rustc")
def test_rust_breakpoint_locals_and_exit(qapp, pump, tmp_path):
    src = tmp_path / "prog.rs"
    src.write_text('fn fak(n: u32) -> u32 {\n    let mut e = 1;\n    for i in 2..=n {\n        e *= i;\n    }\n    e\n}\n\nfn main() {\n    println!("fertig {}", fak(4));\n}\n')
    import subprocess
    subprocess.run(["rustc", "-g", str(src), "-o", str(tmp_path / "prog")], check=True, cwd=tmp_path)
    seen = {}

    def on_pause(s, n, reason):
        if n == 1:
            s.scopes(lambda sc: [s.variables(ref, lambda vs, nm=nm: seen.setdefault(nm, {v["name"]: v["value"] for v in vs})) for nm, ref in sc if nm != "Registers"])
            from time import sleep; qapp.processEvents(); sleep(0.4); qapp.processEvents()
            s.set_breakpoints(str(src), []); s.resume()
        else:
            s.resume()
    s, log = _run(qapp, pump, native_spec(tmp_path / "prog", tmp_path), tmp_path, {str(src): [Bp(4)]}, on_pause, secs=60)
    assert log["paused"] and log["paused"][0][0] == "breakpoint"
    assert log["frames"][0][0].endswith("fak")
    assert seen.get("Arguments", {}).get("n") == "4" or seen.get("Locals", {}).get("n") == "4" or "4" in str(seen)
    assert log["ended"] == 0 and "fertig 24" in "".join(log["out"])
