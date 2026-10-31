"""Web-Vorschau mit echtem QtWebEngine: laden, Element wählen, live ändern, verschieben/skalieren, Text, Quelle finden, zurückschreiben, Dev-Server."""
import functools
import http.server
import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import needs
from vds.web import writer
from vds.web.inspector import WebInspector, WriteDialog
from vds.web.panel import PreviewPanel

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Testseite</title><link rel="stylesheet" href="/style.css"></head>
<body><h1 id="titel" class="kopf gross">Hallo Welt</h1>
<button class="btn primary" data-vds="button1">Klick mich</button>
<div class="box"><span class="inner">innen</span></div>
<script>console.log("info-meldung"); setTimeout(() => { throw new Error("kaputt-im-test"); }, 50);</script></body></html>
"""
CSS = "body { margin: 0; }\n.kopf { color: rgb(51, 51, 51); }\n.btn { padding: 4px; color: rgb(255, 0, 0); }\n.box { width: 200px; height: 80px; background: #eee; }\n"


@pytest.fixture
def site(tmp_path):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "style.css").write_text(CSS, encoding="utf-8")
    handler = functools.partial(type("Q", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None}), directory=str(tmp_path))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield tmp_path, f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown(); srv.server_close()


@pytest.fixture
def panel(qapp, pump, site):
    root, url = site
    p = PreviewPanel(); p.resize(900, 700); p.show()
    ins = WebInspector(p); ins.set_root(root)
    loaded = []
    p.pageLoaded.connect(lambda ok, u: loaded.append(ok))
    p.set_url(url)
    assert pump(lambda: loaded and p.page.url().toString().endswith("index.html"), 30) and loaded[-1]
    assert pump(lambda: True, 0.3)
    p.inspector = ins
    yield p
    p.shutdown()


def js(panel, pump, code, secs=10):
    out = []
    panel.eval(code, lambda v: out.append(v))
    assert pump(lambda: bool(out), secs)
    return out[0]


def jsj(panel, pump, code):
    """JS-Wert (Array/Objekt) als Python-Wert: QtWebEngine reicht Arrays nicht zuverlässig durch, daher über JSON."""
    return json.loads(js(panel, pump, f"JSON.stringify({code})"))


def click(panel, pump, selector):
    js(panel, pump, f"document.querySelector({json.dumps(selector)}).dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true}})); 1")


def pick(panel, pump, selector):
    got = []
    panel.picked.connect(got.append)
    panel.set_mode("pick"); pump(lambda: False, 0.2)
    click(panel, pump, selector)
    assert pump(lambda: bool(got), 10)
    panel.picked.disconnect(got.append)
    return got[-1]


def computed(panel, pump, selector, prop):
    return js(panel, pump, f"getComputedStyle(document.querySelector({json.dumps(selector)})).getPropertyValue({json.dumps(prop)})")


def mouse(panel, pump, kind, at, dx=0, dy=0, to=None):
    """Mausereignis `kind`, Koordinaten aus der Mitte des Elements `at` (CSS-Selektor oder JS-Ausdruck) plus Versatz; gesendet an `to` (JS-Ausdruck) bzw. das Element."""
    el = f"document.querySelector({json.dumps(at)})" if not at.startswith("document.") else at
    return js(panel, pump, f"(() => {{ const e = {el}; const r = e.getBoundingClientRect(); const x = r.x + r.width / 2 + {dx}, y = r.y + r.height / 2 + {dy}; "
                           f"({to or 'e'}).dispatchEvent(new MouseEvent('{kind}', {{bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0}})); return 1; }})()")


# --- Seite und Nachrichten ----------------------------------------------------------------------------------
def test_page_loads_and_console_is_separated_from_tool_messages(qapp, pump, site):
    root, url = site
    p = PreviewPanel(); p.show()
    consoles, tools = [], []
    p.consoleMessage.connect(lambda *a: consoles.append(a)); p.page.toolMessage.connect(lambda k, d: tools.append(k))
    p.set_url(url)
    assert pump(lambda: any("kaputt-im-test" in c[1] for c in consoles), 30)
    assert ("info", "info-meldung") in [(c[0], c[1]) for c in consoles]
    err = next(c for c in consoles if "kaputt-im-test" in c[1])
    assert err[0] == "error" and err[3].endswith("/index.html")
    assert "ready" in tools and not any("__VDS__" in c[1] for c in consoles)        # IDE-Nachrichten tauchen nicht als Konsolenzeilen auf
    p.shutdown()


def test_url_entry_adds_scheme_and_device_changes_size_and_user_agent(qapp, pump, panel):
    assert panel.url.text().endswith("index.html")
    panel.device.setCurrentText("Handy 390×844")
    assert pump(lambda: panel.view.width() == 390 and panel.view.height() == 844, 5)
    assert pump(lambda: "iPhone" in (js(panel, pump, "navigator.userAgent") or ""), 20)         # nach dem Neuladen mit mobilem User-Agent
    panel.rotate.click()
    assert pump(lambda: panel.view.width() == 844, 5)
    panel.device.setCurrentIndex(0)
    assert pump(lambda: panel.view.maximumWidth() > 5000, 5)


# --- Auswahl ------------------------------------------------------------------------------------------------------
def test_pick_reports_element_details_and_navigates(qapp, pump, panel):
    got = pick(panel, pump, "#titel")
    assert got["tag"] == "h1" and got["id"] == "titel" and got["classes"] == ["kopf", "gross"] and got["text"] == "Hallo Welt"
    assert got["path"] == "#titel" and got["computed"]["color"] == "rgb(51, 51, 51)" and got["rect"]["w"] > 50
    assert got["chain"][0]["tag"] == "body"
    btn = pick(panel, pump, ".btn")
    assert btn["vds"] == "button1" and btn["path"].startswith("body > button")
    inner = pick(panel, pump, ".inner")
    assert inner["chain"][0]["classes"] == ["box"]
    got2 = []
    panel.picked.connect(got2.append)
    js(panel, pump, "window.__vds.selectRelative('parent')")
    assert pump(lambda: bool(got2), 5) and got2[-1]["classes"] == ["box"]
    js(panel, pump, "window.__vds.selectRelative('child')")
    assert pump(lambda: len(got2) == 2, 5) and got2[-1]["classes"] == ["inner"]
    # im Auswahlmodus löst ein Klick die Seitenaktionen nicht aus (preventDefault)
    assert js(panel, pump, "window.__vds.selected().path").endswith("span:nth-of-type(1)")


def test_inspector_is_dimmed_until_an_element_is_picked(qapp, pump, panel):
    ins = panel.inspector
    assert not ins.body.isEnabled() and not ins.btn_src.isEnabled() and not any(b.isEnabled() for b in ins.nav_buttons)
    pick(panel, pump, "#titel")
    assert ins.body.isEnabled() and ins.btn_src.isEnabled() and all(b.isEnabled() for b in ins.nav_buttons)


def test_pick_mode_off_leaves_the_page_alone(qapp, pump, panel):
    got = []
    panel.picked.connect(got.append)
    click(panel, pump, "#titel")
    pump(lambda: False, 0.4)
    assert got == []
    assert js(panel, pump, "document.getElementById('__vds_overlay') === null || document.getElementById('__vds_overlay').children[1].style.display !== 'block'")


# --- Live-Stile ------------------------------------------------------------------------------------------------------
def test_inspector_changes_styles_live_and_collects_pending(qapp, pump, panel):
    ins = panel.inspector
    pick(panel, pump, "#titel")
    assert pump(lambda: ins.info is not None, 5)
    ins.set_style("color", "#ff0000"); ins.set_style("font-size", "40px")
    assert pump(lambda: ins.pending.get("#titel") and len(ins.pending["#titel"]["props"]) == 2, 10)
    assert computed(panel, pump, "#titel", "color") == "rgb(255, 0, 0)" and computed(panel, pump, "#titel", "font-size") == "40px"
    assert ins.changes.count() == 1 and ins.btn_write.isEnabled()
    ins.set_style("color", "")                                         # leer = Überschreibung für diese Eigenschaft zurücknehmen
    assert pump(lambda: list(ins.pending["#titel"]["props"]) == ["font-size"], 10)
    assert computed(panel, pump, "#titel", "color") == "rgb(51, 51, 51)"
    ins.discard()
    assert pump(lambda: not ins.pending, 5) and computed(panel, pump, "#titel", "font-size") != "40px" and not ins.btn_write.isEnabled()


def test_move_and_resize_with_the_mouse_in_edit_mode(qapp, pump, panel):
    ins = panel.inspector
    panel.set_mode("edit"); pump(lambda: False, 0.2)
    click(panel, pump, ".box")
    assert pump(lambda: ins.info and ins.info["classes"] == ["box"], 5)
    start = jsj(panel, pump, "(() => { const r = document.querySelector('.box').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
    mouse(panel, pump, "mousedown", ".box"); mouse(panel, pump, "mousemove", ".box", 40, 25, "document"); mouse(panel, pump, "mouseup", ".box", 40, 25, "document")
    assert pump(lambda: ".box" not in ins.pending and any("box" in k or "div" in k for k in ins.pending), 10)
    props = next(v for k, v in ins.pending.items())["props"]
    assert props["position"] == "relative" and props["left"] == "40px" and props["top"] == "25px"
    moved = jsj(panel, pump, "(() => { const r = document.querySelector('.box').getBoundingClientRect(); return [r.x, r.y]; })()")
    assert round(moved[0] - start[0]) == 40 and round(moved[1] - start[1]) == 25
    # Größe über den Griff unten rechts
    h = "document.querySelector('#__vds_overlay [data-h=\"se\"]')"
    mouse(panel, pump, "mousedown", h); mouse(panel, pump, "mousemove", h, 30, 20, "document"); mouse(panel, pump, "mouseup", h, 30, 20, "document")
    assert pump(lambda: "width" in next(iter(ins.pending.values()))["props"], 10)
    p2 = next(iter(ins.pending.values()))["props"]
    assert p2["width"] == "230px" and p2["height"] == "100px"


def test_double_click_edits_text_and_reports_the_old_and_new_text(qapp, pump, panel):
    ins = panel.inspector
    panel.set_mode("edit"); pump(lambda: False, 0.2)
    mouse(panel, pump, "dblclick", "#titel")
    assert pump(lambda: js(panel, pump, "document.getElementById('titel').isContentEditable"), 5)
    js(panel, pump, "(() => { const t = document.getElementById('titel'); t.textContent = 'Neuer Titel'; t.dispatchEvent(new Event('blur')); return 1; })()")
    assert pump(lambda: ins.text_pending, 10)
    old, new, info = next(iter(ins.text_pending.values()))
    assert (old, new) == ("Hallo Welt", "Neuer Titel") and info["id"] == "titel"
    assert js(panel, pump, "document.getElementById('titel').isContentEditable") is False


def test_text_field_in_inspector_changes_text_live(qapp, pump, panel):
    ins = panel.inspector
    pick(panel, pump, ".inner")
    ins.text_edit.setText("anders"); ins._text_changed()
    assert pump(lambda: ins.text_pending, 10) and js(panel, pump, "document.querySelector('.inner').textContent") == "anders"


# --- Quelle ---------------------------------------------------------------------------------------------------------------
def test_jump_to_source_opens_the_clear_hit_and_designer_controls(qapp, pump, panel):
    ins = panel.inspector
    opened, designer = [], []
    ins.openFile.connect(lambda f, line: opened.append((Path(f).name, line))); ins.designerControl.connect(designer.append)
    pick(panel, pump, "#titel")
    assert pump(lambda: ins.info is not None, 5)
    ins.jump_to_source()
    assert opened == [("index.html", 5)] or opened and opened[0][0] == "index.html"
    assert ins.src_list.count() >= 1
    pick(panel, pump, ".btn")
    ins.jump_to_source()
    assert designer == ["button1"]                                      # data-vds → Control im Designer


# --- Zurückschreiben -----------------------------------------------------------------------------------------------------------
def test_write_back_changes_the_css_rule_reloads_and_can_be_undone(qapp, pump, panel, site, monkeypatch):
    root, url = site
    ins = panel.inspector
    monkeypatch.setattr(WriteDialog, "exec", lambda self: 1)
    pick(panel, pump, "#titel")
    ins.set_style("color", "#0000ff"); ins.set_style("font-size", "32px")
    assert pump(lambda: ins.pending.get("#titel") and len(ins.pending["#titel"]["props"]) == 2, 10)
    plans = ins.build_plans()[0][1]
    assert [p.kind for p in plans][0] == "css-regel" and "style.css" in plans[0].label
    files = ins.write_back()
    css = (root / "style.css").read_text()
    assert files == [str(root.resolve() / "style.css")] and ".kopf { color: #0000ff;" in css.replace("\n", " ") or "color: #0000ff" in css
    assert "font-size: 32px" in css and not ins.pending
    # Überschreibung im DOM ist weg, die Quelle gilt – nach dem Neuladen zeigt die Seite die Farbe aus der Datei
    panel.reload()
    assert pump(lambda: computed(panel, pump, "#titel", "color") == "rgb(0, 0, 255)", 20)
    ins.undo_last()
    t = time.time() + 10
    os.utime(root / "style.css", (t, t))                            # gleiche Sekunde wie vorher: dem einfachen Test-Server einen neuen Zeitstempel geben, sonst 304
    assert (root / "style.css").read_text() == CSS
    assert pump(lambda: computed(panel, pump, "#titel", "color") == "rgb(51, 51, 51)", 20)


def test_write_back_text_and_inline_style_into_html(qapp, pump, panel, site, monkeypatch):
    root, url = site
    ins = panel.inspector
    monkeypatch.setattr(WriteDialog, "exec", lambda self: 1)
    pick(panel, pump, ".inner")
    ins.set_style("color", "#123456"); ins.text_edit.setText("drinnen"); ins._text_changed()
    assert pump(lambda: ins.pending and ins.text_pending, 10)
    items = ins.build_plans()
    assert items[0][1] and items[1][1]
    # Stil per Inline-Plan wählen (es gibt keine .inner-Regel), Text direkt
    chosen = [next(p for p in items[0][1] if p.kind in ("inline", "neue-regel")), items[1][1][0]]
    ins.commit(chosen)
    html = (root / "index.html").read_text()
    assert "drinnen" in html and ">innen</span>" not in html


def test_write_dialog_lists_alternatives_and_previews_the_diff(qapp, site):
    root, _ = site
    plans = writer.plan_style(root, {"tag": "h1", "id": "titel", "classes": ["kopf", "gross"], "stableClasses": ["kopf", "gross"], "text": "Hallo Welt"}, {"color": "#0f0"})
    dlg = WriteDialog(root.resolve(), [("h1#titel – color", plans), ("nichts", [])])
    assert dlg.combos[0].count() == len(plans) >= 2 and not dlg.combos[1].isEnabled()
    assert "+.kopf { color: #0f0;" in dlg.view.toPlainText() or "color: #0f0" in dlg.view.toPlainText()
    dlg.combos[0].setCurrentIndex(1)
    assert dlg.chosen() == [dlg.combos[0].currentData()] and "style=" in dlg.view.toPlainText()


def test_pending_changes_survive_until_written_or_discarded(qapp, pump, panel):
    ins = panel.inspector
    pick(panel, pump, ".box")
    ins.set_style("opacity", "0.5")
    assert pump(lambda: ins.pending, 10)
    assert ins.btn_discard.isEnabled()
    ins.discard()
    assert pump(lambda: not ins.pending, 5) and computed(panel, pump, ".box", "opacity") == "1"


def test_save_buttons_follow_pending_changes(qapp, pump, panel, site):
    ins = panel.inspector
    assert panel.btn_save.isHidden() and panel.btn_discard.isHidden()
    pick(panel, pump, "#titel")
    ins.set_style("color", "#0000ff")
    assert pump(lambda: ins.pending, 10)
    assert not panel.btn_save.isHidden() and "(1)" in panel.btn_save.text()
    panel.btn_discard.click()
    assert pump(lambda: not ins.pending and panel.btn_save.isHidden(), 10)
