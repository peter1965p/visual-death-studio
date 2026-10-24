"""Designer-Ziele: Java Swing, React (TSX) und Vue – Codeerzeugung, echte Übersetzung (javac, tsc, Vue-Compiler), Ereignisse, Layouts, Start."""
import json
import os
import shutil
import stat
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from conftest import needs
from vds.designer import codegen, targets
from vds.designer.controls import BY_TYPE, SPECS, new_props
from vds.designer.targets import swing, web


def ctl(ctype, name, x, y, w=None, h=None, **extra):
    spec = BY_TYPE[ctype]
    props = {**new_props(spec, name), **extra.pop("props", {})}
    return {"type": ctype, "name": name, "x": x, "y": y, "w": w or spec.size[0], "h": h or spec.size[1], "props": props, **extra}


def comp(ctype, **props):
    spec = BY_TYPE[ctype]
    return {"type": ctype, "name": spec.base + "1", "props": {**new_props(spec, spec.base + "1"), **props}}


def sample(target):
    m = codegen.new_form("Form1", target)
    m.update(width=520, height=400, controls=[
        ctl("GroupBox", "groupBox1", 16, 16, 220, 170, props={"layout": "Vertikal", "title": "Optionen"}),
        ctl("Button", "button1", 10, 20, parent="groupBox1", props={"text": "Speichern"}),
        ctl("CheckBox", "checkBox1", 10, 60, parent="groupBox1"),
        ctl("TextBox", "textBox1", 10, 100, parent="groupBox1"),
        ctl("TabWidget", "tabControl1", 260, 16, 240, 200, props={"tabs": ["Eins", "Zwei"]}),
        ctl("Label", "label1", 12, 12, parent="tabControl1", tab=0, props={"text": 'Sonder "zeichen" <b> {x}'}),
        ctl("ComboBox", "comboBox1", 12, 40, parent="tabControl1", tab=1),
        ctl("NumericUpDown", "numericUpDown1", 20, 250),
    ])
    return m


def every_control(target):
    ctrls, comps = [], []
    for i, sp in enumerate(SPECS):
        n = sp.base + "1"
        if sp.component:
            comps.append({"type": sp.type, "name": n, "props": new_props(sp, n)})
        else:
            ctrls.append({"type": sp.type, "name": n, "x": 10 + (i % 4) * 150, "y": 30 + (i // 4) * 50, "w": sp.size[0], "h": sp.size[1], "props": new_props(sp, n)})
    m = codegen.new_form("All", target)
    m.update(width=900, height=900, controls=ctrls, components=comps)
    return m


@pytest.fixture(scope="session")
def webtools(tmp_path_factory):
    """TypeScript, React-Typen und Vue-Compiler einmalig in einen Cache installieren (braucht npm und Netzwerk, sonst werden die Prüfungen übersprungen)."""
    cache = Path.home() / ".cache" / "vds-tests" / "webcheck"
    if not (cache / "node_modules" / "typescript").exists():
        if not shutil.which("npm"):
            pytest.skip("npm fehlt")
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "package.json").write_text('{"name":"webcheck","private":true}')
        r = subprocess.run(["npm", "install", "--silent", "typescript", "react", "react-dom", "@types/react", "@types/react-dom", "vue", "@vue/compiler-sfc"],
                           cwd=cache, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            pytest.skip("npm install nicht möglich (kein Netzwerk?)")
    (cache / "vuecheck.cjs").write_text(textwrap.dedent('''
        const sfc = require("@vue/compiler-sfc"); const fs = require("fs");
        const { descriptor, errors } = sfc.parse(fs.readFileSync(process.argv[2], "utf8"));
        if (errors.length) { console.log("PARSE", errors.map(e => e.message)); process.exit(1); }
        const script = sfc.compileScript(descriptor, { id: "x" });
        const tpl = sfc.compileTemplate({ source: descriptor.template.content, filename: "F.vue", id: "x", compilerOptions: { bindingMetadata: script.bindings } });
        if (tpl.errors.length) { console.log("TEMPLATE", tpl.errors.map(e => e.message || e)); process.exit(1); }
        console.log("ok");'''))
    return cache


def tsc(webtools, source: str) -> str:
    f = webtools / "Check.tsx"
    f.write_text(source)
    r = subprocess.run([str(webtools / "node_modules/.bin/tsc"), "--noEmit", "--jsx", "react-jsx", "--strict", "--skipLibCheck", "--esModuleInterop", "--moduleResolution", "bundler",
                        "--module", "esnext", "--target", "es2020", "--lib", "es2020,dom", "Check.tsx"], cwd=webtools, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


# --- Zielverwaltung --------------------------------------------------------------------------------
def test_target_registry_and_user_files(tmp_path):
    assert set(targets.TARGETS) == {"python-qt", "java-swing", "react", "vue", "angular"}
    f = tmp_path / "Form-1.form.json"
    for t, name in (("python-qt", "Form-1.py"), ("java-swing", "Form_1.java"), ("react", "Form-1.tsx"), ("vue", "Form-1.vue"), ("angular", "form-1.component.ts")):
        assert targets.user_file(f, {"target": t}).name == name
    assert targets.target_of({}) == "python-qt" and targets.target_of({"target": "cobol"}) == "python-qt"        # alte Dateien und Unsinn → Python/Qt
    assert targets.supports({"target": "react"}, "Button") and not targets.supports({"target": "react"}, "FontDialog")
    assert targets.supports({"target": "python-qt"}, "FontDialog")


def test_unsupported_controls_are_reported_not_silently_dropped():
    m = every_control("java-swing")
    miss = " ".join(targets.unsupported(m))
    assert "progressDialog1" in miss and "fontDialog1" in miss and "button1" not in miss
    assert targets.unsupported(every_control("python-qt")) == []
    src = swing.base_source(m, "All", "AllBase")
    assert "nicht erzeugt: " in src.splitlines()[1]


# --- Java Swing --------------------------------------------------------------------------------------
@needs("javac")
def test_java_swing_output_compiles_for_a_realistic_form(tmp_path):
    codegen.write_files(tmp_path / "Form1.form.json", sample("java-swing"))
    base_src = (tmp_path / "Form1Base.java").read_text()
    assert "BoxLayout(this.groupBox1, BoxLayout.Y_AXIS)" in base_src and 'createTitledBorder("Optionen")' in base_src
    assert "protected void button1Clicked()" in base_src and "checkBox1Toggled(this.checkBox1.isSelected())" in base_src
    assert "JTabbedPane" in base_src and "tabControl1_page1" in base_src
    r = subprocess.run(["javac", "-d", str(tmp_path / "out"), "Form1.java", "Form1Base.java"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@needs("javac")
def test_java_swing_every_supported_control_and_dialog_compiles(tmp_path):
    codegen.write_files(tmp_path / "All.form.json", every_control("java-swing"))
    r = subprocess.run(["javac", "-d", str(tmp_path / "out"), "All.java", "AllBase.java"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    src = (tmp_path / "AllBase.java").read_text()
    for needle in ("protected java.io.File openFileDialog1()", "JColorChooser.showDialog", "JOptionPane.showConfirmDialog", "setJMenuBar(this.menuBar1)"):
        assert needle in src


@needs("javac")
def test_java_user_class_survives_regeneration_and_gets_handler_stubs(tmp_path):
    f = tmp_path / "Form1.form.json"
    m = sample("java-swing")
    user = codegen.write_files(f, m)
    h = targets.handler(m, m["controls"][1])
    assert h == ("button1Clicked", "")
    line = targets.add_handler(user, m, *h)
    assert "@Override\n    protected void button1Clicked()" in user.read_text() and user.read_text().splitlines()[line - 1].lstrip().startswith("protected void button1Clicked")
    assert targets.add_handler(user, m, *h) == line and user.read_text().count("button1Clicked") == 1       # idempotent
    m["controls"].append(ctl("Button", "button2", 300, 300))
    codegen.write_files(f, m)                                                                                 # neu erzeugen: Basisklasse neu, Benutzerklasse bleibt
    assert "button1Clicked" in user.read_text() and "button2" in (tmp_path / "Form1Base.java").read_text()
    r = subprocess.run(["javac", "-d", str(tmp_path / "out"), "Form1.java", "Form1Base.java"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    checkbox_h = targets.handler(m, m["controls"][2])
    assert checkbox_h == ("checkBox1Toggled", "boolean checked")


@needs("java")
def test_java_source_launcher_finds_the_base_class(tmp_path):
    """`java Form1.java` übersetzt die Basisklasse mit; ohne Display endet es erst zur Laufzeit mit HeadlessException (Übersetzung war also erfolgreich)."""
    codegen.write_files(tmp_path / "Form1.form.json", sample("java-swing"))
    r = subprocess.run(["java", "-Djava.awt.headless=true", "Form1.java"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert "HeadlessException" in r.stderr and "error:" not in r.stderr


def test_java_layouts_map_to_swing_layout_managers():
    m = codegen.new_form("F", "java-swing")
    m.update(layout="Raster", grid_columns=2, spacing=4, margin=5, controls=[ctl("Button", f"b{i}", 10 + (i % 2) * 100, 10 + (i // 2) * 40) for i in range(4)])
    src = swing.base_source(m, "F", "FBase")
    assert "root.setLayout(new GridLayout(0, 2, 4, 4));" in src and "createEmptyBorder(5, 5, 5, 5)" in src
    m2 = codegen.new_form("F", "java-swing")
    m2.update(layout="Horizontal", controls=[ctl("Button", "z", 200, 0), ctl("Button", "a", 10, 0)])
    s2 = swing.base_source(m2, "F", "FBase")
    assert "BoxLayout.X_AXIS" in s2 and s2.index("root.add(this.a)") < s2.index("root.add(this.z)") and "createHorizontalStrut(6)" in s2


# --- React / Vue ---------------------------------------------------------------------------------------
def test_react_output_structure():
    m = sample("react")
    src = web.react_source(m, "Form1")
    assert src.startswith('"use client";') and "export default function Form1(props: Form1Props)" in src
    assert "onButton1Clicked?: () => void;" in src and "onCheckBox1Toggled?: (checked: boolean) => void;" in src and "onTabControl1TabChanged?: (index: number) => void;" in src
    assert "display: \"flex\"" in src and "flexDirection: \"column\"" in src and "position: \"absolute\"" in src            # Layout → Flex, frei → absolut
    assert "useState(0)" in src and "tabControl1Tab === 1 && (" in src
    assert '{"Sonder \\"zeichen\\" <b> {x}"}' in src                                                                       # Sonderzeichen sicher als Ausdruck


def test_vue_output_structure():
    src = web.vue_source(sample("vue"), "Form1")
    assert '<script setup lang="ts">' in src and "defineEmits" in src and '(e: "button1Clicked"): void;' in src
    assert '@click="emit(\'button1Clicked\')"' in src and 'v-if="tabControl1Tab === 0"' in src and "const tabControl1Tab = ref(0);" in src
    assert "&lt;b&gt;" in src or "{{ " in src                                                                              # kein ungeschütztes <b> im Template
    assert 'font-family:&quot;Segoe UI&quot;' in src                                                                       # Anführungszeichen im style-Attribut maskiert


def test_web_layouts_become_flex_and_grid():
    m = codegen.new_form("F", "react")
    m.update(layout="Raster", grid_columns=3, spacing=8, margin=10, controls=[ctl("Button", f"b{i}", 10 + (i % 3) * 100, 10 + (i // 3) * 40) for i in range(6)])
    src = web.react_source(m, "F")
    assert 'display: "grid"' in src and 'gridTemplateColumns: "repeat(3, 1fr)"' in src and 'gap: 8' in src and "position: \"absolute\"" not in src.split("<div", 1)[1].split(">")[1]
    m["layout"] = "Horizontal"
    assert 'flexDirection: "row"' in web.react_source(m, "F")


def test_web_components_become_exported_helper_functions():
    m = codegen.new_form("F", "react")
    m["components"] = [comp("MessageBox", buttons="YesNo", text="Wirklich?"), comp("InputDialog"), comp("OpenFileDialog", multiselect=True), comp("ColorDialog"), comp("PrintDialog"),
                      comp("FontDialog")]
    src = web.react_source(m, "F")
    assert "export function messageBox1(): boolean" in src and "window.confirm(\"Wirklich?\")" in src and "input.multiple = true" in src
    assert "export function colorDialog1(): Promise<string>" in src and "window.print()" in src and "fontDialog1" not in src
    assert "fontDialog1 (FontDialog)" in targets.unsupported(m)
    vue = web.vue_source(m, "F")
    assert '<script lang="ts">' in vue and "export function inputDialog1(): string | null" in vue


def test_tsc_accepts_generated_react_for_realistic_and_complete_forms(webtools):
    assert tsc(webtools, web.react_source(sample("react"), "Form1")) == ""
    assert tsc(webtools, web.react_source(every_control("react"), "All")) == ""


def test_vue_compiler_accepts_generated_templates(webtools, tmp_path):
    for name, m in (("Form1", sample("vue")), ("All", every_control("vue"))):
        f = tmp_path / f"{name}.vue"
        f.write_text(web.vue_source(m, name))
        r = subprocess.run(["node", str(webtools / "vuecheck.cjs"), str(f)], cwd=webtools, capture_output=True, text=True, timeout=60)
        assert r.stdout.strip() == "ok", r.stdout + r.stderr


# --- Dateien, Eigenschaften, Oberfläche -------------------------------------------------------------------
def test_write_files_for_web_targets_overwrites_component_each_time(tmp_path):
    for t, ext in (("react", ".tsx"), ("vue", ".vue")):
        f = tmp_path / f"Page.form.json"
        m = sample(t)
        out = codegen.write_files(f, m)
        assert out.name == "Page" + ext and json.loads(f.read_text())["target"] == t
        out.write_text("// manuell geändert")
        codegen.write_files(f, m)
        assert "Automatisch von Visual Death Studio" in out.read_text()        # Komponente ist erzeugt, wird bewusst neu geschrieben


def test_python_target_still_default_and_unchanged(tmp_path):
    m = codegen.new_form("Alt")
    assert m["target"] == "python-qt"
    del m["target"]                                                            # Datei aus einer früheren Version
    out = codegen.write_files(tmp_path / "Alt.form.json", m)
    assert out.name == "Alt.py" and (tmp_path / "Alt_designer.py").exists()


def test_designer_form_property_target_and_new_form_dialog(qapp, tmp_path):
    from vds.designer.canvas import FormDesigner
    from vds.docks.props import PropertiesDock
    from vds.ui.dialogs import NewFormDialog, suggest_target
    d = FormDesigner(codegen.new_form("F"))
    dock = PropertiesDock(); dock.show_designer(d)
    labels = [dock.grid.item(r, 0).text() for r in range(dock.grid.rowCount()) if dock.grid.item(r, 0)]
    assert "Ziel" in labels
    assert d.canvas.set_prop(None, "target", "react") and d.model["target"] == "react"
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"vue": "^3"}}))
    assert suggest_target(tmp_path) == "vue"
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"next": "15", "react": "19"}})); assert suggest_target(tmp_path) == "react"
    (tmp_path / "package.json").unlink(); (tmp_path / "A.java").write_text("class A {}"); assert suggest_target(tmp_path) == "java-swing"
    (tmp_path / "A.java").unlink(); assert suggest_target(tmp_path) == "python-qt"
    dlg = NewFormDialog(tmp_path); dlg.name.setText("Start"); dlg.target.setCurrentIndex(dlg.target.findData("vue"))
    assert dlg.values() == ("Start", "vue")


def test_main_window_new_form_open_designer_and_handlers_for_each_target(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.app import MainWindow
    from vds.ui import dialogs
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    monkeypatch.setattr(dialogs.NewFormDialog, "exec", lambda self: 1)
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    try:
        for t, ext, comp_file in (("java-swing", ".java", "Seite1.java"), ("react", ".tsx", "Seite2.tsx"), ("vue", ".vue", "Seite3.vue")):
            name = comp_file.split(".")[0]
            monkeypatch.setattr(dialogs.NewFormDialog, "values", lambda self, n=name, tt=t: (n, tt))
            w.new_form()
            doc = w.docs.current_doc()
            assert doc.kind == "form" and doc.target == t and doc.run_target.name == comp_file and doc.run_target.exists()
            doc.view.add_control("Button")
            w._open_handler(doc, "button1")
            if t == "java-swing":
                assert "button1Clicked" in (tmp_path / comp_file).read_text() and w.docs.current_doc().path.name == comp_file
            else:
                assert "button1Clicked" in w.statusBar().currentMessage()
        # Doppelklick auf die Benutzerdatei öffnet wieder den Designer (wie bei Form1.py)
        w._open_file(tmp_path / "Seite1.java")
        assert w.docs.current_doc().kind == "form"
    finally:
        w.docs.close_all(); w.close()


def test_form_save_reports_unsupported_controls(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.app import MainWindow
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    m = codegen.new_form("F", "java-swing"); m["components"] = [comp("ProgressDialog")]
    codegen.write_files(tmp_path / "F.form.json", m)
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    try:
        doc = w.docs.open(tmp_path / "F.form.json")
        doc.view.canvas.add_control("Button")
        w.docs.save()
        assert "progressDialog1" in w.statusBar().currentMessage() and "Java" in w.statusBar().currentMessage()
    finally:
        w.docs.close_all(); w.close()


# --- Starten (Dev-Server) ------------------------------------------------------------------------------------
def fake_npm(bindir: Path, log: Path):
    bindir.mkdir(exist_ok=True)
    exe = bindir / "npm"
    exe.write_text(f'#!/usr/bin/env bash\necho "npm $@" >> {log}\nif [ "$1" = "run" ]; then (sleep 300 & echo $! > {log}.child; wait); fi\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)


def test_web_form_runs_dev_server_and_stop_kills_the_whole_process_group(qapp, pump, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.app import MainWindow
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    log = tmp_path / "npm.log"
    fake_npm(tmp_path / "bin", log)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    proj = tmp_path / "proj"; (proj / "src").mkdir(parents=True)
    (proj / "package.json").write_text('{"scripts": {"dev": "vite"}}')
    codegen.write_files(proj / "src" / "Home.form.json", sample("react"))
    w = MainWindow(); w.show(); w.set_root(proj)
    try:
        w.docs.open(proj / "src" / "Home.form.json")
        w.run("buildrun")
        assert pump(lambda: (tmp_path / "npm.log.child").exists(), 20)
        assert log.read_text().splitlines() == ["npm install", "npm run dev"]                    # ohne node_modules zuerst installieren
        assert (proj / "src" / "Home.tsx").exists() and w.runner.busy and w.a["stop"].isEnabled()
        child = int((tmp_path / "npm.log.child").read_text())
        w.stop_any()
        assert pump(lambda: not w.runner.busy, 20)
        time.sleep(0.5)
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)                                                                      # auch der Kindprozess ist weg
    finally:
        w.docs.close_all(); w.close()


def test_web_form_without_package_json_explains(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.app import MainWindow
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    codegen.write_files(tmp_path / "Home.form.json", sample("vue"))
    w = MainWindow(); w.show(); w.set_root(tmp_path)
    try:
        w.docs.open(tmp_path / "Home.form.json"); w.run("buildrun")
        assert "package.json" in w.output.text.toPlainText() and not w.runner.busy
    finally:
        w.docs.close_all(); w.close()


def test_toolbox_dims_controls_the_target_cannot_generate(qapp):
    from PySide6.QtWidgets import QApplication
    from vds.docks.tools import CTRL_ROLE, Toolbox
    tb = Toolbox()

    def find(t):
        az = next(tb.tree.topLevelItem(i) for i in range(tb.tree.topLevelItemCount()) if tb.tree.topLevelItem(i).text(0).startswith("Alle"))
        return next(az.child(i) for i in range(az.childCount()) if az.child(i).data(0, CTRL_ROLE) == t)
    assert "nicht verfügbar" not in find("FontDialog").toolTip(0)
    tb.set_target("react")
    assert "nicht verfügbar" in find("FontDialog").toolTip(0) and "React" in find("FontDialog").toolTip(0) and "nicht verfügbar" not in find("Button").toolTip(0)
    tb.set_target("python-qt")
    assert "nicht verfügbar" not in find("FontDialog").toolTip(0)
    tb.set_target("")


# --- Angular -------------------------------------------------------------------------------------------------------
def test_angular_component_structure():
    src = web.angular_source(sample("angular"), "Form1Component", "app-form1")
    assert "import { Component, EventEmitter, Output } from '@angular/core';" in src and "selector: 'app-form1'," in src and "export class Form1Component {" in src
    assert "@Output() button1Clicked = new EventEmitter<void>();" in src and "@Output() checkBox1Toggled = new EventEmitter<boolean>();" in src
    assert "@Output() numericUpDown1ValueChanged = new EventEmitter<number>();" in src and "tabControl1Tab = 0;" in src
    assert '(click)="button1Clicked.emit()"' in src and '(change)="checkBox1Toggled.emit($any($event.target).checked)"' in src
    assert "@if (tabControl1Tab === 1) {" in src and "(click)=\"tabControl1Tab = 1; tabControl1TabChanged.emit(1)\"" in src
    assert "&#123;x&#125;" in src and "&lt;b&gt;" in src                                       # { } und < > im Text maskiert (Control-Flow-Syntax!)
    assert 'font-family:&quot;Segoe UI&quot;' in src and 'data-vds="button1"' in src


def test_angular_names_and_file(tmp_path):
    assert web.angular_names("Form1") == ("form1.component.ts", "Form1Component", "app-form1")
    assert web.angular_names("MeineSeite")[0] == "meine-seite.component.ts" and web.angular_names("MeineSeite")[2] == "app-meine-seite"
    m = sample("angular")
    out = codegen.write_files(tmp_path / "MeineSeite.form.json", m)
    assert out.name == "meine-seite.component.ts" and "class MeineSeiteComponent" in out.read_text() and targets.user_file(tmp_path / "MeineSeite.form.json", m) == out


def test_angular_template_literal_is_safe_for_backticks_and_dollar_braces():
    m = codegen.new_form("F", "angular")
    m["controls"] = [ctl("Label", "label1", 5, 5, props={"text": "Preis `5` ${x} \\ @if"})]
    src = web.angular_source(m, "FComponent", "app-f")
    assert "\\`5\\`" in src and "$&#123;x&#125;" in src and "&#64;if" in src and "\\\\" in src      # Backticks maskiert, ${ im Text wird zu Entities (kein Template-Literal-Einschub)


def test_tsc_accepts_angular_strings_are_valid_typescript(webtools):
    """Die Angular-Komponente ist gültiges TypeScript (die Template-Prüfung übernimmt der echte Angular-Build in den Vorlagen)."""
    f = webtools / "Ng.ts"
    (webtools / "ngshim.d.ts").write_text("declare module '@angular/core' { export const Component: any; export class EventEmitter<T> { emit(v?: T): void } export const Output: any; }\n")
    f.write_text(web.angular_source(every_control("angular"), "AllComponent", "app-all"))
    r = subprocess.run([str(webtools / "node_modules/.bin/tsc"), "--noEmit", "--skipLibCheck", "--target", "es2020", "--lib", "es2020,dom", "--experimentalDecorators",
                        "--strict", "--moduleResolution", "bundler", "--module", "esnext", "Ng.ts", "ngshim.d.ts"], cwd=webtools, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_web_form_picks_the_start_script_when_there_is_no_dev_script(qapp, pump, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.app import MainWindow
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    log = tmp_path / "npm.log"
    fake_npm(tmp_path / "bin", log)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    proj = tmp_path / "ng"; (proj / "node_modules").mkdir(parents=True)
    (proj / "package.json").write_text('{"scripts": {"start": "ng serve"}}')
    codegen.write_files(proj / "Home.form.json", sample("angular"))
    w = MainWindow(); w.show(); w.set_root(proj)
    try:
        w.docs.open(proj / "Home.form.json"); w.run("buildrun")
        assert pump(lambda: (tmp_path / "npm.log.child").exists(), 20)
        assert log.read_text().splitlines() == ["npm run start"]                  # node_modules vorhanden: kein install, Angular-Skript „start“
        assert (proj / "home.component.ts").exists()
        w.stop_any(); pump(lambda: not w.runner.busy, 20)
    finally:
        w.docs.close_all(); w.close()
