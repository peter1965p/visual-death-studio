"""LSP: Vorschläge, Umbenennen über Dateigrenzen, Verweise, Formatieren, Codeaktionen – mit pylsp (Python) und clangd (C++)."""
from pathlib import Path

from conftest import needs
from vds.editor.documents import Documents
from vds.lsp.edits import apply_edits
from vds.lsp.manager import LspManager
from vds.lsp.ranking import rank


def _setup(qapp, pump, root: Path, files: list, lang_key: str):
    docs, m = Documents(), LspManager()
    m.set_root(root)
    status = []
    m.statusChanged.connect(lambda l, t: status.append((l, t)))
    ds = [docs.open(root / f) for f in files]
    for d in ds:
        m.attach(d)
    assert pump(lambda: (lang_key, "bereit") in status, 30), status
    pump(lambda: all(str(d.path) in m.servers[lang_key].opened for d in ds), 10)
    return docs, m, ds


def _ask(pump, fn, *args):
    box = {}
    fn(*args, lambda *r: box.setdefault("r", r))
    assert pump(lambda: "r" in box, 20)
    return box["r"]


def test_python_rename_across_files_references_and_completion(qapp, pump, tmp_path):
    (tmp_path / "tools.py").write_text("def berechne_summe(zahlen):\n    return sum(zahlen)\n")
    (tmp_path / "main.py").write_text("from tools import berechne_summe\n\nergebnis = berechne_summe([1, 2])\nprint(berechne_summe([3]))\nmath.sq\n")
    docs, m, (d1, d2) = _setup(qapp, pump, tmp_path, ["tools.py", "main.py"], "python")
    assert m.supports(tmp_path / "main.py", "rename") and m.supports(tmp_path / "main.py", "references")
    # Verweise auf die Funktion (aus main.py, Zeile 3)
    refs, = _ask(pump, m.references, tmp_path / "main.py", 2, 14)
    assert {Path(p).name for p, *_ in refs} == {"tools.py", "main.py"} and len(refs) >= 4
    # Umbenennen über beide Dateien
    edits, err = _ask(pump, m.rename, tmp_path / "main.py", 2, 14, "summiere")
    assert not err, err
    new = {Path(p).name: apply_edits(Path(p).read_text(), e) for p, e in edits.items()}
    assert new["tools.py"].startswith("def summiere(zahlen)")
    assert new["main.py"].count("summiere") == 3 and "berechne_summe" not in new["main.py"]      # Import + 2 Aufrufe
    # Vorschläge werden mit Wörtern aus der Datei kombiniert und kontextabhängig sortiert
    items, = _ask(pump, m.complete, tmp_path / "main.py", 3, 10, None)
    assert rank(items, "berechne_s", m.local_words(tmp_path / "main.py"))[0]["name"] == "berechne_summe"
    m.shutdown()


def test_python_code_actions_offer_refactorings(qapp, pump, tmp_path):
    (tmp_path / "a.py").write_text("def f(x):\n    y = x * 2 + 1\n    return y\n")
    docs, m, (d,) = _setup(qapp, pump, tmp_path, ["a.py"], "python")
    acts, = _ask(pump, m.code_actions, tmp_path / "a.py", 1, 8, 1, 17)
    titles = [a["title"] for a in acts]
    assert any("xtract" in t or "ariable" in t or "ethod" in t for t in titles), titles
    m.shutdown()


@needs("clangd")
def test_cpp_rename_references_and_format(qapp, pump, tmp_path):
    (tmp_path / "main.cpp").write_text("#include <iostream>\n\nint verdoppeln(int zahl) {\nreturn zahl*2;\n}\n\nint main() {\n  int a=verdoppeln(3);\n    std::cout<<verdoppeln(a)<<std::endl;\n}\n")
    docs, m, (d,) = _setup(qapp, pump, tmp_path, ["main.cpp"], "cpp")
    p = tmp_path / "main.cpp"
    refs, = _ask(pump, m.references, p, 2, 5)
    assert len(refs) == 3
    edits, err = _ask(pump, m.rename, p, 2, 5, "doppelt")
    assert not err
    renamed = apply_edits(p.read_text(), edits[str(p)])
    assert renamed.count("doppelt") == 3 and "verdoppeln" not in renamed
    fmt, err = _ask(pump, m.format_document, p)
    assert not err and fmt and str(p) in fmt
    m.shutdown()
