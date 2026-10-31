"""Web: Quellcode-Suche, Zurückschreiben von Stilen und Text (CSS-Regel, Inline, Tailwind), Dev-Server-Adresse."""
import json
from pathlib import Path

import pytest

from vds.web import devserver, source_map, writer


def info(tag="div", id="", classes=(), text="", **kw):
    return {"tag": tag, "id": id, "classes": list(classes), "stableClasses": list(kw.pop("stable", classes)), "text": text, **kw}


def put(root: Path, rel: str, content: str) -> Path:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    return f


# --- Dev-Server-Adresse ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expect", [
    ("  VITE v6.4.5  ready in 300 ms\n\n  ➜  Local:   http://localhost:5173/\n  ➜  Network: use --host to expose", "http://localhost:5173/"),
    ("  ➜  Local:   http://localhost:5173/\n  ➜  Network: http://192.168.0.5:5173/", "http://localhost:5173/"),
    ("[Sat Oct 24 10:00:00 2026] PHP 8.5.12 Development Server (http://127.0.0.1:8000) started", "http://127.0.0.1:8000"),
    ("   INFO  Server running on [http://127.0.0.1:8000].", "http://127.0.0.1:8000"),
    ("\x1b[32m- Local:\x1b[0m        http://localhost:3000", "http://localhost:3000"),
    ("Local: http://0.0.0.0:4200/", "http://localhost:4200/"),
    ("- Network:      http://192.168.1.2:3000\n", None),
    ("kein Server hier, siehe https://example.com/docs", None),
])
def test_dev_server_url_detection(text, expect):
    assert devserver.find_url(text) == expect


# --- Quellsuche ---------------------------------------------------------------------------------------------------
def test_search_ranks_id_over_class_over_text(tmp_path):
    put(tmp_path, "index.html", '<h1 id="titel" class="kopf gross">Hallo Welt</h1>\n<p class="kopf">Hallo Welt</p>\n')
    put(tmp_path, "src/App.tsx", 'export const A = () => <button className={`btn primary ${x}`}>Speichern</button>;\n')
    put(tmp_path, "src/Card.vue", '<template>\n  <div :class="[\'card\', \'wide\']" class="card">Inhalt</div>\n</template>\n')
    c = source_map.search(tmp_path, info("h1", "titel", ["kopf", "gross"], "Hallo Welt"))
    assert c[0].file.name == "index.html" and c[0].line == 1 and c[0].kind == "id" and c[0].score == 100
    assert any(x.kind == "text" and x.line == 2 for x in c)
    b = source_map.search(tmp_path, info("button", classes=["btn", "primary"], text="Speichern"))
    assert b[0].file.name == "App.tsx" and b[0].kind == "klasse" and "className" in b[0].snippet
    v = source_map.search(tmp_path, info("div", classes=["card"], text="Inhalt"))
    assert v[0].file.name == "Card.vue" and v[0].line == 2


def test_search_ignores_dependency_and_build_dirs_and_generated_classes(tmp_path):
    put(tmp_path, "node_modules/lib/x.html", '<p id="a">x</p>')
    put(tmp_path, "dist/index.html", '<p id="a">x</p>')
    put(tmp_path, "src/a.html", '<p id="a">x</p>')
    assert [c.file.name for c in source_map.search(tmp_path, info("p", "a"))] == ["a.html"]
    assert source_map.search(tmp_path, info("p", classes=["css-1x2y3z"], stable=[], text="")) == []


# --- Tag-Suche -------------------------------------------------------------------------------------------------------
def test_find_tag_handles_jsx_expressions_quotes_and_php():
    jsx = '<Foo a={() => x > 1} className="a" onClick={() => go("</b>")}>text</Foo>'
    t = writer.find_tag(jsx, jsx.index("className"))
    assert jsx[t[0]:t[1]].endswith('go("</b>")}>') and jsx[t[0]:].startswith("<Foo")
    php = '<div class="box <?= $x->y ?>" id="b">Hallo</div>'
    t = writer.find_tag(php, php.index("id="))
    assert php[t[0]:t[1]] == '<div class="box <?= $x->y ?>" id="b">'
    assert writer.find_tag("text ohne tag", 3) is None


# --- CSS-Regeln --------------------------------------------------------------------------------------------------------
def test_existing_rule_is_edited_keeping_important_and_style(tmp_path):
    css = put(tmp_path, "style.css", ".btn {\n    padding: 4px;\n    color: red !important;\n}\n.kopf { color: #333; }\n@media (max-width: 600px) {\n  .kopf { color: green; }\n}\n")
    put(tmp_path, "index.html", '<button class="btn">x</button><h1 class="kopf">y</h1>')
    plans = writer.plan_style(tmp_path, info("button", classes=["btn"], text="x"), {"color": "#00f", "border-radius": "8px"})
    p = next(p for p in plans if p.kind == "css-regel")
    assert "color: #00f !important;" in p.new and "    border-radius: 8px;" in p.new and "padding: 4px;" in p.new
    q = next(p for p in writer.plan_style(tmp_path, info("h1", classes=["kopf"], text="y"), {"color": "#fff", "font-size": "20px"}) if p.kind == "css-regel")
    assert ".kopf { color: #fff; font-size: 20px; }" in q.new                                       # einzeilige Regel bleibt einzeilig
    assert "@media (max-width: 600px) {\n  .kopf { color: green; }" in q.new                          # Regel im Media-Query bleibt unberührt
    assert css.read_text() == p.old


def test_most_specific_rule_wins_and_complex_selectors_are_skipped(tmp_path):
    put(tmp_path, "s.css", ".a { color: red; }\n.a.b { color: blue; }\n.wrap .a { color: green; }\n.a:hover { color: pink; }\n#x { margin: 0; }\n")
    plans = writer.css_plans(tmp_path, info("div", classes=["a", "b"]), {"color": "#111"})
    assert len(plans) == 1 and ".a.b { color: #111; }" in plans[0].new and "color: green" in plans[0].new
    ident = writer.css_plans(tmp_path, info("div", "x", ["a"]), {"margin": "4px"})
    assert "#x { margin: 4px; }" in ident[0].new


def test_style_block_in_vue_and_new_rule_fallback(tmp_path):
    vue = put(tmp_path, "src/Card.vue", "<template>\n  <div class=\"card\">x</div>\n</template>\n<style scoped>\n.card {\n  color: red;\n}\n</style>\n")
    p = writer.css_plans(tmp_path, info("div", classes=["card"]), {"color": "#0f0"})[0]
    assert "<style scoped>\n.card {\n  color: #0f0;\n}\n</style>" in p.new and p.file == vue
    other = tmp_path / "o"; other.mkdir()
    put(other, "src/index.css", "body { margin: 0; }\n")
    put(other, "src/A.tsx", 'export const A = () => <div className="neu">x</div>;')
    plans = writer.plan_style(other, info("div", classes=["neu"], text="x"), {"color": "#123456"})
    nr = next(p for p in plans if p.kind == "neue-regel")
    assert nr.file.name == "index.css" and nr.new.endswith(".neu {\n  color: #123456;\n}\n")


# --- Inline-Style ------------------------------------------------------------------------------------------------------------
def test_inline_style_in_html_jsx_vue_and_php(tmp_path):
    put(tmp_path, "a.html", '<p class="x" id="p1">Text</p>\n<img src="a.png" class="pic" />\n<b class="w" style="color: blue; margin: 0">fett</b>\n')
    p = next(p for p in writer.plan_style(tmp_path, info("p", "p1", ["x"], "Text"), {"color": "#f00"}) if p.kind == "inline")
    assert '<p class="x" id="p1" style="color: #f00">Text</p>' in p.new
    i = next(p for p in writer.plan_style(tmp_path, info("img", classes=["pic"]), {"width": "50px"}) if p.kind == "inline")
    assert '<img src="a.png" class="pic" style="width: 50px" />' in i.new
    m = next(p for p in writer.plan_style(tmp_path, info("b", classes=["w"], text="fett"), {"color": "#0f0", "padding": "2px"}) if p.kind == "inline")
    assert 'style="color: #0f0; margin: 0; padding: 2px"' in m.new
    put(tmp_path, "App.tsx", 'export default () => (\n  <div className="box" style={{ color: "red", zIndex: 2 }} onClick={() => f()}>Hi</div>\n);\n')
    j = next(p for p in writer.plan_style(tmp_path, info("div", classes=["box"], text="Hi"), {"background-color": "#eee", "z-index": "5", "color": "blue"}) if p.kind == "inline")
    assert 'style={{ color: "blue", zIndex: 5, backgroundColor: "#eee" }}' in j.new and 'onClick={() => f()}' in j.new
    put(tmp_path, "B.tsx", 'const B = () => <div className="v" style={styles.v}>x</div>;')
    assert not [p for p in writer.plan_style(tmp_path, info("div", classes=["v"], text="x"), {"color": "#fff"}) if p.kind == "inline" and p.file.name == "B.tsx"]   # style={variable} bleibt unangetastet
    put(tmp_path, "c.php", '<div class="card <?= $kind ?>" id="k"><?= $title ?></div>')
    k = next(p for p in writer.plan_style(tmp_path, info("div", "k", ["card"]), {"opacity": "0.5"}) if p.kind == "inline")
    assert k.new == '<div class="card <?= $kind ?>" id="k" style="opacity: 0.5"><?= $title ?></div>'


# --- Tailwind -----------------------------------------------------------------------------------------------------------------------
def test_tailwind_classes_are_replaced_not_duplicated(tmp_path):
    put(tmp_path, "package.json", json.dumps({"devDependencies": {"tailwindcss": "^4"}}))
    put(tmp_path, "src/App.tsx", 'export default () => <button className="px-4 text-red-500 bg-blue-500 rounded text-sm w-24">Los</button>;\n')
    plans = writer.plan_style(tmp_path, info("button", classes=["px-4", "text-red-500", "bg-blue-500", "rounded", "text-sm", "w-24"], text="Los"),
                              {"color": "rgb(255, 0, 128)", "background-color": "#00ff00", "border-radius": "12px", "font-size": "18px", "width": "200px"})
    tw = plans[0]
    assert tw.kind == "tailwind"
    new = tw.new
    for old in ("text-red-500", "bg-blue-500", "text-sm", "w-24"):
        assert old not in new
    for tok in ("text-[#ff0080]", "bg-[#00ff00]", "rounded-[12px]", "text-[18px]", "w-[200px]", "px-4"):
        assert tok in new
    assert new.count("rounded") == 1
    # nicht ausdrückbare Eigenschaft (display) → kein Tailwind-Plan, Inline bleibt
    kinds = [p.kind for p in writer.plan_style(tmp_path, info("button", classes=["px-4", "text-red-500", "bg-blue-500", "rounded", "text-sm", "w-24"], text="Los"), {"display": "none"})]
    assert "tailwind" not in kinds and "inline" in kinds


def test_no_tailwind_plan_without_tailwind(tmp_path):
    put(tmp_path, "a.html", '<p class="text-red-500">x</p>')
    assert "tailwind" not in [p.kind for p in writer.plan_style(tmp_path, info("p", classes=["text-red-500"], text="x"), {"color": "#fff"})]


# --- Text, Zusammenführen, Rückgängig ------------------------------------------------------------------------------------------------
def test_text_plans_need_a_unique_place(tmp_path):
    put(tmp_path, "a.html", "<h1>Willkommen</h1>\n<p>Zweimal</p><p>Zweimal</p>\n")
    one = writer.text_plans(tmp_path, "Willkommen", "Hallo", [])
    assert len(one) == 1 and "<h1>Hallo</h1>" in one[0].new
    assert writer.text_plans(tmp_path, "Zweimal", "Einmal", []) == []                       # mehrdeutig → nichts raten
    assert writer.text_plans(tmp_path, "Willkommen", "Willkommen", []) == []


def test_merge_combines_style_and_text_in_one_file_and_skips_overlaps(tmp_path):
    f = put(tmp_path, "a.html", '<h1 class="t">Willkommen</h1>\n')
    style = next(p for p in writer.plan_style(tmp_path, info("h1", classes=["t"], text="Willkommen"), {"color": "#f00"}) if p.kind == "inline")
    text = writer.text_plans(tmp_path, "Willkommen", "Hallo", [])[0]
    merged, skipped = writer.merge([style, text])
    assert not skipped and len(merged) == 1 and merged[0].new == '<h1 class="t" style="color: #f00">Hallo</h1>\n'
    dup, skipped = writer.merge([style, style])
    assert len(skipped) == 1 and len(dup) == 1 and f.read_text() == style.old


def test_apply_and_undo_restore_files_exactly(tmp_path):
    f = put(tmp_path, "s.css", ".a { color: red; }\n")
    g = put(tmp_path, "i.html", '<p class="a">x</p>\n')
    before = (f.read_text(), g.read_text())
    plans = writer.plan_style(tmp_path, info("p", classes=["a"], text="x"), {"color": "#0f0"})
    backup = writer.apply([next(p for p in plans if p.kind == "css-regel")])
    assert "#0f0" in f.read_text() and g.read_text() == before[1]
    writer.undo(backup)
    assert (f.read_text(), g.read_text()) == before


def test_diff_is_readable(tmp_path):
    put(tmp_path, "s.css", ".a { color: red; }\n")
    p = writer.css_plans(tmp_path, info("p", classes=["a"]), {"color": "#0f0"})[0]
    d = p.diff(tmp_path.resolve())
    assert "--- a/s.css" in d and "-.a { color: red; }" in d and "+.a { color: #0f0; }" in d


# --- PHP-Anwendungsserver (RoadRunner, FrankenPHP, Swoole, Octane) --------------------------------------------------------
# Hinweis: Die Beispielausgaben entsprechen den üblichen Logformaten, stammen aber nicht aus echten Läufen (die Programme sind nicht installiert).
@pytest.mark.parametrize("text,expect", [
    ('{"level":"info","msg":"http server was started","address":"[::]:8080"}', "http://localhost:8080"),
    ('INFO\thttp\thttp server was started\t{"address": "0.0.0.0:9000"}', "http://localhost:9000"),
    ("Caddy serving on :8080", "http://localhost:8080"),
    ('{"level":"info","msg":"serving initial configuration"}\nFrankenPHP started, listening on localhost:8443', "http://localhost:8443"),
    ("Swoole http server is started at 0.0.0.0:9501", "http://localhost:9501"),
    ("   INFO  Server running on [http://127.0.0.1:8000].\n   Local: http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ('{"msg":"rpc listening","address":"127.0.0.1:6001"}', None),
    ("Network: listening on 192.168.1.5:3000", None),
])
def test_app_server_ports_are_found_without_scheme(text, expect):
    assert devserver.find_url(text) == expect


def test_detect_command_for_octane_roadrunner_and_frankenphp(tmp_path):
    (tmp_path / "artisan").write_text("x"); (tmp_path / "composer.json").write_text(json.dumps({"require": {"laravel/octane": "^2.0"}}))
    assert devserver.detect_command(tmp_path) == "php artisan octane:start"
    other = tmp_path / "rr"; other.mkdir()
    (other / ".rr.yaml").write_text("version: '3'"); assert devserver.detect_command(other) == "rr serve"
    (other / "rr").write_text("#!/bin/sh"); assert devserver.detect_command(other) == "./rr serve"
    fp = tmp_path / "fp"; fp.mkdir(); (fp / "Caddyfile").write_text("{ frankenphp }")
    assert devserver.detect_command(fp) == "frankenphp run"


def test_new_rule_goes_into_the_stylesheet_the_page_loads(tmp_path):
    """Laravel: Seite lädt /css/app.css → public/css/app.css, nicht irgendeine andere CSS-Datei."""
    (tmp_path / "public" / "css").mkdir(parents=True); (tmp_path / "resources" / "css").mkdir(parents=True)
    (tmp_path / "public" / "css" / "app.css").write_text(".a { color: red; }\n")
    (tmp_path / "resources" / "css" / "app.css").write_text(".b { color: red; }\n")
    info = {"tag": "a", "id": "", "classes": ["neu"], "stableClasses": ["neu"], "sheets": ["/css/app.css", "/x/fehlt.css", "/../../etc/passwd"]}
    plan = writer.new_rule_plan(tmp_path, info, {"color": "#fff"})
    assert plan.file == (tmp_path / "public" / "css" / "app.css").resolve() and ".neu {" in plan.new
    assert writer.sheet_files(tmp_path, info["sheets"]) == [(tmp_path / "public" / "css" / "app.css").resolve()]


def test_existing_rule_in_loaded_sheet_is_offered_first(tmp_path):
    (tmp_path / "public").mkdir(); (tmp_path / "resources").mkdir()
    (tmp_path / "public" / "app.css").write_text(".x { color: red; }\n")
    (tmp_path / "resources" / "app.css").write_text(".x { color: blue; }\n")
    info = {"tag": "p", "id": "", "classes": ["x"], "stableClasses": ["x"], "sheets": ["/app.css"]}
    plans = writer.css_plans(tmp_path.resolve(), info, {"color": "#000"})
    assert [p.file.parent.name for p in plans] == ["public", "resources"]


def test_shared_class_rule_is_last_choice_and_new_rule_is_unique(tmp_path):
    """.btn-lg gilt für zwei Buttons: Verschieben darf nicht dort landen (Überschneidung, falsches Element)."""
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "app.css").write_text(".btn-lg { padding: 1rem; }\n")
    (tmp_path / "home.html").write_text('<a class="btn btn-primary btn-lg" href="/a">A</a>\n<a class="btn btn-ghost btn-lg" href="/b">B</a>\n')
    info = {"tag": "a", "id": "", "classes": ["btn", "btn-primary", "btn-lg"], "stableClasses": ["btn", "btn-primary", "btn-lg"],
            "classCounts": {"btn": 2, "btn-primary": 1, "btn-lg": 2}, "text": "A", "sheets": ["/app.css"]}
    plans = writer.plan_style(tmp_path, info, {"left": "5px", "top": "7px"})
    kinds = [p.kind for p in plans]
    assert kinds[0] == "inline" and plans[-1].kind == "css-regel" and plans[-1].shared == 2 and "gilt für 2 Elemente" in plans[-1].label
    assert ".btn-primary {" in writer.new_rule_plan(tmp_path, info, {"left": "5px"}).new
    both = {**info, "classCounts": {"btn": 2, "btn-primary": 2, "btn-lg": 2}}
    assert ".btn.btn-primary.btn-lg {" in writer.new_rule_plan(tmp_path, both, {"left": "5px"}).new


def test_text_from_laravel_setting_is_written_to_the_database_and_undone(tmp_path, monkeypatch):
    """`{{ Setting::get('hero') }}` steht nicht im Quelltext: die IDE ändert den Wert dort, wo er herkommt (PHP hier nachgestellt)."""
    (tmp_path / "app" / "Models").mkdir(parents=True)
    (tmp_path / "artisan").write_text("")
    (tmp_path / "app" / "Models" / "Setting.php").write_text("<?php class Setting { static function get($k){} static function put($k,$v){} }")
    db = {"hero": "Alt", "x": "Anderes"}
    calls = []

    def fake_php(root, code, timeout=30):
        calls.append(code)
        if "definitions" in code:
            return json.dumps(db)
        if "->first()" in code:
            return json.dumps(db.get("hero"))
        if "Setting::put" in code:
            import base64, re
            k, v = json.loads(base64.b64decode(re.search(r"base64_decode\('([^']+)'", code).group(1)))
            db.pop(k) if v is None else db.__setitem__(k, v)
            return "ok"
    monkeypatch.setattr(writer, "_php", fake_php)
    plans = writer.setting_plans(tmp_path, " Alt ", "Neu")
    assert [p.run[2] for p in plans] == ["hero"] and "+ Neu" in plans[0].diff()
    assert writer.setting_plans(tmp_path, "unbekannt", "Neu") == [] and writer.setting_plans(tmp_path, "Alt", "Alt") == []
    out, skipped = writer.merge(plans)
    backup = writer.apply(out)
    assert db["hero"] == "Neu" and list(backup.values()) == ["Alt"]
    writer.undo(backup)
    assert db["hero"] == "Alt"


def test_no_setting_plan_without_laravel_model(tmp_path):
    assert writer.setting_plans(tmp_path, "a", "b") == []
