# Visual Death Studio

Native Qt-IDE (PySide6) mit Neon-Oberfläche, visuellem Formular-Designer, Debugger, IntelliSense und Claude-Anbindung.
Inspiriert von Visual Studio, aber mit eigenem Design.

![Formular-Designer](docs/designer.png)

![Code-Editor](docs/editor.png)

Startseite und Web-Vorschau mit einer fertig gebauten Laravel-Unternehmensseite (Projekt aus „Fertige Anwendungen“, F5 startet den Server):

![Startseite und Web-Vorschau](docs/web-vorschau.png)

## Funktionen

- **Formular-Designer** mit Toolbox (48 Steuerelemente in 7 Kategorien, Suche, A–Z-Liste; Dialoge wie Datei öffnen/speichern, Ordner, Farbe, Schrift, Drucken, Druckvorschau, MessageBox als Komponentenleiste), Eigenschaften, Farben und Schriften; erzeugt PySide6-Code
- **Verschachtelung und Layouts** im Designer: Controls in GroupBox, Panel und TabWidget ziehen, Layouts (vertikal, horizontal, Raster) für Formular und Container
- **Designer für mehrere Plattformen:** dasselbe Formular (Controls, Verschachtelung, Layouts) als **Python/Qt**, **Java Swing**, **React (TSX)**, **Vue 3** oder **Angular** ausgeben; Layouts werden zu Flex/Grid-CSS bzw. Swing-Layout-Managern, Ereignisse zu Props/Emits bzw. überschreibbaren Java-Methoden
- **Web-Vorschau für jedes Webprojekt** (Vite-Projekte mit React oder Vue, Angular, Next, Nuxt, PHP – alles, was einen Dev-Server mit Browser-Adresse hat): eingebetteter Browser, öffnet sich selbst, sobald ein Dev-Server seine Adresse meldet; Geräte-Größen, Zoom, Konsolenfehler in der Fehlerliste
  - **Elemente anklicken** (⌖): Details, Eltern/Kind-Navigation, „Zum Code springen“ (id, Klassen, Text werden im Projekt gesucht; Elemente aus Designer-Seiten öffnen direkt das Formular)
  - **Visuell bearbeiten** (✥): verschieben, Größe per Griff, Pfeiltasten zum Feinjustieren (Umschalt = 10 px), Text per Doppelklick, Stile (Farbe, Schrift, Abstand, Rahmen …) live im Inspektor
  - **Visueller Web-Editor** (Ansicht → Strg+Alt+V): eigene Ansicht nur mit großer Web-Vorschau und Web-Element nebeneinander, Bearbeiten ist gleich an; nochmal Strg+Alt+V stellt das Layout wieder her
  - **Gemeinsame Klassen**: Regeln, die mehrere Elemente der Seite treffen (z. B. `.btn-lg`), werden nur als letzte Wahl angeboten (mit „gilt für n Elemente“); Verschieben landet als Inline-Style oder eigene Regel nur für das gewählte Element
  - **Texte aus Laravel-Einstellungen** (`{{ Setting::get('schluessel') }}`): steht der Text nicht im Quelltext, bietet die IDE an, den Wert in der Datenbank zu ändern (mit Vorschau und Rückgängig); PHP startet dafür die Anwendung kurz im Projektordner
  - **In den Quellcode übernehmen** (Knopf „💾 In Quellcode speichern (n)“ unten in der Vorschau, oder Strg+Alt+S; neue Regeln landen im Stylesheet, das die Seite wirklich lädt, z. B. `public/css/app.css` bei Laravel; offene Editor-Tabs werden vorher gesichert und danach nachgeladen, die Vorschau lädt neu): die IDE zeigt die Möglichkeiten mit Unterschied (bestehende CSS-Regel, Tailwind-Klassen, Inline-Style, neue Regel) – erst nach deiner Bestätigung wird geschrieben, mit „Rückgängig“
- **Fertige Anwendungen** (Neues Projekt → „Fertige Anwendung“): Anwendung × Technik frei kombinieren – CMS, Online-Shop, Unternehmens-Website (mit Laravel, Spring Boot, React, Vue, Next, Nuxt oder Angular), Datenbank-App im Access-Stil, Dateimanager, Webbrowser (Qt bzw. Swing). Claude baut sie auf dem Grundgerüst auf; der Auftrag ist vorbelegt und änderbar. Der Assistent erledigt den Rest selbst: legt das `.venv` an, installiert die Pakete, prüft den Code (Python: Syntax und Importe, PHP: `php -l`, bei Laravel zusätzlich Datenbank-Einrichtung und Tests – SQLite wird dafür bei Bedarf per Projekt-ini zugeschaltet, ohne die `php.ini` anzufassen –, Swing: `javac`) und lässt Claude gefundene Fehler bis zu zweimal korrigieren
- **Projekt importieren** (Datei → Projekt importieren, Strg+Alt+I): Qt Creator (`.pro` per qmake, CMake-Projekte), Visual Studio (`.sln`, `.csproj`, `.vcxproj` – C++ wird über eine abgeleitete CMake-Datei unter `.vds/import/` gebaut), Code::Blocks (`.cbp`), IntelliJ (`.iml`), Eclipse (`.project`, Java wird mit `javac` gebaut), Swift Package, Xcode (nur zum Bearbeiten, gebaut wird unter macOS), Maven, Gradle. Das Projekt bleibt an seinem Ort; die IDE trägt nur Build- und Startbefehl ein (F5 baut und startet), eigene Einträge bleiben erhalten
- **Projekt exportieren** (Strg+Alt+E): für Qt Creator (`CMakeLists.txt` bzw. `.pyproject`), Visual Studio (`.sln` bzw. CMake-Ordner), VS Code (`tasks.json`, `launch.json`), IntelliJ/PyCharm/CLion (`.idea`, `.iml`), Eclipse (`.project`, `.classpath`) oder als ZIP ohne `venv`, `node_modules`, `build` u. a.; vorhandene Dateien werden nie überschrieben
- **Befehlspalette und globale Suche** (Strg+Q; Strg+P Dateien, Strg+Umschalt+P Befehle, Strg+Umschalt+F Text in Dateien): Befehle, Dateien, Einstellungen und Textstellen mit unscharfer Suche; Präfixe `>` Befehle, `%` Text, `@` Einstellungen
- **Profiler** (Alt+F2): CPU-Zeit (cProfile) und Speicher (tracemalloc) für Python-Skripte, sortierbare Tabelle, Doppelklick springt zur Stelle im Code
- **Datenbank-Explorer** (Strg+Alt+B): SQLite (auch per Doppelklick auf `.db`/`.sqlite`), MySQL/MariaDB, PostgreSQL, ODBC über Qt SQL (die Client-Bibliotheken müssen installiert sein); Tabellen, Sichten, Spalten, SQL ausführen, Ergebnistabelle; Kennwörter werden nie gespeichert
- **Live Share** (Strg+Alt+J): Projekt über einen Code mit anderen teilen – der Gast erhält eine Kopie, Änderungen laufen live in beide Richtungen (optional nur lesen). Die Verbindung ist **unverschlüsselt**: nur im lokalen Netz oder per VPN nutzen; neue und gelöschte Dateien werden nicht übertragen
- **Automatische Updates:** VDS sucht beim Start (höchstens einmal am Tag, abschaltbar unter Extras → Optionen → Allgemein) und über Hilfe → Nach Updates suchen nach neuen GitHub-Releases. Bei einem Git-Klon (so legt `install.sh` die Installation an) genügt ein Klick auf »Jetzt aktualisieren«: Vorspulen auf das Release-Tag, Pakete aktualisieren, Neustart. Lokale Änderungen oder eigene Commits im Programmordner werden nie überschrieben – dann zeigt VDS nur die Release-Seite
- **Git** im Änderungen-Fenster: Commit, **Push**, Pull und Remote eintragen (Push/Pull laufen im Hintergrund, ohne Passwortabfrage – bei Anmeldeproblemen erklärt die IDE, wie SSH-Schlüssel oder `gh auth login` einzurichten sind)
- **Projektvorlagen** mit Designer: React + TypeScript (Vite), Vue 3 (Vite), Angular, Next.js, Nuxt 3, Java Swing, **Spring Boot** (Maven-Wrapper, nur ein JDK nötig), **Laravel** (per `composer create-project` im Assistenten); dazu PHP (Skript und Webanwendung mit eingebautem Server)
- **Start-Befehl** pro Projekt (z. B. `npm run dev`, `php -S …`): F5 startet den Dev-Server, Umschalt+F5 beendet ihn samt Kindprozessen
- **Sprachabhängige Codeausschnitte** in der Toolbox (Python, Node, TypeScript, C, C++, C#, Rust, Go, Java, Bash)
- **Editor** mit Syntax-Hervorhebung, IntelliSense per LSP (pylsp, clangd) und optionaler Claude-Vervollständigung
- **Debugger** für Python, C/C++ (gdb), Node, Java, Go (dlv) und C# (netcoredbg) mit Haltepunkten, Variablen, Überwachung, Aufrufliste und Direktfenster
- **Test-Explorer** für pytest, unittest, node:test, Go, Cargo und dotnet
- **Refactorings**: Umbenennen, Verweise suchen, Formatieren, Quick Actions
- **Erstellen** erkennt CMake, Make, Cargo, Go, .NET, Maven, Gradle und npm; eigene Build-/Clean-Befehle und weitere Einstellungen unter Projekt → Eigenschaften
- **Projekt-Assistent** inklusive „Mit Claude erstellen“
- **Claude-Chat und -Vervollständigung** wahlweise über die lokale Claude-Code-CLI **oder mit eigenem API-Schlüssel** (Extras → Optionen → Claude; Agent mit Dateiwerkzeugen im Projektordner, Modellwahl, Verbindungstest)
- **Startseite** (Strg+Umschalt+H, erscheint beim Start): zuletzt geöffnete Projekte mit erkanntem Typ (Laravel, Spring Boot, React, Vue, Angular, Python …), Schnellaktionen für neues Projekt, Ordner öffnen (Datei → Ordner schließen beendet das Projekt komplett, auch für den nächsten Start), Designer und Web-Vorschau
- **Farbschemata:** Neon (dunkel) und Hell
- **Optionen** (Strg+,): Editor (Tab-Breite, Zeilenumbruch, Leerraum, Autospeichern), IntelliSense, Designer-Raster, Claude-Anbieter, Export/Import
- Diff-/Review-Ansicht, Git-Änderungen, Paket-Manager, Terminal

## Installation

    git clone https://github.com/peter1965p/visual-death-studio.git
    cd visual-death-studio
    ./install.sh

Das Skript legt eine virtuelle Python-Umgebung an, installiert die Abhängigkeiten, erzeugt den Starter `visual-death-studio`
(in `~/.local/bin`) und einen Eintrag im Anwendungsmenü. Es braucht Python 3.10+ und keine Administratorrechte; am Ende zeigt es,
welche optionalen Werkzeuge (Compiler, Debugger, Sprachserver) fehlen. `./install.sh --help` listet die Optionen.

Laravel: im Assistenten „Laravel-Webanwendung“ wählen (oder `composer create-project laravel/laravel meine-app` und Ordner öffnen), F5 startet `php artisan serve`, die Vorschau öffnet sich selbst. (Für SQLite braucht PHP die Erweiterung `pdo_sqlite`; auf Arch: `php-sqlite`.)

Farbschema: Extras → Optionen → Allgemein (Neon dunkel oder Hell, wirkt nach einem Neustart).

Startbild abschalten: Extras → Optionen → Allgemein oder `--no-splash`.

Entfernen: `./uninstall.sh` (löscht Starter, Menüeintrag und die vom Skript angelegte Umgebung; mit `--purge` auch die Einstellungen,
Projekte bleiben unberührt).

Ohne Skript: `python -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/python run.py`.

Compiler, Debugger und Sprachserver (gcc, gdb, clangd, node, go, dlv, java, dotnet, …) werden nicht mitgeliefert; die
jeweilige Funktion ist verfügbar, sobald das Werkzeug installiert ist. Die Claude-Funktionen brauchen entweder die lokale
`claude`-CLI oder einen eigenen Anthropic-API-Schlüssel (Datenschutz: Dein Code geht in beiden Fällen an Anthropic; der Schlüssel liegt in einer
nur für dich lesbaren Datei im Konfigurationsordner, nie in den Optionen).

## Tests

    venv/bin/pip install -r requirements-dev.txt
    QT_QPA_PLATFORM=offscreen venv/bin/python -m pytest tests

## Lizenz

MIT, siehe [LICENSE](LICENSE).
