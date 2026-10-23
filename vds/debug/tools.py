"""Sucht externe Debugger (dlv, netcoredbg, gdb, jdb …) im PATH und an üblichen Orten; liefert Installationshinweise für CachyOS/Arch."""
import os
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
}


def search_dirs() -> list:
    home = Path.home()
    extra = [home / "go" / "bin", home / ".local" / "bin", home / ".local" / "share" / "visual-death-studio" / "tools" / "bin", home / ".dotnet" / "tools"]
    return [str(d) for d in extra if d.is_dir()]


def find(name: str) -> str | None:
    """Pfad zum Programm oder None."""
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(search_dirs()))


def missing_message(name: str, purpose: str) -> str:
    return f"Für {purpose} wird '{name}' benötigt, es wurde aber nicht gefunden.\nInstallation (CachyOS/Arch): {HINTS.get(name, name)}"
