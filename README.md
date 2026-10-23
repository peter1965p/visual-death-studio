# Visual Death Studio

Native Qt-IDE (PySide6) mit Neon-Oberfläche, visuellem Formular-Designer, Debugger, IntelliSense und Claude-Anbindung.
Inspiriert von Visual Studio, aber mit eigenem Design.

![Formular-Designer](docs/designer.png)

![Code-Editor](docs/editor.png)

## Funktionen

- **Formular-Designer** mit Toolbox (36 Steuerelemente in 7 Kategorien, Suche, A–Z-Liste), Eigenschaften, Farben und Schriften; erzeugt PySide6-Code
- **Sprachabhängige Codeausschnitte** in der Toolbox (Python, Node, TypeScript, C, C++, C#, Rust, Go, Java, Bash)
- **Editor** mit Syntax-Hervorhebung, IntelliSense per LSP (pylsp, clangd) und optionaler Claude-Vervollständigung
- **Debugger** für Python, C/C++ (gdb), Node, Java, Go (dlv) und C# (netcoredbg) mit Haltepunkten, Variablen, Überwachung, Aufrufliste und Direktfenster
- **Test-Explorer** für pytest, unittest, node:test, Go, Cargo und dotnet
- **Refactorings**: Umbenennen, Verweise suchen, Formatieren, Quick Actions
- **Projekt-Assistent** inklusive „Mit Claude erstellen“
- **Claude-Chat**, Diff-/Review-Ansicht, Git-Änderungen, Paket-Manager, Terminal

## Installation

    git clone https://github.com/peter1965p/visual-death-studio.git
    cd visual-death-studio
    python -m venv venv && venv/bin/pip install -r requirements.txt
    venv/bin/python run.py

Optional: `venv/bin/python run.py --install-desktop` legt einen Starter im Anwendungsmenü an.

Compiler, Debugger und Sprachserver (gcc, gdb, clangd, node, go, dlv, java, dotnet, …) werden nicht mitgeliefert; die
jeweilige Funktion ist verfügbar, sobald das Werkzeug installiert ist. Die Claude-Funktionen benötigen die lokale
`claude`-CLI.

## Tests

    venv/bin/pip install -r requirements-dev.txt
    QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests

## Lizenz

MIT, siehe [LICENSE](LICENSE).
