"""Java-Swing-Ausgabe des Designers: <Name>Base.java (immer neu erzeugt, mit allen Controls und überschreibbaren Ereignis-Methoden)
und <Name>.java (Benutzerklasse, einmalig angelegt, startbar mit `java <Name>.java`)."""
import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QColor

from .. import layouts
from ..controls import BY_TYPE
from . import base

SUPPORTED = {"Button", "Label", "TextBox", "RichTextBox", "CheckBox", "RadioButton", "ComboBox", "ListBox", "NumericUpDown", "DoubleSpinBox", "TrackBar",
             "ProgressBar", "Line", "PictureBox", "DateEdit", "TimeEdit", "GroupBox", "Panel", "TabWidget",
             "ToolButton", "CommandLinkButton", "DateTimeEdit", "CalendarWidget", "Dial", "ScrollBar", "LcdNumber", "TextBrowser", "TableWidget", "TableView",
             "TreeWidget", "TreeView", "ListView", "FontComboBox", "KeySequenceEdit", "MenuBar", "StatusBar", "DialogButtonBox"}
COMPONENTS = {"OpenFileDialog", "SaveFileDialog", "FolderBrowserDialog", "ColorDialog", "InputDialog", "MessageBox", "PrintDialog", "PageSetupDialog"}
JAVA_ARG = {"checked": "boolean checked", "index": "int index", "value": "int value", "text": "String text"}


def java_str(s) -> str:
    out = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "").replace("\t", "\\t")
    return '"' + out + '"'


def color(hexstr: str) -> str:
    c = QColor(hexstr)
    return f"new Color({c.red()}, {c.green()}, {c.blue()})"


def names(stem: str) -> tuple:
    n = re.sub(r"\W", "_", stem)
    comp = ("C" + n) if not n or not n[0].isalpha() else n[0].upper() + n[1:]
    return comp, comp + "Base"


@dataclass
class Ctx:
    fields: list = field(default_factory=list)      # (Typ, Name)
    handlers: dict = field(default_factory=dict)    # Methodenname -> Parameter
    lines: list = field(default_factory=list)
    groups: set = field(default_factory=set)
    docs: bool = False
    n: int = 0

    def add(self, line: str):
        self.lines.append("        " + line)


def font_line(var: str, p: dict) -> str:
    f = base.font_of(p)
    if not f:
        return ""
    style = ("Font.BOLD" if f["bold"] else "Font.PLAIN") + (" | Font.ITALIC" if f["italic"] else "")
    return f'{var}.setFont(new Font({java_str(f["family"] or "SansSerif")}, {style}, {round(f["size"] * 96 / 72)}));'


def common(ctx: Ctx, var: str, p: dict, bg=True):
    if p.get("tooltip"):
        ctx.add(f"{var}.setToolTipText({java_str(p['tooltip'])});")
    if p.get("enabled") is False:
        ctx.add(f"{var}.setEnabled(false);")
    fl = font_line(var, p)
    if fl:
        ctx.add(fl)
    if p.get("fore_color"):
        ctx.add(f"{var}.setForeground({color(p['fore_color'])});")
    if p.get("back_color") and bg:
        ctx.add(f"{var}.setOpaque(true);")
        ctx.add(f"{var}.setBackground({color(p['back_color'])});")


def border_line(holder: str, src: dict, title: str | None = None, line: bool = False):
    mode, spacing, margin, cols = layouts.cfg(src)
    parts = []
    if title is not None:
        parts.append(f"BorderFactory.createTitledBorder({java_str(title)})")
    elif line:
        parts.append("BorderFactory.createLineBorder(Color.GRAY)")
    if mode != "Keine":
        parts.append(f"BorderFactory.createEmptyBorder({margin}, {margin}, {margin}, {margin})")
    if not parts:
        return ""
    expr = parts[0] if len(parts) == 1 else f"BorderFactory.createCompoundBorder({parts[0]}, {parts[1]})"
    return f"{holder}.setBorder({expr});"


def set_layout(ctx: Ctx, holder: str, src: dict):
    mode, spacing, margin, cols = layouts.cfg(src)
    if mode == "Keine":
        ctx.add(f"{holder}.setLayout(null);")
    elif mode == "Raster":
        ctx.add(f"{holder}.setLayout(new GridLayout(0, {cols}, {spacing}, {spacing}));")
    else:
        ctx.add(f"{holder}.setLayout(new BoxLayout({holder}, BoxLayout.{'Y_AXIS' if mode == 'Vertikal' else 'X_AXIS'}));")


def wire(ctx: Ctx, c: dict, var: str):
    """Ereignis des Controls an die überschreibbare Methode {name}{Ereignis} der Basisklasse binden."""
    spec, t, name = BY_TYPE[c["type"]], c["type"], c["name"]
    if not spec.event:
        return
    sig, suffix, args = spec.event
    method = base.event_name(name, suffix)
    # Argument und Auslöser je Control-Art
    getter = {"CheckBox": f"{var}.isSelected()", "RadioButton": f"{var}.isSelected()", "ComboBox": f"{var}.getSelectedIndex()",
              "NumericUpDown": f"((Number) {var}.getValue()).intValue()", "TrackBar": f"{var}.getValue()", "TabWidget": f"{var}.getSelectedIndex()",
              "TextBox": f"{var}.getText()"}
    params = {"Button": "", "CheckBox": "boolean checked", "RadioButton": "boolean checked", "ComboBox": "int index", "NumericUpDown": "int value",
              "TrackBar": "int value", "TabWidget": "int index", "TextBox": "String text", "ListBox": ""}
    if t not in params:
        return
    call = f"{method}({getter[t] if params[t] else ''})"
    if t in ("Button", "CheckBox", "RadioButton", "ComboBox"):
        ctx.add(f"{var}.addActionListener(e -> {call});")
    elif t in ("NumericUpDown", "TrackBar", "TabWidget"):
        ctx.add(f"{var}.addChangeListener(e -> {call});")
    elif t == "ListBox":
        ctx.add(f"{var}.addListSelectionListener(e -> {method}());")
    elif t == "TextBox":
        ctx.docs = True
        ctx.add(f"onTextChanged({var}, () -> {call});")
    ctx.handlers[method] = params[t]


def items_array(items) -> str:
    return "new String[] {" + ", ".join(java_str(i) for i in items) + "}"


def emit_control(ctx: Ctx, model: dict, c: dict, holder: str, mode: str):
    t, p, name = c["type"], c["props"], c["name"]
    var = f"this.{name}"
    outer = var                                                  # was dem Container hinzugefügt wird (ggf. ScrollPane)
    typ = None
    ctx.n += 1
    if t in ("Button", "ToolButton", "CommandLinkButton"):
        typ = "JButton"; ctx.add(f"{var} = new JButton({java_str(p.get('text', ''))});")
        if p.get("flat"):
            ctx.add(f"{var}.setBorderPainted(false);")
    elif t == "Label":
        typ = "JLabel"
        text = p.get("text", "")
        if p.get("word_wrap"):
            text = "<html>" + html.escape(str(text)) + "</html>"
        ctx.add(f"{var} = new JLabel({java_str(text)});")
        al = {"Links": "LEFT", "Mitte": "CENTER", "Rechts": "RIGHT"}.get(p.get("alignment", ""))
        if al:
            ctx.add(f"{var}.setHorizontalAlignment(SwingConstants.{al});")
    elif t in ("TextBox", "KeySequenceEdit"):
        typ = "JPasswordField" if p.get("password") else "JTextField"
        ctx.add(f"{var} = new {typ}({java_str(p.get('text', ''))});")
        if p.get("readonly"):
            ctx.add(f"{var}.setEditable(false);")
        al = {"Links": "LEFT", "Mitte": "CENTER", "Rechts": "RIGHT"}.get(p.get("alignment", ""))
        if al:
            ctx.add(f"{var}.setHorizontalAlignment(JTextField.{al});")
    elif t == "RichTextBox":
        typ = "JTextArea"; ctx.add(f"{var} = new JTextArea({java_str(p.get('text', ''))});")
        if p.get("readonly"):
            ctx.add(f"{var}.setEditable(false);")
        outer = f"sp_{name}"; ctx.add(f"JScrollPane {outer} = new JScrollPane({var});")
    elif t in ("CheckBox", "RadioButton"):
        typ = "JCheckBox" if t == "CheckBox" else "JRadioButton"
        ctx.add(f"{var} = new {typ}({java_str(p.get('text', ''))}, {'true' if p.get('checked') else 'false'});")
        if t == "RadioButton":
            g = "group_" + (c.get("parent") or "root")
            if g not in ctx.groups:
                ctx.groups.add(g); ctx.add(f"ButtonGroup {g} = new ButtonGroup();")
            ctx.add(f"{g}.add({var});")
    elif t == "ComboBox":
        typ = "JComboBox<String>"; ctx.add(f"{var} = new JComboBox<>({items_array(p.get('items', []))});")
    elif t == "ListBox":
        typ = "JList<String>"; ctx.add(f"{var} = new JList<>({items_array(p.get('items', []))});")
        outer = f"sp_{name}"; ctx.add(f"JScrollPane {outer} = new JScrollPane({var});")
    elif t in ("NumericUpDown", "DoubleSpinBox"):
        typ = "JSpinner"
        if t == "NumericUpDown":
            ctx.add(f"{var} = new JSpinner(new SpinnerNumberModel({int(p.get('value', 0))}, {int(p.get('minimum', 0))}, {int(p.get('maximum', 100))}, 1));")
        else:
            ctx.add(f"{var} = new JSpinner(new SpinnerNumberModel({float(p.get('value', 0))}, {float(p.get('minimum', 0))}, {float(p.get('maximum', 100))}, 0.1));")
    elif t in ("TrackBar", "Dial"):
        typ = "JSlider"
        o = "VERTICAL" if p.get("orientation") == "Vertical" else "HORIZONTAL"
        ctx.add(f"{var} = new JSlider(JSlider.{o}, {int(p.get('minimum', 0))}, {int(p.get('maximum', 100))}, {int(p.get('value', 0))});")
    elif t == "ScrollBar":
        typ = "JScrollBar"
        o = "VERTICAL" if p.get("orientation") == "Vertical" else "HORIZONTAL"
        ctx.add(f"{var} = new JScrollBar(JScrollBar.{o}, {int(p.get('value', 0))}, 10, {int(p.get('minimum', 0))}, {int(p.get('maximum', 100)) + 10});")
    elif t == "LcdNumber":
        typ = "JLabel"
        ctx.add(f"{var} = new JLabel({java_str(str(p.get('value', 0)))}, SwingConstants.RIGHT);")
        ctx.add(f"{var}.setFont(new Font(Font.MONOSPACED, Font.BOLD, {max(14, c['h'] - 12)}));")
        ctx.add(f"{var}.setOpaque(true); {var}.setBackground(Color.BLACK); {var}.setForeground(new Color(124, 252, 0));")
    elif t == "TextBrowser":
        typ = "JEditorPane"; ctx.add(f"{var} = new JEditorPane();")
        ctx.add(f"{var}.setText({java_str(p.get('text', ''))}); {var}.setEditable(false);")
        outer = f"sp_{name}"; ctx.add(f"JScrollPane {outer} = new JScrollPane({var});")
    elif t in ("TableWidget", "TableView"):
        typ = "JTable"
        rows, cols = (int(p.get("rows", 3)), int(p.get("columns", 3))) if t == "TableWidget" else (3, 3)
        ctx.add(f"{var} = new JTable({rows}, {cols});")
        outer = f"sp_{name}"; ctx.add(f"JScrollPane {outer} = new JScrollPane({var});")
    elif t in ("TreeWidget", "TreeView"):
        typ = "JTree"
        ctx.add(f"{var} = new JTree(new javax.swing.tree.DefaultMutableTreeNode());")
        items = p.get("items", []) if t == "TreeWidget" else []
        if items:
            ctx.add(f"{var}.setModel(new javax.swing.tree.DefaultTreeModel(new javax.swing.tree.DefaultMutableTreeNode(\"\") {{{{ "
                    + " ".join(f"add(new javax.swing.tree.DefaultMutableTreeNode({java_str(i)}));" for i in items) + " }}));")
        ctx.add(f"{var}.setRootVisible(false);")
        outer = f"sp_{name}"; ctx.add(f"JScrollPane {outer} = new JScrollPane({var});")
    elif t == "ListView":
        typ = "JList<String>"; ctx.add(f"{var} = new JList<>(new String[0]);")
        outer = f"sp_{name}"; ctx.add(f"JScrollPane {outer} = new JScrollPane({var});")
    elif t == "FontComboBox":
        typ = "JComboBox<String>"
        ctx.add(f"{var} = new JComboBox<>(GraphicsEnvironment.getLocalGraphicsEnvironment().getAvailableFontFamilyNames());")
    elif t == "MenuBar":
        typ = "JMenuBar"; ctx.add(f"{var} = new JMenuBar();")
        for it in p.get("items", []):
            ctx.add(f"{var}.add(new JMenu({java_str(it)}));")
    elif t == "StatusBar":
        typ = "JLabel"; ctx.add(f"{var} = new JLabel({java_str(p.get('text', ''))});")
        ctx.add(f"{var}.setBorder(BorderFactory.createMatteBorder(1, 0, 0, 0, Color.GRAY));")
    elif t == "DialogButtonBox":
        typ = "JPanel"; ctx.add(f"{var} = new JPanel(new FlowLayout(FlowLayout.RIGHT));")
        ctx.add(f"{var}.add(new JButton(\"OK\")); {var}.add(new JButton(\"Abbrechen\"));")
    elif t == "ProgressBar":
        typ = "JProgressBar"
        ctx.add(f"{var} = new JProgressBar({int(p.get('minimum', 0))}, {int(p.get('maximum', 100))});")
        ctx.add(f"{var}.setValue({int(p.get('value', 0))});")
    elif t == "Line":
        typ = "JSeparator"; ctx.add(f"{var} = new JSeparator(SwingConstants.{'VERTICAL' if p.get('orientation') == 'Vertical' else 'HORIZONTAL'});")
    elif t == "PictureBox":
        typ = "JLabel"
        ctx.add(f"{var} = new JLabel({'new ImageIcon(' + java_str(p['image']) + ')' if p.get('image') else '(Icon) null'});")
    elif t in ("DateEdit", "TimeEdit", "DateTimeEdit", "CalendarWidget"):
        typ = "JSpinner"
        ctx.add(f"{var} = new JSpinner(new SpinnerDateModel());")
        fmt = {"TimeEdit": "HH:mm", "DateTimeEdit": "yyyy-MM-dd HH:mm"}.get(t, "yyyy-MM-dd")
        ctx.add(f"{var}.setEditor(new JSpinner.DateEditor({var}, {java_str(fmt)}));")
    elif t in ("GroupBox", "Panel"):
        typ = "JPanel"; ctx.add(f"{var} = new JPanel();")
        set_layout(ctx, var, p)
        b = border_line(var, p, p.get("title", "") if t == "GroupBox" else None, line=t == "Panel")
        b and ctx.add(b)
    elif t == "TabWidget":
        typ = "JTabbedPane"; ctx.add(f"{var} = new JTabbedPane();")
    ctx.fields.append((typ, name))
    common(ctx, var, p, bg=t not in ("TabWidget",))
    wire(ctx, c, var)
    if t == "MenuBar" and c.get("parent") is None:
        ctx.add(f"setJMenuBar({var});")                       # Menüleiste gehört an den Fensterrahmen
        return None
    # Platzierung
    if mode == "Keine":
        ctx.add(f"{outer}.setBounds({c['x']}, {c['y']}, {c['w']}, {c['h']});")
    elif mode in ("Vertikal", "Horizontal"):
        ctx.add(f"{outer}.setPreferredSize(new Dimension({c['w']}, {c['h']}));")
        big = "Integer.MAX_VALUE"
        ctx.add(f"{outer}.setMaximumSize(new Dimension({big if mode == 'Vertikal' else c['w']}, {c['h'] if mode == 'Vertikal' else big}));")
        ctx.add(f"{outer}.setAlignment{'X' if mode == 'Vertikal' else 'Y'}(Component.{'LEFT' if mode == 'Vertikal' else 'TOP'}_ALIGNMENT);")
    else:
        ctx.add(f"{outer}.setPreferredSize(new Dimension({c['w']}, {c['h']}));")
    return outer


def emit_level(ctx: Ctx, model: dict, parent, tab, holder: str):
    src = model if parent is None else layouts.by_name(model)[parent]["props"]
    mode, spacing = layouts.cfg(src)[0], layouts.cfg(src)[1]
    first = True
    for c in base.kids(model, parent, tab):
        if c["type"] not in SUPPORTED:
            continue
        if mode in ("Vertikal", "Horizontal") and not first and spacing:
            ctx.add(f"{holder}.add(Box.create{'Vertical' if mode == 'Vertikal' else 'Horizontal'}Strut({spacing}));")
        first = False
        outer = emit_control(ctx, model, c, holder, mode)
        if outer is None:
            continue
        if c["type"] == "TabWidget":
            for i, title in enumerate(layouts.tab_titles(c["props"])):
                page = f"{c['name']}_page{i}"
                ctx.add(f"JPanel {page} = new JPanel();")
                set_layout(ctx, page, c["props"])
                b = border_line(page, c["props"])
                b and ctx.add(b)
                ctx.add(f"this.{c['name']}.addTab({java_str(title)}, {page});")
                emit_level(ctx, model, c["name"], i, page)
            ctx.add(f"this.{c['name']}.setSelectedIndex({min(max(int(c['props'].get('current', 0)), 0), len(layouts.tab_titles(c['props'])) - 1)});")
        elif c["type"] in ("GroupBox", "Panel"):
            emit_level(ctx, model, c["name"], None, f"this.{c['name']}")
        ctx.add(f"{holder}.add({outer});")


def component_method(c: dict) -> str:
    """Dialog-Komponenten als geschützte Hilfsmethoden der Basisklasse (Aufruf z. B. `File f = openFileDialog1();`)."""
    t, n, p = c["type"], c["name"], c["props"]
    j = lambda k: java_str(p.get(k, ""))
    if t in ("OpenFileDialog", "SaveFileDialog", "FolderBrowserDialog"):
        mode = {"FolderBrowserDialog": "DIRECTORIES_ONLY"}.get(t, "FILES_ONLY")
        filt = ""
        if t != "FolderBrowserDialog" and p.get("filter") and "(*)" not in str(p["filter"]):
            exts = re.findall(r"\*\.(\w+)", str(p["filter"]))
            if exts:
                filt = f"        fc.setFileFilter(new javax.swing.filechooser.FileNameExtensionFilter({j('filter')}, {', '.join(java_str(e) for e in exts)}));\n"
        show = "showSaveDialog" if t == "SaveFileDialog" else "showOpenDialog"
        multi = "        fc.setMultiSelectionEnabled(true);\n" if p.get("multiselect") else ""
        start = f"        fc.setCurrentDirectory(new java.io.File({j('directory')}));\n" if p.get("directory") else ""
        ret = "fc.getSelectedFiles()" if p.get("multiselect") else "fc.getSelectedFile()"
        rtype = "java.io.File[]" if p.get("multiselect") else "java.io.File"
        return (f"\n    /** {t}: Auswahl oder null bei Abbruch. */\n    protected {rtype} {n}() {{\n        JFileChooser fc = new JFileChooser();\n"
                f"        fc.setDialogTitle({j('title')});\n        fc.setFileSelectionMode(JFileChooser.{mode});\n{filt}{multi}{start}"
                f"        return fc.{show}(this) == JFileChooser.APPROVE_OPTION ? {ret} : null;\n    }}\n")
    if t == "ColorDialog":
        return (f"\n    /** Gewählte Farbe oder null bei Abbruch. */\n    protected Color {n}() {{\n        return JColorChooser.showDialog(this, {j('title')}, "
                f"{color(p.get('color') or '#ffffff')});\n    }}\n")
    if t == "InputDialog":
        return (f"\n    /** Eingabe oder null bei Abbruch. */\n    protected String {n}() {{\n        return (String) JOptionPane.showInputDialog(this, {j('label')}, "
                f"{j('title')}, JOptionPane.QUESTION_MESSAGE, null, null, {j('text')});\n    }}\n")
    if t == "MessageBox":
        icon = {"Information": "INFORMATION_MESSAGE", "Warning": "WARNING_MESSAGE", "Critical": "ERROR_MESSAGE", "Question": "QUESTION_MESSAGE"}.get(p.get("icon"), "INFORMATION_MESSAGE")
        opt = {"Ok": "DEFAULT_OPTION", "OkCancel": "OK_CANCEL_OPTION", "YesNo": "YES_NO_OPTION", "YesNoCancel": "YES_NO_CANCEL_OPTION"}.get(p.get("buttons"), "DEFAULT_OPTION")
        return (f"\n    /** Ergebnis: JOptionPane.YES_OPTION, OK_OPTION, NO_OPTION, CANCEL_OPTION … */\n    protected int {n}() {{\n"
                f"        return JOptionPane.showConfirmDialog(this, {j('text')}, {j('title')}, JOptionPane.{opt}, JOptionPane.{icon});\n    }}\n")
    if t in ("PrintDialog", "PageSetupDialog"):
        call = "printDialog()" if t == "PrintDialog" else "pageDialog(job.defaultPage()) != null"
        return (f"\n    /** true = bestätigt; gedruckt wird über den zurückgegebenen Druckauftrag. */\n    protected boolean {n}() {{\n"
                f"        java.awt.print.PrinterJob job = java.awt.print.PrinterJob.getPrinterJob();\n        return job.{call};\n    }}\n")
    return ""


def base_source(model: dict, comp: str, base_name: str) -> str:
    layouts.normalize(model)
    ctx = Ctx()
    ctx.add("setTitle(" + java_str(model.get("title", comp)) + ");")
    ctx.add("setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);")
    ctx.add("JPanel root = new JPanel();")
    set_layout(ctx, "root", model)
    b = border_line("root", model)
    b and ctx.add(b)
    ctx.add(f"root.setPreferredSize(new Dimension({model['width']}, {model['height']}));")
    if model.get("back_color"):
        ctx.add(f"root.setBackground({color(model['back_color'])});")
    emit_level(ctx, model, None, None, "root")
    ctx.add("setContentPane(root);")
    ctx.add("pack();")
    ctx.add("setLocationRelativeTo(null);")
    notes = base.unsupported(model, SUPPORTED) + [f"{c['name']} ({c['type']})" for c in model.get("components", []) if c["type"] not in COMPONENTS]
    out = [f"// {base.HEADER_LINE}\n"]
    if notes:
        out.append("// Für Java Swing nicht erzeugt: " + ", ".join(notes) + "\n")
    out.append("import java.awt.*;\nimport javax.swing.*;\n\n")
    out.append(f"public abstract class {base_name} extends JFrame {{\n")
    out += [f"    protected {typ} {n};\n" for typ, n in ctx.fields]
    out.append("\n    protected void setupUi() {\n")
    out += [line + "\n" for line in ctx.lines]
    out.append("    }\n")
    for m, params in ctx.handlers.items():
        out.append(f"\n    /** Ereignis – in {comp} überschreiben. */\n    protected void {m}({params}) {{\n    }}\n")
    for c in model.get("components", []):
        out.append(component_method(c))
    if ctx.docs:
        out.append("\n    private static void onTextChanged(javax.swing.text.JTextComponent c, Runnable r) {\n"
                   "        c.getDocument().addDocumentListener(new javax.swing.event.DocumentListener() {\n"
                   "            public void insertUpdate(javax.swing.event.DocumentEvent e) { r.run(); }\n"
                   "            public void removeUpdate(javax.swing.event.DocumentEvent e) { r.run(); }\n"
                   "            public void changedUpdate(javax.swing.event.DocumentEvent e) { r.run(); }\n"
                   "        });\n    }\n")
    out.append("}\n")
    return "".join(out)


def user_source(comp: str, base_name: str) -> str:
    return (f"public class {comp} extends {base_name} {{\n    public {comp}() {{\n        setupUi();\n    }}\n\n"
            f"    public static void main(String[] args) {{\n        javax.swing.SwingUtilities.invokeLater(() -> new {comp}().setVisible(true));\n    }}\n}}\n")


def write(form_path: Path, model: dict) -> Path:
    stem = form_path.name[: -len(".form.json")]
    comp, base_name = names(stem)
    (form_path.parent / f"{base_name}.java").write_text(base_source(model, comp, base_name), encoding="utf-8")
    user = form_path.parent / f"{comp}.java"
    if not user.exists():
        user.write_text(user_source(comp, base_name), encoding="utf-8")
    return user


def add_handler(user_file: Path, handler: str, params: str) -> int:
    text = user_file.read_text(encoding="utf-8")
    pat = re.compile(rf"\bvoid\s+{re.escape(handler)}\s*\(")
    if not pat.search(text):
        stub = f"\n    @Override\n    protected void {handler}({params}) {{\n    }}\n"
        i = text.rstrip().rfind("}")
        text = text[:i].rstrip("\n") + "\n" + stub + text[i:]
        user_file.write_text(text, encoding="utf-8")
    return text[: pat.search(text).start()].count("\n") + 1
