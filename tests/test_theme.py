"""Farbschemata: Neon (Standard) und Hell – Palette, Farbumsetzung, Stylesheet, Oberfläche, Umschalten in den Optionen."""
import os
import subprocess
import sys
import textwrap

from vds import options, theme


def run_light(code: str) -> str:
    """Code in einem eigenen Prozess mit hellem Schema ausführen (das Schema wird beim Import festgelegt)."""
    env = {**os.environ, "VDS_THEME": "hell", "QT_QPA_PLATFORM": "offscreen", "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu"}
    r = subprocess.run([sys.executable, "-c", "import PySide6.QtWebEngineWidgets\n" + textwrap.dedent(code)], capture_output=True, text=True, env=env, timeout=120,
                       cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip()


def test_both_palettes_have_the_same_keys_and_neon_is_default():
    assert set(theme.NEON) == set(theme.HELL) and set(theme.TOKENS_NEON) == set(theme.TOKENS_HELL)
    assert theme.current == "neon" and theme.C["editor"] == "#080a16" and not theme.is_light()
    assert theme.t("#0c0f22") == "#0c0f22" and theme.adapt("#3dffa1") == "#3dffa1"      # im Neon-Schema bleibt alles unverändert


def test_stylesheet_in_neon_keeps_the_dark_look_and_has_no_unresolved_placeholders():
    css = theme.stylesheet()
    assert "{c[" not in css and "{{" not in css and "rgba(10,13,31,0.85)" in css


def test_light_theme_contrast_and_color_mapping():
    out = run_light("""
        from PySide6.QtGui import QColor
        from vds import theme
        L = lambda h: QColor(h).lightnessF()
        print(theme.current, theme.is_light())
        print(L(theme.C["editor"]) > 0.9, L(theme.C["fg"]) < 0.25, L(theme.C["panel"]) > 0.9)
        def lum(h):
            c = QColor(h); f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
            return 0.2126 * f(c.redF()) + 0.7152 * f(c.greenF()) + 0.0722 * f(c.blueF())
        contrast = lambda h: 1.05 / (lum(h) + 0.05)                               # gegen Weiß
        print(all(contrast(v) >= 4.5 for k, v in theme.TOKENS.items() if k != "comment"), contrast(theme.TOKENS["comment"]) >= 3.5)   # Syntaxfarben auf Weiß gut lesbar (WCAG), Kommentare bewusst blasser
        print(theme.t("#0c0f22") == theme.C["panel"], theme.t("#dbe6ff") == theme.C["fg"])
        print(L(theme.adapt("#3dffa1")) <= 0.37, L(theme.adapt("#ffc474")) <= 0.37, theme.adapt("#ff4d6d") != "#ff4d6d")
        css = theme.stylesheet()
        print("rgba(10,13,31" not in css, "#0d0b22" not in css, "{c[" not in css, theme.C["bar"] in css)
        print(theme.t("<span style='color:#3dffa1'>+3</span> background:#0c0f22").count("#3dffa1"))
    """).splitlines()
    assert out[0] == "hell True"
    assert out[1] == "True True True" and out[2] == "True True" and out[3] == "True True"
    assert out[4] == "True True True" and out[5] == "True True True True" and out[6] == "0"


def test_light_main_window_builds_with_readable_text_everywhere():
    out = run_light("""
        import tempfile
        from PySide6.QtCore import QCoreApplication, QSettings, Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QApplication
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        QSettings.setPath(QSettings.NativeFormat, QSettings.UserScope, tempfile.mkdtemp())
        app = QApplication([])
        from vds.theme import apply_palette, stylesheet
        app.setStyle("Fusion"); apply_palette(app); app.setStyleSheet(stylesheet())
        from vds.app import MainWindow
        w = MainWindow(); w.show(); app.processEvents()
        img = w.grab().toImage()
        L = lambda x, y: QColor(img.pixel(x, y)).lightnessF()
        print(L(400, 300) > 0.85)                                   # Editorfläche hell
        print(L(10, 14) > 0.85 and L(300, 40) > 0.85)               # Menü- und Werkzeugleiste hell
        ed = w.docs.open(__import__("pathlib").Path("workspace/hello.py")) if False else None
        from vds.editor.code_editor import CodeEditor
        e = CodeEditor("x.py"); e.setPlainText("def f():\\n    return 'x'\\n"); e.resize(300, 100); e.show(); app.processEvents()
        print(QColor(e.grab().toImage().pixel(250, 90)).lightnessF() > 0.9)
        w.preview.shutdown(); w.close()
        from vds.web.panel import dispose_profiles; dispose_profiles()
    """).splitlines()
    assert out == ["True", "True", "True"]


def test_options_dialog_offers_theme_and_hints_a_restart(qapp):
    from vds.ui.options_dialog import OptionsDialog
    dlg = OptionsDialog(None)
    assert dlg.fields["ui/theme"][1]() == "neon" and dlg.restart_btn.isHidden() and dlg.theme_note.text() == ""
    dlg.fields["ui/theme"][2]("hell")
    assert not dlg.restart_btn.isHidden() and "Neustart" in dlg.theme_note.text()
    dlg.fields["ui/theme"][2]("neon")
    assert dlg.restart_btn.isHidden()
    options.set("ui/theme", "unsinn"); assert options.get("ui/theme") == "neon"
    options.reset()


def test_stored_theme_is_read_from_settings_unless_overridden(qapp, monkeypatch):
    monkeypatch.delenv("VDS_THEME", raising=False)
    options.reset(); options._store().setValue("ui/theme", "hell")
    assert theme.stored_theme() == "hell"
    monkeypatch.setenv("VDS_THEME", "neon"); assert theme.stored_theme() == "neon"
    monkeypatch.setenv("VDS_THEME", "quatsch"); assert theme.stored_theme() == "neon"
    options.reset()
