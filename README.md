# Visual Death Studio

Native Qt-IDE (PySide6) mit dunkler, von Visual Studio inspirierter Oberfläche, visuellem Formular-Designer, Projekt-Assistent und Claude-Anbindung.

    python -m venv venv && venv/bin/pip install -r requirements.txt
    venv/bin/python run.py

Stand: Docks (Toolbox, Explorer, Eigenschaften, Ausgabe, Fehlerliste, Terminal, Haltepunkte), Editor mit
Pygments-Highlighting, Build/Run für Python, C, C++, C#, Rust, Go, Node, Java, Bash (je nach installierter Toolchain),
Fehlerliste aus Compilerausgaben, PTY-Terminal. Offen: LSP-Client, Debugger (DAP).
