"""Optionaler Praxistest mit einem echten Laravel-Projekt (composer create-project laravel/laravel …): VDS_LARAVEL_DIR=<Projektordner> setzen."""
import os
import socket
import urllib.request
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from vds.app import MainWindow
from vds.project import ProjectSettings
from vds.web import source_map, writer

LARAVEL = os.environ.get("VDS_LARAVEL_DIR")
pytestmark = pytest.mark.skipif(not LARAVEL or not (Path(LARAVEL or "x") / "artisan").exists(), reason="VDS_LARAVEL_DIR nicht gesetzt")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_laravel_serve_preview_pick_and_source_lookup(qapp, pump, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    root = Path(LARAVEL).resolve()
    port = free_port()
    ProjectSettings(run_cmd=f"php artisan serve --port={port}").save(root)
    w = MainWindow(); w.show(); w.set_root(root)
    try:
        w.dbg.start()
        assert pump(lambda: w.d_preview.isVisible() and f":{port}" in w.preview.url.text(), 40)       # „Server running on [http://127.0.0.1:…]“ erkannt
        assert pump(lambda: w.preview.page.url().toString().startswith(f"http://127.0.0.1:{port}"), 40)
        out = []
        assert pump(lambda: (w.preview.eval("document.querySelector('h1') ? document.querySelector('h1').textContent : ''", out.append) or True) and out and out[-1], 40)
        w.preview.set_mode("pick"); pump(lambda: False, 0.3)
        w.preview.eval("document.querySelector('h1').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}))")
        assert pump(lambda: w.inspector.info and w.inspector.info["tag"] == "h1", 20)
        info = w.inspector.info
        cands = source_map.search(root, info)
        assert cands and cands[0].file.name == "welcome.blade.php"                                    # Blade-Vorlage mit Tailwind-Klassen gefunden
        plans = writer.plan_style(root, info, {"color": "#ff0000"}, cands)
        assert plans and plans[0].kind == "tailwind" and "text-[#ff0000]" in plans[0].new            # Laravel nutzt Tailwind → Klassen statt Inline-Style
        assert any(p.kind == "inline" for p in plans)
        w.stop_any()
        assert pump(lambda: not w.runner.busy, 20)
        with pytest.raises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)                          # Server wirklich beendet
    finally:
        w.docs.close_all(); w.close()
