"""Node.js-Debugging über den eingebauten V8-Inspector-Adapter."""
from conftest import needs
from vds.debug.session import Bp, DebugSession, node_spec


@needs("node")
def test_node_breakpoint_variables_step_exception(qapp, pump, tmp_path):
    f = tmp_path / "demo.js"
    f.write_text("function fak(n) {\n  let ergebnis = 1;\n  for (let i = 2; i <= n; i++) {\n    ergebnis *= i;\n  }\n  return ergebnis;\n}\n"
                 "const liste = [1, 2, 3];\nconst obj = { name: 'Welt', zahl: 42 };\nconst y = fak(3);\nconsole.log('fertig', y);\nthrow new Error('absichtlich');\n")
    s = DebugSession()
    log = {"paused": [], "out": [], "ended": None, "frames": None, "seen": {}}
    s.output.connect(lambda t, k: log["out"].append(t))
    s.framesChanged.connect(lambda fr, sel: log.__setitem__("frames", [(x.name, x.line) for x in fr]))
    s.ended.connect(lambda c: log.__setitem__("ended", c))

    def on_pause(reason, text):
        log["paused"].append((reason, text))
        n = len(log["paused"])
        if n == 1:
            def got_scopes(scs):
                log["seen"]["scopes"] = [x[0] for x in scs]
                for name, ref in scs:
                    s.variables(ref, lambda vs, nm=name: log["seen"].setdefault(nm, {v["name"]: (v["value"], v["type"], v["ref"]) for v in vs}))
            s.scopes(got_scopes)
            s.evaluate("ergebnis * 100", lambda ok, r, t, ref: log["seen"].setdefault("eval", r))
            s.evaluate("nichtDa + 1", lambda ok, r, t, ref: log["seen"].setdefault("evalfail", (ok, r)))
            qapp.processEvents()
            import time; time.sleep(0.5); qapp.processEvents()
            s.step_over()
        elif reason == "exception":
            s.stop()
        else:
            s.resume()
    s.paused.connect(on_pause)
    s.start(node_spec(f, tmp_path), tmp_path, {str(f): [Bp(4)]})
    assert pump(lambda: log["ended"] is not None, 25), (log["paused"], log["out"], log["frames"], log["seen"], s.state)
    assert log["paused"][0][0] == "breakpoint"
    assert log["frames"][0][0] in ("fak", "<module>")
    loc = log["seen"].get("Locals", {})
    assert "n" in str(log["seen"]) and log["seen"]["eval"] == "100"
    assert log["seen"]["evalfail"][0] is False and "nichtDa" in log["seen"]["evalfail"][1]
    assert any(p[0] == "step" for p in log["paused"])
    assert log["paused"][-1][0] == "exception" and "absichtlich" in log["paused"][-1][1]
    assert "fertig 6" in "".join(log["out"])


@needs("node")
def test_node_object_expansion_and_stdin(qapp, pump, tmp_path):
    f = tmp_path / "obj.js"
    f.write_text("const obj = { name: 'Welt', zahl: 42, liste: [1, 2] };\ndebugger;\nprocess.stdin.once('data', d => { console.log('gelesen', d.toString().trim()); });\n")
    s = DebugSession()
    seen = {"out": [], "ended": None}
    s.output.connect(lambda t, k: seen["out"].append(t))
    s.ended.connect(lambda c: seen.__setitem__("ended", c))

    def on_pause(reason, text):
        def got(scs):
            ref = next(r for n, r in scs if n in ("Locals", "Script", "Module"))
            def got_vars(vs):
                o = next((v for v in vs if v["name"] == "obj"), None)
                seen["obj"] = o
                if o and o["ref"]:
                    s.variables(o["ref"], lambda inner: (seen.__setitem__("inner", {v["name"]: v["value"] for v in inner}), s.resume()))
                else:
                    s.resume()
            s.variables(ref, got_vars)
        s.scopes(got)
    s.paused.connect(on_pause)
    s.start(node_spec(f, tmp_path), tmp_path, {})
    assert pump(lambda: "inner" in seen, 30)
    assert seen["obj"]["type"] and seen["inner"]["name"] == "'Welt'" and seen["inner"]["zahl"] == "42"
    s.write_stdin("hallo\n")
    assert pump(lambda: "gelesen hallo" in "".join(seen["out"]), 20)
    s.stop()                       # Node lebt weiter, solange stdin offen ist
    assert pump(lambda: seen["ended"] is not None, 10)
