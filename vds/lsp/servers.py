"""Welche Sprachserver es je Sprache gibt und wie man sie installiert. Der erste installierte gewinnt.

Gesucht wird bewusst nur auf dem System, nicht im Projektordner: Sonst würde schon das Öffnen eines fremden Projekts ein Programm aus dessen node_modules starten."""
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..build import languages
from ..build.languages import Lang


@dataclass(frozen=True)
class Server:
    command: tuple
    install: str                      # Befehl oder Hinweis; mit sudo läuft er nicht ohne Passwort, siehe can_run_install


_NPM_TS = "npm i -g typescript typescript-language-server"
_NPM_WEB = "npm i -g vscode-langservers-extracted"
SERVERS = {
    "python": [Server(("pylsp",), "pip install python-lsp-server"), Server(("pyright-langserver", "--stdio"), "npm i -g pyright")],
    "php": [Server(("intelephense", "--stdio"), "npm i -g intelephense"), Server(("phpactor", "language-server"), "sudo pacman -S phpactor")],
    "javascript": [Server(("typescript-language-server", "--stdio"), _NPM_TS)],
    "typescript": [Server(("typescript-language-server", "--stdio"), _NPM_TS)],
    "javascriptreact": [Server(("typescript-language-server", "--stdio"), _NPM_TS)],
    "typescriptreact": [Server(("typescript-language-server", "--stdio"), _NPM_TS)],
    "c": [Server(("clangd",), "sudo pacman -S clang")],
    "cpp": [Server(("clangd",), "sudo pacman -S clang")],
    "csharp": [Server(("csharp-ls",), "dotnet tool install -g csharp-ls")],
    "rust": [Server(("rust-analyzer",), "sudo pacman -S rust-analyzer")],
    "go": [Server(("gopls",), "go install golang.org/x/tools/gopls@latest")],
    "java": [Server(("jdtls",), "yay -S jdtls")],
    "shell": [Server(("bash-language-server", "start"), "npm i -g bash-language-server")],
    "html": [Server(("vscode-html-language-server", "--stdio"), _NPM_WEB)],
    "css": [Server(("vscode-css-language-server", "--stdio"), _NPM_WEB)],
    "scss": [Server(("vscode-css-language-server", "--stdio"), _NPM_WEB)],
    "json": [Server(("vscode-json-language-server", "--stdio"), _NPM_WEB)],
    "yaml": [Server(("yaml-language-server", "--stdio"), "npm i -g yaml-language-server")],
    "dockerfile": [Server(("docker-langserver", "--stdio"), "npm i -g dockerfile-language-server-nodejs")],
    "svelte": [Server(("svelteserver", "--stdio"), "npm i -g svelte-language-server")],
    "ruby": [Server(("ruby-lsp",), "gem install ruby-lsp")],
    "lua": [Server(("lua-language-server",), "sudo pacman -S lua-language-server")],
    "dart": [Server(("dart", "language-server"), "yay -S flutter")],
    "zig": [Server(("zls",), "sudo pacman -S zls")],
    "toml": [Server(("taplo", "lsp", "stdio"), "cargo install taplo-cli --locked")],
    "cmake": [Server(("cmake-language-server",), "pip install cmake-language-server")],
}

# Nur für den Sprachserver bekannt; zum direkten Ausführen und für die Codeausschnitte bleibt languages.py zuständig.
_EXTRA = (("javascriptreact", "React (JSX)", (".jsx",)), ("typescriptreact", "React (TSX)", (".tsx",)), ("html", "HTML", (".html", ".htm")), ("css", "CSS", (".css",)),
          ("scss", "SCSS", (".scss",)), ("json", "JSON", (".json",)), ("yaml", "YAML", (".yaml", ".yml")), ("svelte", "Svelte", (".svelte",)), ("ruby", "Ruby", (".rb",)),
          ("lua", "Lua", (".lua",)), ("dart", "Dart", (".dart",)), ("zig", "Zig", (".zig",)), ("toml", "TOML", (".toml",)), ("dockerfile", "Dockerfile", ()), ("cmake", "CMake", (".cmake",)))
_BY_EXT = {ext: Lang(id_, name, exts, []) for id_, name, exts in _EXTRA for ext in exts}
_BLADE = Lang("blade", "Blade", (".blade.php",), [])
_BY_NAME = {"dockerfile": Lang("dockerfile", "Dockerfile", (), []), "cmakelists.txt": Lang("cmake", "CMake", (".cmake",), [])}


def lang_for(path: str | Path) -> Lang | None:
    """Sprache einer Datei aus Sicht des Sprachservers. Blade-Vorlagen sind kein PHP: Ein PHP-Server versteht sie nicht, sie bekommen nur die Vervollständigung aus Wörtern und Schlüsselwörtern."""
    p = Path(path)
    name = p.name.lower()
    if name.endswith(".blade.php"):
        return _BLADE
    return languages.lang_for(p) or _BY_NAME.get(name) or (_BY_NAME["dockerfile"] if name.startswith("dockerfile.") else None) or _BY_EXT.get(p.suffix.lower())


def choose(lang_id: str) -> Server | None:
    """Der erste installierte Sprachserver dieser Sprache."""
    return next((s for s in SERVERS.get(lang_id, ()) if shutil.which(s.command[0])), None)


def suggestion(lang_id: str) -> Server | None:
    """Der empfohlene Server zum Nachinstallieren."""
    return next(iter(SERVERS.get(lang_id, ())), None)


def can_run_install(server: Server) -> bool:
    """Darf die IDE den Installationsbefehl selbst ausführen? sudo und yay fragen nach Passwort oder Bestätigung und brauchen ein echtes Terminal."""
    return server.install.split()[0] in ("npm", "pip", "go", "dotnet", "cargo", "gem") and shutil.which(server.install.split()[0]) is not None
