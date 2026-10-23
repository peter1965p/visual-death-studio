"""Go (Delve) und C# (netcoredbg) – laufen nur, wenn dlv/go bzw. netcoredbg/dotnet installiert sind."""
import subprocess

from conftest import needs
from vds.debug.session import Bp, DebugSession, csharp_spec, go_spec
from vds.debug.tools import find


def _drive(qapp, pump, spec, root, bps, secs=90):
    from PySide6.QtCore import QTimer
    s = DebugSession()
    log = {"paused": [], "out": [], "ended": None, "seen": {}, "frames": None}
    s.output.connect(lambda t, k: log["out"].append(t))
    s.ended.connect(lambda c: log.__setitem__("ended", c))
    s.framesChanged.connect(lambda fr, sel: log["seen"].setdefault("frames", [(f.name, f.line) for f in fr]))

    def on_pause(reason, text):
        log["paused"].append((reason, text))
        if len(log["paused"]) == 1:
            def got(scs):
                for name, ref in scs:
                    s.variables(ref, lambda vs, nm=name: log["seen"].setdefault(nm, {v["name"]: v["value"] for v in vs}))
            s.scopes(got)
            s.evaluate("ergebnis * 100", lambda ok, r, t, ref: log["seen"].setdefault("eval", (ok, r)))
            QTimer.singleShot(2000, lambda: (s.set_breakpoints(list(bps)[0], []), s.resume()))
        else:
            s.resume()
    s.paused.connect(on_pause)
    s.start(spec, root, bps)
    pump(lambda: log["ended"] is not None, secs)
    return s, log


@needs("dlv")
@needs("go")
def test_go_breakpoint_locals_and_exit(qapp, pump, tmp_path):
    (tmp_path / "go.mod").write_text("module demo\n\ngo 1.22\n")
    src = tmp_path / "main.go"
    src.write_text('package main\n\nimport "fmt"\n\nfunc fak(n int) int {\n\tergebnis := 1\n\tfor i := 2; i <= n; i++ {\n\t\tergebnis *= i\n\t}\n\treturn ergebnis\n}\n\nfunc main() {\n\tfmt.Println("fertig", fak(4))\n}\n')
    s, log = _drive(qapp, pump, go_spec(tmp_path, tmp_path, find("dlv")), tmp_path, {str(src): [Bp(8)]})
    assert log["paused"] and log["paused"][0][0] == "breakpoint", log
    assert log["seen"]["frames"][0][0].endswith("fak") and log["seen"]["frames"][0][1] == 8
    loc = next(v for k, v in log["seen"].items() if k in ("Locals", "Arguments") and "ergebnis" in v)
    assert loc["ergebnis"] == "1"
    assert log["seen"]["eval"] == (True, "100")
    assert "fertig 24" in "".join(log["out"]) and log["ended"] is not None


@needs("netcoredbg")
@needs("dotnet")
def test_csharp_breakpoint_locals_and_exit(qapp, pump, tmp_path):
    (tmp_path / "App.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n    <TargetFramework>net10.0</TargetFramework>\n    <ImplicitUsings>enable</ImplicitUsings>\n    <Nullable>enable</Nullable>\n  </PropertyGroup>\n</Project>\n')
    src = tmp_path / "Program.cs"
    src.write_text('static int Fak(int n)\n{\n    int ergebnis = 1;\n    for (int i = 2; i <= n; i++)\n    {\n        ergebnis *= i;\n    }\n    return ergebnis;\n}\n\nConsole.WriteLine("fertig " + Fak(4));\n')
    subprocess.run(["dotnet", "build", "-c", "Debug", "-v", "q"], cwd=tmp_path, check=True, capture_output=True)
    dll = next((tmp_path / "bin" / "Debug").glob("*/App.dll"))
    s, log = _drive(qapp, pump, csharp_spec(dll, tmp_path, find("netcoredbg")), tmp_path, {str(src): [Bp(6)]})
    assert log["paused"] and log["paused"][0][0] == "breakpoint", log
    assert "Fak" in log["seen"]["frames"][0][0] and log["seen"]["frames"][0][1] == 6
    assert any("ergebnis" in v for v in log["seen"].values() if isinstance(v, dict)), log["seen"]
    assert "fertig 24" in "".join(log["out"])
