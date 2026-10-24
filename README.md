# Visual Death Studio

Native Qt-IDE (PySide6) mit Neon-Oberfläche, visuellem Formular-Designer, Debugger, IntelliSense und Claude-Anbindung.
Inspiriert von Visual Studio, aber mit eigenem Design.

![Formular-Designer](docs/designer.png)

![Code-Editor](docs/editor.png)

## Funktionen

- **Formular-Designer** mit Toolbox (48 Steuerelemente in 7 Kategorien, Suche, A–Z-Liste; Dialoge wie Datei öffnen/speichern, Ordner, Farbe, Schrift, Drucken, Druckvorschau, MessageBox als Komponentenleiste), Eigenschaften, Farben und Schriften; erzeugt PySide6-Code
- **Verschachtelung und Layouts** im Designer: Controls in GroupBox, Panel und TabWidget ziehen, Layouts (vertikal, horizontal, Raster) für Formular und Container
- **Sprachabhängige Codeausschnitte** in der Toolbox (Python, Node, TypeScript, C, C++, C#, Rust, Go, Java, Bash)
- **Editor** mit Syntax-Hervorhebung, IntelliSense per LSP (pylsp, clangd) und optionaler Claude-Vervollständigung
- **Debugger** für Python, C/C++ (gdb), Node, Java, Go (dlv) und C# (netcoredbg) mit Haltepunkten, Variablen, Überwachung, Aufrufliste und Direktfenster
- **Test-Explorer** für pytest, unittest, node:test, Go, Cargo und dotnet
- **Refactorings**: Umbenennen, Verweise suchen, Formatieren, Quick Actions
- **Erstellen** erkennt CMake, Make, Cargo, Go, .NET, Maven, Gradle und npm; eigene Build-/Clean-Befehle und weitere Einstellungen unter Projekt → Eigenschaften
- **Projekt-Assistent** inklusive „Mit Claude erstellen“
- **Claude-Chat**, Diff-/Review-Ansicht, Git-Änderungen, Paket-Manager, Terminal

## Installation

    git clone https://github.com/peter1965p/visual-death-studio.git
    cd visual-death-studio
    ./install.sh

Das Skript legt eine virtuelle Python-Umgebung an, installiert die Abhängigkeiten, erzeugt den Starter `visual-death-studio`
(in `~/.local/bin`) und einen Eintrag im Anwendungsmenü. Es braucht Python 3.10+ und keine Administratorrechte; am Ende zeigt es,
welche optionalen Werkzeuge (Compiler, Debugger, Sprachserver) fehlen. `./install.sh --help` listet die Optionen.

Entfernen: `./uninstall.sh` (löscht Starter, Menüeintrag und die vom Skript angelegte Umgebung; mit `--purge` auch die Einstellungen,
Projekte bleiben unberührt).

Ohne Skript: `python -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/python run.py`.

Compiler, Debugger und Sprachserver (gcc, gdb, clangd, node, go, dlv, java, dotnet, …) werden nicht mitgeliefert; die
jeweilige Funktion ist verfügbar, sobald das Werkzeug installiert ist. Die Claude-Funktionen benötigen die lokale
`claude`-CLI.

## Tests

    venv/bin/pip install -r requirements-dev.txt
    QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests

## Lizenz

MIT, siehe [LICENSE](LICENSE).
