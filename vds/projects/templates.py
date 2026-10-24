"""Projektvorlagen und Projekterzeugung. Platzhalter __NAME__ wird durch den Projektnamen ersetzt."""
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..designer import codegen
from .java_templates import SPRING_FILES
from .maui_gtk import maui_gtk_files
from .web_templates import ANGULAR_FILES, DEV, NEXT_FILES, NUXT_FILES, PHP_CONSOLE, PHP_WEB, REACT_FILES, VUE_FILES

GITIGNORE = {
    "python": ".venv/\n__pycache__/\n*.pyc\n.env\n.vds/\n",
    "node": "node_modules/\n.vds/\n",
    "default": ".vds/\n*.o\n*.out\ntarget/\nbin/\nobj/\n",
}


@dataclass
class Template:
    id: str
    name: str
    description: str
    lang: str                    # Anzeigename der Sprache
    lang_id: str                 # Schlüssel für Farbe/Kürzel
    kind: str                    # Projekttyp (Filter)
    files: object = field(default_factory=dict)   # dict oder Funktion(optionen) -> dict
    main: str = ""               # Datei, die nach dem Erstellen geöffnet wird
    options: tuple = ("git", "readme")   # git | readme | venv
    qt_form: bool = False
    tags: tuple = ()
    form_target: str = ""        # Designer-Ziel des Start-Formulars (java-swing | react | vue); leer = keins
    form_dir: str = ""           # Ordner des Formulars relativ zum Projekt (z. B. src, components)
    settings: dict = field(default_factory=dict)   # Vorbelegung für .vds/project.json (z. B. run_cmd)


PY_CONSOLE = 'def main() -> None:\n    print("Hallo, __NAME__!")\n\n\nif __name__ == "__main__":\n    main()\n'
FASTAPI = '''from fastapi import FastAPI

app = FastAPI(title="__NAME__")


@app.get("/")
def root():
    return {"message": "Hallo, __NAME__!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
'''

CSPROJ_MAUI = """<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFrameworks>net10.0-android</TargetFrameworks>
    <TargetFrameworks Condition="$([MSBuild]::IsOSPlatform('windows'))">$(TargetFrameworks);net10.0-windows10.0.19041.0</TargetFrameworks>
    <TargetFrameworks Condition="$([MSBuild]::IsOSPlatform('osx'))">$(TargetFrameworks);net10.0-ios;net10.0-maccatalyst</TargetFrameworks>
    <OutputType>Exe</OutputType>
    <RootNamespace>__ID__</RootNamespace>
    <UseMaui>true</UseMaui>
    <SingleProject>true</SingleProject>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <ApplicationTitle>__NAME__</ApplicationTitle>
    <ApplicationId>com.companyname.__IDLOWER__</ApplicationId>
    <ApplicationDisplayVersion>1.0</ApplicationDisplayVersion>
    <ApplicationVersion>1</ApplicationVersion>
    <SupportedOSPlatformVersion Condition="'$(TargetFramework)' == 'net10.0-android'">21.0</SupportedOSPlatformVersion>
  </PropertyGroup>

</Project>
"""
XMLNS = 'xmlns="http://schemas.microsoft.com/dotnet/2021/maui" xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"'
MAUI_FILES = {
    "__NAME__.csproj": CSPROJ_MAUI,
    "MauiProgram.cs": "namespace __ID__;\n\npublic static class MauiProgram\n{\n    public static MauiApp CreateMauiApp()\n    {\n"
                      "        var builder = MauiApp.CreateBuilder();\n        builder.UseMauiApp<App>();\n        return builder.Build();\n    }\n}\n",
    "App.xaml": f'<?xml version="1.0" encoding="UTF-8" ?>\n<Application {XMLNS}\n             x:Class="__ID__.App">\n</Application>\n',
    "App.xaml.cs": "namespace __ID__;\n\npublic partial class App : Application\n{\n    public App()\n    {\n        InitializeComponent();\n    }\n\n"
                   "    protected override Window CreateWindow(IActivationState? activationState) => new Window(new AppShell());\n}\n",
    "AppShell.xaml": f'<?xml version="1.0" encoding="UTF-8" ?>\n<Shell {XMLNS}\n       xmlns:local="clr-namespace:__ID__"\n       x:Class="__ID__.AppShell"\n       Title="__NAME__">\n'
                     '    <ShellContent Title="Start" ContentTemplate="{DataTemplate local:MainPage}" Route="MainPage" />\n</Shell>\n',
    "AppShell.xaml.cs": "namespace __ID__;\n\npublic partial class AppShell : Shell\n{\n    public AppShell()\n    {\n        InitializeComponent();\n    }\n}\n",
    "MainPage.xaml": f'<?xml version="1.0" encoding="utf-8" ?>\n<ContentPage {XMLNS}\n             x:Class="__ID__.MainPage">\n'
                     '    <VerticalStackLayout Padding="30" Spacing="20" VerticalOptions="Center">\n'
                     '        <Label Text="Hallo, __NAME__!" FontSize="28" HorizontalOptions="Center" />\n'
                     '        <Label x:Name="CounterLabel" Text="Noch nicht geklickt" HorizontalOptions="Center" />\n'
                     '        <Button Text="Klick mich" Clicked="OnCounterClicked" HorizontalOptions="Center" />\n'
                     '    </VerticalStackLayout>\n</ContentPage>\n',
    "MainPage.xaml.cs": "namespace __ID__;\n\npublic partial class MainPage : ContentPage\n{\n    int count;\n\n    public MainPage()\n    {\n        InitializeComponent();\n    }\n\n"
                        "    void OnCounterClicked(object? sender, EventArgs e)\n    {\n        count++;\n        CounterLabel.Text = $\"Geklickt: {count}\";\n    }\n}\n",
    "Platforms/Android/AndroidManifest.xml": '<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
                     '    <application android:allowBackup="true" android:supportsRtl="true"></application>\n'
                     '    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />\n    <uses-permission android:name="android.permission.INTERNET" />\n</manifest>\n',
    "Platforms/Android/MainActivity.cs": "using Android.App;\nusing Android.Content.PM;\n\nnamespace __ID__;\n\n"
                     "[Activity(Theme = \"@style/Maui.SplashTheme\", MainLauncher = true, LaunchMode = LaunchMode.SingleTop,\n"
                     "    ConfigurationChanges = ConfigChanges.ScreenSize | ConfigChanges.Orientation | ConfigChanges.UiMode | ConfigChanges.ScreenLayout | ConfigChanges.SmallestScreenSize | ConfigChanges.Density)]\n"
                     "public class MainActivity : MauiAppCompatActivity\n{\n}\n",
    "Platforms/Android/MainApplication.cs": "using Android.App;\nusing Android.Runtime;\n\nnamespace __ID__;\n\n[Application]\npublic class MainApplication : MauiApplication\n{\n"
                     "    public MainApplication(IntPtr handle, JniHandleOwnership ownership) : base(handle, ownership)\n    {\n    }\n\n"
                     "    protected override MauiApp CreateMauiApp() => MauiProgram.CreateMauiApp();\n}\n",
}

TEMPLATES = [
    Template("claude", "Mit Claude erstellen", "Beschreibe dein Projekt in eigenen Worten – Claude legt Struktur und Code an.",
             "Beliebig", "claude", "KI", {}, "", ("git",)),
    Template("py-console", "Python-Konsolenanwendung", "Ein Python-Programm, das in der Konsole läuft.",
             "Python", "python", "Konsole", {"main.py": PY_CONSOLE, "requirements.txt": ""}, "main.py", ("git", "readme", "venv")),
    Template("py-qt", "Python-Fensteranwendung (Qt, mit Formular-Designer)",
             "Eine PySide6-Anwendung mit visuellem Formular (Form1) – Controls per Drag & Drop platzieren.",
             "Python", "python", "Desktop", {"requirements.txt": "PySide6\n"}, "Form1.form.json", ("git", "readme", "venv"), qt_form=True),
    Template("react-vite", "React + TypeScript (Vite, mit Designer)",
             "React-App mit Vite und TypeScript; die Seite Form1 baust du im Designer (Ausgabe als .tsx-Komponente). Start: F5 (npm install + npm run dev).",
             "TypeScript", "typescript", "Web", REACT_FILES, "src/Form1.form.json", ("git", "readme"), form_target="react", form_dir="src", settings={"run_cmd": DEV}),
    Template("vue-vite", "Vue 3 + TypeScript (Vite, mit Designer)",
             "Vue-3-App mit Vite und TypeScript; Form1 entsteht im Designer als .vue-Komponente. Start: F5 (npm install + npm run dev).",
             "TypeScript", "vue", "Web", VUE_FILES, "src/Form1.form.json", ("git", "readme"), form_target="vue", form_dir="src", settings={"run_cmd": DEV}),
    Template("next", "Next.js (App Router, TypeScript, mit Designer)",
             "Next.js-App mit App Router; Form1 (Designer) liegt in components/ und wird auf der Startseite eingebunden. Start: F5.",
             "TypeScript", "typescript", "Web", NEXT_FILES, "components/Form1.form.json", ("git", "readme"), form_target="react", form_dir="components",
             settings={"run_cmd": DEV}),
    Template("nuxt", "Nuxt 3 (Vue, TypeScript, mit Designer)",
             "Nuxt-3-App; Form1 (Designer) liegt in components/ und wird automatisch importiert. Start: F5.",
             "TypeScript", "vue", "Web", NUXT_FILES, "components/Form1.form.json", ("git", "readme"), form_target="vue", form_dir="components", settings={"run_cmd": DEV}),
    Template("angular", "Angular (eigenständige Komponenten, TypeScript, mit Designer)",
             "Angular-App mit Standalone-Komponenten; Form1 (Designer) liegt in src/app und wird in der App-Komponente eingebunden. Start: F5 (npm start).",
             "TypeScript", "typescript", "Web", ANGULAR_FILES, "src/app/Form1.form.json", ("git", "readme"), form_target="angular", form_dir="src/app",
             settings={"run_cmd": "[ -d node_modules ] || npm install; npm start"}),
    Template("java-swing", "Java-Fensteranwendung (Swing, mit Designer)",
             "Swing-Fenster mit visuellem Formular (Form1): Controls und Layouts im Designer, Ereignisse als überschreibbare Methoden. Start: F5 (java Form1.java).",
             "Java", "java", "Desktop", {}, "Form1.form.json", ("git", "readme"), form_target="java-swing"),
    Template("java-spring", "Java-Webanwendung (Spring Boot, Maven)",
             "Spring-Boot-REST-Anwendung mit Beispiel-Controller, Test und Startseite. Maven wird über das mitgelieferte Skript ./mvnw bei Bedarf selbst geladen (nur ein JDK nötig). "
             "Start: F5, Adresse http://localhost:8080.",
             "Java", "java", "Web", SPRING_FILES, "src/main/java/com/example/__IDLOWER__/HelloController.java", ("git", "readme"),
             settings={"run_cmd": "./mvnw spring-boot:run"}),
    Template("php-console", "PHP-Skript (Konsole)", "Ein PHP-Skript, das mit dem PHP-Interpreter läuft.", "PHP", "php", "Konsole",
             {"main.php": PHP_CONSOLE}, "main.php"),
    Template("php-web", "PHP-Webanwendung (eingebauter Server)", "Kleine PHP-Seite mit Formular; Start über den eingebauten PHP-Server (F5, Adresse http://127.0.0.1:8000).",
             "PHP", "php", "Web", PHP_WEB, "public/index.php", ("git", "readme"), settings={"run_cmd": "php -S 127.0.0.1:8000 -t public"}),
    Template("py-fastapi", "Python-Web-API (FastAPI)", "Eine kleine REST-API mit FastAPI und Uvicorn.",
             "Python", "python", "Web", {"main.py": FASTAPI, "requirements.txt": "fastapi\nuvicorn[standard]\n"}, "main.py", ("git", "readme", "venv")),
    Template("c-console", "C-Konsolenanwendung", "Ein C-Programm mit main().", "C", "c", "Konsole",
             {"main.c": '#include <stdio.h>\n\nint main(void) {\n    printf("Hallo, __NAME__!\\n");\n    return 0;\n}\n'}, "main.c"),
    Template("cpp-console", "C++-Konsolenanwendung", "Ein C++20-Programm mit iostream.", "C++", "cpp", "Konsole",
             {"main.cpp": '#include <iostream>\n\nint main() {\n    std::cout << "Hallo, __NAME__!" << std::endl;\n    return 0;\n}\n'}, "main.cpp"),
    Template("cs-console", "C#-Konsolenanwendung", "Ein C#-Programm mit Top-Level-Anweisungen.", "C#", "csharp", "Konsole",
             {"Program.cs": 'Console.WriteLine("Hallo, __NAME__!");\n'}, "Program.cs"),
    Template("cs-maui", ".NET MAUI-App (C#, XAML)",
             "Mobile/Desktop-App für Android, iOS, Windows und macOS. Unter Linux braucht der Android-Build den Workload maui-android; Linux-Desktop nur über ein experimentelles GTK4-Backend.",
             "C#", "csharp", "Mobil", MAUI_FILES, "MainPage.xaml.cs", ("git", "readme")),
    Template("cs-maui-gtk", ".NET MAUI-App für Linux (GTK4, experimentell)",
             "Echte MAUI-App für den Linux-Desktop über das GTK4-Backend von dotnet/maui-labs – ohne Workload, per 'dotnet run'.",
             "C#", "csharp", "Desktop", maui_gtk_files, "MainPage.cs", ("git", "readme", "essentials")),
    Template("rust-console", "Rust-Anwendung (Cargo)", "Ein Cargo-Projekt mit src/main.rs.", "Rust", "rust", "Konsole",
             {"Cargo.toml": '[package]\nname = "__NAME__"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n',
              "src/main.rs": 'fn main() {\n    println!("Hallo, __NAME__!");\n}\n'}, "src/main.rs"),
    Template("go-console", "Go-Anwendung", "Ein Go-Modul mit main.go.", "Go", "go", "Konsole",
             {"go.mod": "module __NAME__\n\ngo 1.22\n",
              "main.go": 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hallo, __NAME__!")\n}\n'}, "main.go"),
    Template("node-console", "Node.js-Anwendung", "Ein Node.js-Projekt mit package.json.", "JavaScript", "javascript", "Konsole",
             {"index.js": 'console.log("Hallo, __NAME__!");\n',
              "package.json": '{\n  "name": "__NAME__",\n  "version": "1.0.0",\n  "main": "index.js",\n  "scripts": { "start": "node index.js" }\n}\n'},
             "index.js"),
    Template("java-console", "Java-Konsolenanwendung", "Ein Java-Programm (Single-File-Start).", "Java", "java", "Konsole",
             {"Main.java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hallo, __NAME__!");\n    }\n}\n'}, "Main.java"),
    Template("sh-script", "Bash-Skript", "Ein ausführbares Shell-Skript.", "Bash", "shell", "Konsole",
             {"main.sh": '#!/usr/bin/env bash\nset -euo pipefail\n\necho "Hallo, __NAME__!"\n'}, "main.sh"),
    Template("empty", "Leeres Projekt", "Ein leerer Ordner – Dateien fügst du selbst hinzu.", "Beliebig", "", "Sonstige",
             {}, "", ("git", "readme")),
]
BY_ID = {t.id: t for t in TEMPLATES}


def _ignore_for(t: Template) -> str:
    if t.lang_id == "python":
        return GITIGNORE["python"]
    if t.lang_id in ("javascript", "typescript", "vue"):
        return GITIGNORE["node"] + "dist/\n.next/\n.nuxt/\n.output/\n*.tsbuildinfo\n"
    if t.lang_id == "php":
        return GITIGNORE["default"] + "vendor/\n"
    return GITIGNORE["default"]


def _qt_demo(root: Path):
    model = codegen.new_form("Form1")
    model["title"] = "Form1"
    model["controls"] = [
        {"type": "Label", "name": "label1", "x": 40, "y": 40, "w": 240, "h": 24, "props": {"text": "Hallo aus __NAME__!", "enabled": True, "visible": True, "tooltip": "", "font_size": 12}},
        {"type": "Button", "name": "button1", "x": 40, "y": 88, "w": 120, "h": 32, "props": {"text": "Klick mich", "enabled": True, "visible": True, "tooltip": "", "font_size": 0}},
    ]
    user = codegen.write_files(root / "Form1.form.json", model)
    codegen.add_handler(user, "button1_clicked", [])
    user.write_text(user.read_text(encoding="utf-8").replace(
        "def button1_clicked(self):\n        pass", 'def button1_clicked(self):\n        self.label1.setText("Button geklickt!")'), encoding="utf-8")


def _demo_form(root: Path, t: Template, name: str):
    """Start-Formular (Label + Button) für Java Swing, React und Vue; Java bekommt gleich einen Ereignis-Handler."""
    from ..designer import targets
    model = codegen.new_form("Form1", t.form_target)
    model["title"] = name
    model["controls"] = [
        {"type": "Label", "name": "label1", "x": 16, "y": 16, "w": 260, "h": 24, "props": {"text": f"Hallo aus {name}!", "enabled": True, "visible": True, "tooltip": "", "font_size": 12}},
        {"type": "Button", "name": "button1", "x": 16, "y": 56, "w": 120, "h": 32, "props": {"text": "Klick mich", "enabled": True, "visible": True, "tooltip": "", "font_size": 0}},
    ]
    folder = root / t.form_dir
    folder.mkdir(parents=True, exist_ok=True)
    user = codegen.write_files(folder / "Form1.form.json", model)
    if t.form_target == "java-swing":
        h = targets.handler(model, model["controls"][1])
        targets.add_handler(user, model, *h)
        user.write_text(user.read_text(encoding="utf-8").replace(f"protected void {h[0]}() {{\n    }}", f'protected void {h[0]}() {{\n        label1.setText("Button geklickt!");\n    }}'),
                        encoding="utf-8")
        return [f"  + {p.name}" for p in (folder / "Form1.form.json", folder / "Form1Base.java", user)]
    return [f"  + {(folder / n).relative_to(root).as_posix()}" for n in ("Form1.form.json", user.name)]


def create_project(t: Template, name: str, location: Path, options: dict):
    """Legt <location>/<name> an. Rückgabe: (Projektordner, zu öffnende Datei|None, Protokollzeilen)."""
    root = location / name
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"'{root}' existiert bereits und ist nicht leer.")
    root.mkdir(parents=True, exist_ok=True)
    log = [f"Projekt '{name}' ({t.name}) wird in {root} erstellt…"]
    ident = re.sub(r"\W", "_", name)
    ident = ident if not ident[0].isdigit() else "_" + ident
    npm_name = re.sub(r"[^a-z0-9._-]", "-", name.lower()).strip("-.") or "app"
    fill = lambda x: x.replace("__NAME__", name).replace("__IDLOWER__", npm_name if t.lang_id in ("typescript", "vue", "javascript") else ident.lower()).replace("__ID__", ident)
    files = t.files(options) if callable(t.files) else t.files
    for rel, content in files.items():
        f = root / fill(rel)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(fill(content), encoding="utf-8")
        if content.startswith("#!"):
            f.chmod(0o755)                      # Skripte (z. B. mvnw) ausführbar
        log.append(f"  + {fill(rel)}")
    if t.qt_form:
        _qt_demo(root)
        for rel in ("Form1.form.json", "Form1_designer.py", "Form1.py"):
            text = (root / rel).read_text(encoding="utf-8")
            (root / rel).write_text(text.replace("__NAME__", name), encoding="utf-8")
        log += ["  + Form1.form.json", "  + Form1_designer.py", "  + Form1.py"]
    if t.form_target:
        log += _demo_form(root, t, name)
    if t.settings:
        from ..project import ProjectSettings
        ProjectSettings(**t.settings).save(root)
        log.append("  + .vds/project.json (Start-Befehl)")
    if options.get("readme"):
        (root / "README.md").write_text(f"# {name}\n\n{t.description}\n", encoding="utf-8")
        log.append("  + README.md")
    if options.get("git"):
        (root / ".gitignore").write_text(_ignore_for(t), encoding="utf-8")
        if shutil.which("git"):
            r = subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True, text=True)
            log.append("  Git-Repository initialisiert." if r.returncode == 0 else f"  git init fehlgeschlagen: {r.stderr.strip()}")
        else:
            log.append("  git ist nicht installiert – nur .gitignore angelegt.")
    if options.get("venv"):
        py = shutil.which("python3") or sys.executable
        r = subprocess.run([py, "-m", "venv", ".venv"], cwd=root, capture_output=True, text=True, timeout=180)
        log.append("  Virtuelle Umgebung .venv angelegt." if r.returncode == 0 else f"  venv fehlgeschlagen: {r.stderr.strip()}")
    log.append("Projekt erstellt.")
    main = root / fill(t.main) if t.main else None
    return root, main, log
