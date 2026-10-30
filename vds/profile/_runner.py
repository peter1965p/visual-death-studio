"""Läuft im Interpreter des Projekts (nur Standardbibliothek): führt ein Skript unter cProfile oder tracemalloc aus und schreibt das Ergebnis als JSON.

Aufruf: python _runner.py AUSGABE.json cpu|memory SKRIPT [ARGUMENTE …]"""
import json
import os
import runpy
import sys
import time


def _run(script, args):
    sys.argv = [script, *args]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit:
        pass


def main():
    out, mode, script, args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    t0 = time.perf_counter()
    result = {"mode": mode, "script": script, "rows": []}
    if mode == "cpu":
        import cProfile
        import pstats
        pr = cProfile.Profile()
        try:
            pr.enable()
            _run(script, args)
        finally:
            pr.disable()
            st = pstats.Stats(pr)
            rows = [{"file": f, "line": ln, "func": fn, "calls": nc, "tottime": tt, "cumtime": ct}
                    for (f, ln, fn), (cc, nc, tt, ct, _) in st.stats.items()]
            rows.sort(key=lambda r: -r["cumtime"])
            result["rows"] = rows[:400]
    else:
        import tracemalloc
        tracemalloc.start(10)
        try:
            _run(script, args)
        finally:
            cur, peak = tracemalloc.get_traced_memory()
            snap = tracemalloc.take_snapshot().filter_traces([tracemalloc.Filter(False, tracemalloc.__file__), tracemalloc.Filter(False, "<frozen *>")])
            tracemalloc.stop()
            result["current"], result["peak"] = cur, peak
            result["rows"] = [{"file": s.traceback[0].filename, "line": s.traceback[0].lineno, "size": s.size, "count": s.count}
                              for s in snap.statistics("lineno")[:300]]
    result["seconds"] = time.perf_counter() - t0
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
