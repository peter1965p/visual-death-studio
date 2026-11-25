"""Sucht externe Debugger (dlv, netcoredbg, gdb, jdb …) im PATH und an üblichen Orten; liefert Installationshinweise für CachyOS/Arch."""
import os
import re
import shutil
from pathlib import Path

HINTS = {
    "gdb": "sudo pacman -S gdb          (gdb 14 oder neuer)",
    "dlv": "sudo pacman -S go delve     (oder: go install github.com/go-delve/delve/cmd/dlv@latest)",
    "go": "sudo pacman -S go",
    "netcoredbg": "yay -S netcoredbg         (oder Release von github.com/Samsung/netcoredbg nach ~/.local/bin entpacken)",
    "jdb": "sudo pacman -S jdk-openjdk",
    "javac": "sudo pacman -S jdk-openjdk",
    "node": "sudo pacman -S nodejs",
    "dotnet": "sudo pacman -S dotnet-sdk",
    "php": "sudo pacman -S php",
    "composer": "sudo pacman -S composer",
    "npm": "sudo pacman -S npm",
    "pnpm": "sudo pacman -S pnpm",
    "yarn": "sudo pacman -S yarn",
    "cargo": "sudo pacman -S rust",
    "mvn": "sudo pacman -S maven",
    "gradle": "sudo pacman -S gradle",
    "cmake": "sudo pacman -S cmake",
    "ctest": "sudo pacman -S cmake",
    "meson": "sudo pacman -S meson",
    "make": "sudo pacman -S make",
    "just": "sudo pacman -S just",
    "docker": "sudo pacman -S docker docker-compose",
    "ruby": "sudo pacman -S ruby",
    "bundle": "sudo pacman -S ruby",
    "zig": "sudo pacman -S zig",
    "uv": "sudo pacman -S uv",
    "flutter": "yay -S flutter",
    "pre-commit": "sudo pacman -S pre-commit",
}


def search_dirs() -> list:
    home = Path.home()
    extra = [home / "go" / "bin", home / ".local" / "bin", home / ".local" / "share" / "visual-death-studio" / "tools" / "bin", home / ".dotnet" / "tools",
             home / ".cargo" / "bin", home / ".bun" / "bin", home / ".deno" / "bin", home / ".volta" / "bin", home / ".config" / "composer" / "vendor" / "bin",
             home / ".composer" / "vendor" / "bin", home / ".pub-cache" / "bin", home / "flutter" / "bin", home / ".local" / "share" / "fnm" / "aliases" / "default" / "bin"]
    nvm = _nvm_bin(home)
    return [str(d) for d in ([nvm] if nvm else []) + extra if d.is_dir()]


def _nvm_bin(home: Path) -> Path | None:
    """bin-Ordner der nvm-Standardversion, sonst der neuesten. nvm trägt sich nur in interaktive Shells ein, ein Start aus dem Menü kennt ihn sonst nicht."""
    base = home / ".nvm" / "versions" / "node"
    try:
        versions = sorted((d for d in base.iterdir() if (d / "bin").is_dir()), key=lambda d: [int(x) for x in re.findall(r"\d+", d.name)])
    except OSError:
        return None
    try:
        wanted = "v" + (home / ".nvm" / "alias" / "default").read_text(encoding="utf-8").strip().lstrip("v")
    except OSError:
        wanted = ""
    matches = [d for d in versions if d.name == wanted or d.name.startswith(wanted + ".")] if wanted != "v" else []
    chosen = (matches or versions or [None])[-1]
    return chosen / "bin" if chosen else None


def extend_path():
    """Werkzeug-Ordner an den PATH hängen, damit Sprachserver, Build und Terminal beim Start aus dem Menü dasselbe finden wie in der Shell."""
    known = os.environ.get("PATH", "").split(os.pathsep)
    nvm = _nvm_bin(Path.home())
    first = [str(nvm)] if nvm and str(nvm) not in known else []       # nvm vor dem System-Node wie in der Shell: Sonst scheitert `npm i -g` an fehlenden Rechten
    os.environ["PATH"] = os.pathsep.join(first + known + [d for d in search_dirs() if d not in known and d not in first])


def find(name: str) -> str | None:
    """Pfad zum Programm oder None."""
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(search_dirs()))


def missing_message(name: str, purpose: str) -> str:
    return f"Für {purpose} wird '{name}' benötigt, es wurde aber nicht gefunden.\nInstallation (CachyOS/Arch): {HINTS.get(name, name)}"
