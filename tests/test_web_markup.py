"""Elementstruktur aus Quelltext (Blade/HTML/JSX), Zuordnung Seite → Quelle und die Strukturänderungen."""
from pathlib import Path

from vds.web import blocks, markup

BLADE = """@extends('layouts.site')

@section('content')
    <section class="hero">
        <div class="container">
            <h1>{{ \\App\\Models\\Setting::get('hero_title') }}</h1>
            @if($a > 1)
                <p class="lead" data-x="{{ route("a") }}">Text {{ $x }}</p>
            @endif
            <div class="hero-actions">
                <a class="btn btn-primary btn-lg" href="{{ route('contact') }}">{{ $cta }}</a>
                <a class="btn btn-ghost btn-lg" href="{{ route('services') }}">Unsere Leistungen</a>
            </div>
            <ul><li>eins<li>zwei</ul>
            <?php echo "<b>nicht</b>"; ?>
            {{-- <div>Kommentar</div> --}}
            <img src="a.png">
        </div>
    </section>
@endsection
"""


def tags(text):
    return [(n.tag, n.line) for n in markup.walk(markup.parse(text))]


def test_parser_handles_blade_php_comments_void_and_implied_end_tags():
    t = tags(BLADE)
    assert [x for x, _ in t] == ["section", "div", "h1", "p", "div", "a", "a", "ul", "li", "li", "img"]    # nichts aus PHP, Kommentar oder {{ }}
    tree = markup.parse(BLADE)
    a = next(n for n in markup.walk(tree) if n.tag == "a")
    assert a.attr["class"] == "btn btn-primary btn-lg" and a.attr["href"] == "{{ route('contact') }}" and a.complete
    p = next(n for n in markup.walk(tree) if n.tag == "p")
    assert p.attr["data-x"] == '{{ route("a") }}'                               # Anführungszeichen innerhalb von {{ }}
    assert [n.complete for n in markup.walk(tree) if n.tag == "li"] == [False, False]   # <li> ohne Ende: erkannt, aber nicht bearbeitbar


def test_static_classes_and_own_text_ignore_dynamic_parts():
    assert markup.static_classes("btn {{ $x }} active @if($a) on @endif") == (["btn", "active"], True)
    assert markup.static_classes("a b") == (["a", "b"], False)
    tree = markup.parse(BLADE)
    p = next(n for n in markup.walk(tree) if n.tag == "p")
    assert markup.own_text(BLADE, p) == ("Text", True)


def project(tmp_path, text=BLADE, name="resources/views/home.blade.php"):
    f = tmp_path / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return tmp_path.resolve(), f


def info(tag, classes=(), text="", chain=(), **kw):
    return {"tag": tag, "id": "", "classes": list(classes), "stableClasses": list(classes), "text": text, "attrs": kw.get("attrs", {}),
            "chain": [{"tag": t, "id": "", "classes": list(c)} for t, c in chain]}


def test_locate_tells_the_two_buttons_apart_and_prefers_text_and_chain(tmp_path):
    root, f = project(tmp_path)
    (tmp_path / "resources/views/admin.blade.php").write_text('<a class="btn btn-primary" href="/x">Neu</a>')
    ch = [("div", ["hero-actions"]), ("div", ["container"]), ("section", ["hero"])]
    prim = markup.locate(root, info("a", ["btn", "btn-primary", "btn-lg"], "Kontakt", ch))
    ghost = markup.locate(root, info("a", ["btn", "btn-ghost", "btn-lg"], "Unsere Leistungen", ch, attrs={"href": "/services"}))
    assert prim[0].file == f and prim[0].line == 11 and ghost[0].line == 12
    assert all(m.file == f for m in ghost)                                      # die Klasse btn-ghost gibt es nur hier
    h1 = markup.locate(root, info("h1", [], "Irgendein Titel", ch[1:]))
    assert h1[0].line == 6 and h1[0].score >= 15


def test_locate_rejects_nodes_with_classes_the_element_does_not_have(tmp_path):
    root, _ = project(tmp_path, '<p class="a b">x</p>')
    assert markup.locate(root, info("p", ["a"], "x")) == []                    # im Quelltext steht „b“, das Element hat es nicht
    assert markup.locate(root, info("p", ["a", "b", "c"], "x"))


def lines(plan):
    return plan.new.splitlines()


def test_insert_after_before_inside_keep_indentation(tmp_path):
    root, f = project(tmp_path)
    m = markup.locate(root, info("a", ["btn", "btn-ghost", "btn-lg"], "Unsere Leistungen"))[0]
    after = markup.insert_plan(m, root, "<h3>Neu</h3>\n<p>x</p>", "after")
    assert lines(after)[12:14] == ["                <h3>Neu</h3>", "                <p>x</p>"] and "</div>" in lines(after)[14]
    before = markup.insert_plan(m, root, "<hr />", "before")
    assert lines(before)[11] == "                <hr />" and "btn-ghost" in lines(before)[12]
    box = markup.locate(root, info("div", ["hero-actions"], ""))[0]
    inside = markup.insert_plan(box, root, "<a>X</a>", "inside")
    assert lines(inside)[12] == "                <a>X</a>" and lines(inside)[13].strip() == "</div>"
    img = markup.locate(root, info("img", [], "", [("div", ["container"])], attrs={"src": "a.png"}))[0]
    assert markup.insert_plan(img, root, "<p>x</p>", "inside") is None         # in <img> geht nichts hinein


def test_inline_element_is_edited_inline(tmp_path):
    root, _ = project(tmp_path, "<p>Ein <b>fetter</b> Text</p>")
    m = markup.locate(root, info("b", [], "fetter"))[0]
    assert markup.insert_plan(m, root, "<i>x</i>", "after").new == "<p>Ein <b>fetter</b><i>x</i> Text</p>"
    assert markup.delete_plan(m, root).new == "<p>Ein  Text</p>"


def test_delete_duplicate_move(tmp_path):
    root, f = project(tmp_path)
    m = markup.locate(root, info("a", ["btn", "btn-ghost", "btn-lg"], "Unsere Leistungen"))[0]
    assert "Unsere Leistungen" not in markup.delete_plan(m, root).new and markup.delete_plan(m, root).new.count("\n") == BLADE.count("\n") - 1
    assert markup.duplicate_plan(m, root).new.count("Unsere Leistungen") == 2
    up = markup.move_plan(m, root, "up").new.splitlines()
    assert "btn-ghost" in up[10] and "btn-primary" in up[11]
    assert markup.move_plan(m, root, "down") is None                           # letztes Geschwister
    first = markup.locate(root, info("a", ["btn", "btn-primary", "btn-lg"], ""))[0]
    assert markup.move_plan(first, root, "up") is None


def test_incomplete_nodes_are_not_changed(tmp_path):
    root, _ = project(tmp_path, "<ul>\n  <li>eins\n  <li>zwei</li>\n</ul>")
    text, tree = markup.parsed(root / "resources/views/home.blade.php")
    m = markup.Match(root / "resources/views/home.blade.php", next(n for n in markup.walk(tree) if n.tag == "li"), 50, text)
    assert markup.delete_plan(m, root) is None and markup.duplicate_plan(m, root) is None


def test_jsx_gets_classname_and_blocks_adapt_to_project(tmp_path):
    root, f = project(tmp_path, "export default () => (\n  <div id=\"a\">\n    <p>x</p>\n  </div>\n)\n", "src/App.jsx")
    m = markup.locate(root, {"tag": "p", "id": "", "classes": [], "stableClasses": [], "text": "x", "attrs": {}, "chain": []})[0]
    assert 'className="card"' in markup.insert_plan(m, root, '<div class="card">y</div>', "after").new
    # Bausteine: Projektklassen, sonst Inline-Stile, Tailwind
    plain = blocks.snippet(root, "button")
    assert "style=" in plain and "btn-primary" not in plain
    (root / "style.css").write_text(".btn { x: 1 } .btn-primary { y: 2 } .card {} .container {} .section {}")
    assert 'class="btn btn-primary"' in blocks.snippet(root, "button") and 'class="card"' in blocks.snippet(root, "card")
    (root / "package.json").write_text('{"dependencies": {"tailwindcss": "3"}}')
    assert "bg-indigo-600" in blocks.snippet(root, "button")
    assert all(blocks.snippet(root, b) for b, _, _ in blocks.BLOCKS)
