"""Java-Debugging über JDWP + jdb (-attach)."""
import subprocess

from conftest import needs
from vds.debug.adapters.java_jdb import scan_classes
from vds.debug.session import Bp, DebugSession, java_spec

PROGRAM = """import java.util.*;

public class Main {
    static class Punkt { int x = 3; String name = "P"; }

    static int fak(int n) {
        int ergebnis = 1;
        for (int i = 2; i <= n; i++) {
            ergebnis *= i;
        }
        return ergebnis;
    }

    public static void main(String[] args) {
        Punkt p = new Punkt();
        String text = "Hallo";
        int y = fak(4);
        System.out.println("fertig " + y);
        throw new IllegalStateException("absichtlich");
    }
}
"""


def test_scan_classes_nested():
    cls = scan_classes("package a.b;\npublic class Outer {\n  class In { int x; }\n  void f() { String s = \"class X {\"; }\n}\n", "a.b.")
    assert [c[0] for c in cls] == ["a.b.Outer", "a.b.Outer$In"]


@needs("javac")
@needs("jdb")
def test_java_breakpoint_locals_condition_object_and_exception(qapp, pump, tmp_path):
    src = tmp_path / "Main.java"
    src.write_text(PROGRAM)
    subprocess.run(["javac", "-g", "-d", str(tmp_path / "out"), str(src)], check=True)
    s = DebugSession()
    log = {"paused": [], "out": [], "ended": None, "seen": {}}
    s.output.connect(lambda t, k: log["out"].append(t))
    s.ended.connect(lambda c: log.__setitem__("ended", c))
    s.framesChanged.connect(lambda fr, sel: log["seen"].setdefault("frames", [(f.name, f.line) for f in fr]))

    from PySide6.QtCore import QTimer

    def inspect_main_frame():
        """In den main-Frame wechseln, das Objekt p aufklappen, Haltepunkt entfernen und weiterlaufen."""
        s.select_frame(1)

        def got(scs):
            def expand(vs):
                p = next((v for v in vs if v["name"] == "p"), None)
                log["seen"]["p"] = p
                if p and p["ref"]:
                    s.variables(p["ref"], lambda inner: log["seen"].setdefault("p_fields", {v["name"]: v["value"] for v in inner}))
            s.variables(scs[0][1], expand)
        s.scopes(got)
        QTimer.singleShot(1500, lambda: (s.set_breakpoints(str(src), []), s.resume()))

    def on_pause(reason, text):
        log["paused"].append((reason, text))
        if len(log["paused"]) == 1:
            def got_scopes(scs):
                s.variables(scs[0][1], lambda vs: log["seen"].setdefault("locals", {v["name"]: v["value"] for v in vs}))
            s.scopes(got_scopes)
            s.evaluate("ergebnis * 100", lambda ok, r, t, ref: log["seen"].setdefault("eval", r))
            s.evaluate("nichtDa", lambda ok, r, t, ref: log["seen"].setdefault("evalfail", ok))
            QTimer.singleShot(1500, inspect_main_frame)
        elif reason == "exception":
            s.stop()
        else:
            s.resume()
    s.paused.connect(on_pause)
    s.start(java_spec("Main", tmp_path / "out", tmp_path, tmp_path), tmp_path, {str(src): [Bp(9, "i == 3")]})
    assert pump(lambda: log["ended"] is not None, 45), (log["paused"], log["out"], log["seen"], s.state)
    assert log["paused"][0][0] == "breakpoint"                        # bedingt: erst bei i == 3
    seen = log["seen"]
    assert seen["frames"][0][0] == "Main.fak" and seen["frames"][0][1] == 9
    assert seen["locals"]["n"] == "4" and seen["locals"]["i"] == "3"
    assert seen["eval"] == "200" and seen["evalfail"] is False
    assert seen["p"]["type"].endswith("Punkt") and seen["p_fields"] == {"x": "3", "name": '"P"'}
    assert log["paused"][-1][0] == "exception" and "IllegalStateException" in log["paused"][-1][1]
    assert "fertig 24" in "".join(log["out"])


@needs("javac")
@needs("jdb")
def test_java_stdin_reaches_program(qapp, pump, tmp_path):
    src = tmp_path / "Echo.java"
    src.write_text("public class Echo {\n    public static void main(String[] a) throws Exception {\n        var r = new java.io.BufferedReader(new java.io.InputStreamReader(System.in));\n        System.out.println(\"Hallo \" + r.readLine());\n    }\n}\n")
    subprocess.run(["javac", "-g", "-d", str(tmp_path / "out"), str(src)], check=True)
    s = DebugSession()
    seen = {"out": [], "ended": None}
    s.output.connect(lambda t, k: seen["out"].append(t))
    s.ended.connect(lambda c: seen.__setitem__("ended", c))
    s.start(java_spec("Echo", tmp_path / "out", tmp_path, tmp_path), tmp_path, {})
    pump(lambda: s.state == "running", 20)
    s.write_stdin("Welt\n")
    assert pump(lambda: seen["ended"] is not None, 20), seen
    assert "Hallo Welt" in "".join(seen["out"]) and seen["ended"] == 0
