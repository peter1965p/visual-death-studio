"""Prompts für Projekterstellung und Chat."""
import re
from pathlib import Path

from ..projects.maui_gtk import GTK_VERSION

SYSTEM_PROJECT = (
    "Du arbeitest im Projekt-Assistenten von Visual Death Studio, einer Qt-IDE. Arbeite ausschließlich im aktuellen "
    "Arbeitsverzeichnis. Erstelle kleine, sofort lauffähige Projekte mit sinnvoller Struktur und kurzen Kommentaren, wo sie "
    "helfen. Du hast keine Shell: installiere nichts und führe nichts aus. Grafische Python-Oberflächen baust du mit PySide6. "
    "Beende deine Antwort mit einer kurzen deutschen Zusammenfassung (was wurde angelegt, wie startet man es) und als "
    "allerletzte Zeile exakt: MAIN: <relativer Pfad der Hauptdatei>"
)
SYSTEM_APP = SYSTEM_PROJECT.replace("Erstelle kleine, sofort lauffähige Projekte mit sinnvoller Struktur", "Baue eine vollständige, sofort lauffähige Anwendung mit sauberer Struktur")
SYSTEM_CHAT = (
    "Du bist der eingebaute Assistent der IDE Visual Death Studio. Das Arbeitsverzeichnis ist das geöffnete Projekt. "
    "Antworte knapp auf Deutsch. Ändere Dateien direkt mit deinen Werkzeugen, statt Code nur im Chat zu zeigen, "
    "wenn der Nutzer eine Änderung möchte."
)

LANG_HINTS = {
    "Automatisch (Claude entscheidet)": "",
    "Python": "Sprache: Python (Konsole).",
    "Python – Qt-Fensteranwendung (PySide6)": "Sprache/Framework: Python mit PySide6 (grafische Oberfläche), mit requirements.txt.",
    "Python – Web-API (FastAPI)": "Sprache/Framework: Python mit FastAPI und Uvicorn, mit requirements.txt.",
    "C": "Sprache: C (eine oder wenige Dateien, mit gcc baubar).",
    "C++": "Sprache: C++20 (mit g++ baubar).",
    "C#": "Sprache: C# (.NET 10, Top-Level-Anweisungen in Program.cs, per 'dotnet run Program.cs' startbar).",
    "C# – .NET MAUI (Android/iOS/Windows/macOS)": "Sprache/Framework: C# mit .NET MAUI (net10.0, XAML-Seiten, Code-Behind). Lege ein vollständiges Projekt an: <Name>.csproj mit UseMaui, "
        "MauiProgram.cs, App.xaml(.cs), AppShell.xaml(.cs), MainPage.xaml(.cs) und Platforms/Android (AndroidManifest.xml, MainActivity.cs, MainApplication.cs). "
        "Hinweis: Offizielle Zielplattformen sind Android, iOS, Windows und macOS; für den Linux-Desktop gibt es nur das experimentelle GTK4-Backend (Vorschau).",
    "C# – .NET MAUI für Linux (GTK4, experimentell)": "Sprache/Framework: C# mit .NET MAUI auf dem Linux-Desktop über das GTK4-Backend (NuGet 'Microsoft.Maui.Platforms.Linux.Gtk4' "
        f"{GTK_VERSION}, optional '...Gtk4.Essentials'). Kein Workload. Projektaufbau: <Name>.csproj (net10.0, OutputType Exe, PackageReference), Program.cs "
        "(Klasse Program : GtkMauiApplication mit CreateMauiApp und Main → app.Run(args)), MauiProgram.cs (MauiApp.CreateBuilder().UseMauiAppLinuxGtk4<App>(); "
        "optional builder.AddLinuxGtk4Essentials()), App.cs (Application mit CreateWindow) und Seiten in reinem C# (ContentPage, ohne XAML). Start mit 'dotnet run'.",
    "Rust": "Sprache: Rust (Cargo-Projekt).",
    "Go": "Sprache: Go (go.mod + main.go).",
    "JavaScript (Node.js)": "Sprache: JavaScript für Node.js (package.json).",
    "Java": "Sprache: Java (per 'java Main.java' startbar).",
    "Bash": "Sprache: Bash-Skript.",
}


def project_prompt(name: str, description: str, lang_hint: str = "", template: str | None = None, files: list | None = None) -> str:
    if template:
        return (f"Das Projekt '{name}' wurde aus der Vorlage '{template}' erzeugt (vorhandene Dateien: {', '.join(files or [])}). "
                f"Passe und erweitere es nach dieser Beschreibung des Nutzers:\n\n{description.strip()}")
    return f"Erstelle das Projekt '{name}'. {lang_hint}\n\nBeschreibung des Nutzers:\n{description.strip()}"


def parse_main(result: str, root: Path) -> Path | None:
    m = re.findall(r"^\s*MAIN:\s*(.+?)\s*$", result, re.M)
    if m:
        p = root / m[-1].strip("`'\" ")
        if p.is_file():
            return p
    for cand in ("Form1.form.json", "main.py", "main.c", "main.cpp", "index.js", "Program.cs", "src/main.rs", "main.go", "Main.java", "main.sh"):
        if (root / cand).is_file():
            return root / cand
    return None
