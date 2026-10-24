#!/usr/bin/env bash
# Installiert Visual Death Studio für den aktuellen Benutzer: virtuelle Umgebung, Starter im Terminal und Eintrag im Anwendungsmenü.
# Es wird nichts mit Administratorrechten ausgeführt und nichts außerhalb von $HOME (bzw. --prefix) geschrieben.
set -euo pipefail

ID="visual-death-studio"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
VENV="$SRC/venv"
DESKTOP=1
RECREATE=0

usage() {
    cat <<USAGE
Aufruf: ./install.sh [Optionen]

  --prefix DIR    Ordner für den Starter (DIR/bin/$ID), Standard: \$HOME/.local
  --venv DIR      Ort der virtuellen Python-Umgebung, Standard: <dieser Ordner>/venv
  --no-desktop    Keinen Eintrag im Anwendungsmenü anlegen
  --recreate      Virtuelle Umgebung löschen und neu anlegen (nur, wenn sie von diesem Skript stammt)
  -h, --help      Diese Hilfe

Entfernen: ./uninstall.sh
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="${2:?--prefix braucht einen Ordner}"; shift 2 ;;
        --venv) VENV="${2:?--venv braucht einen Ordner}"; shift 2 ;;
        --no-desktop) DESKTOP=0; shift ;;
        --recreate) RECREATE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -t 1 ]; then G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; B=$'\e[1m'; N=$'\e[0m'; else G=; Y=; R=; B=; N=; fi
step() { printf '%s==>%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '%sFehler:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }

# --- 1. Python --------------------------------------------------------------------------------
step "Python prüfen"
command -v python3 >/dev/null || die "python3 wurde nicht gefunden. Arch/CachyOS: sudo pacman -S python"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "Python 3.10 oder neuer wird benötigt (gefunden: $(python3 -V 2>&1))."
ok "$(python3 -V 2>&1)"

# --- 2. Virtuelle Umgebung --------------------------------------------------------------------
step "Virtuelle Umgebung: $VENV"
MARKER="$VENV/.vds-install"
if [ "$RECREATE" = 1 ] && [ -d "$VENV" ]; then
    [ -f "$MARKER" ] || die "$VENV stammt nicht von diesem Skript und wird nicht gelöscht."
    rm -rf "$VENV"
fi
if [ -x "$VENV/bin/python" ]; then
    ok "vorhandene Umgebung wird weiterverwendet"
else
    python3 -m venv "$VENV" 2>/dev/null \
        || die "Die virtuelle Umgebung konnte nicht angelegt werden. Debian/Ubuntu: sudo apt install python3-venv"
    echo "Von install.sh angelegt – uninstall.sh darf diese Umgebung löschen." > "$MARKER"
    ok "angelegt"
fi

step "Python-Pakete installieren (requirements.txt)"
"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet -r "$SRC/requirements.txt" \
    || die "pip install ist fehlgeschlagen (Netzwerk? Details: $VENV/bin/pip install -r requirements.txt)."
ok "installiert"

step "Selbsttest"
( cd "$SRC" && QT_QPA_PLATFORM=offscreen "$VENV/bin/python" -c 'import vds.app' ) \
    || die "Das Programm lässt sich nicht importieren. Fehlen Qt-Systembibliotheken? (Arch: sudo pacman -S libxcb xcb-util-cursor)"
ok "Programm lädt"

# --- 3. Starter -------------------------------------------------------------------------------
step "Starter anlegen"
BIN="$PREFIX/bin"
mkdir -p "$BIN"
{
    echo '#!/usr/bin/env bash'
    printf 'exec %q %q "$@"\n' "$VENV/bin/python" "$SRC/run.py"
} > "$BIN/$ID"
chmod +x "$BIN/$ID"
ok "$BIN/$ID"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) warn "$BIN ist nicht im PATH – füge das zu ~/.bashrc bzw. ~/.zshrc hinzu: export PATH=\"$BIN:\$PATH\"" ;;
esac

if [ "$DESKTOP" = 1 ]; then
    step "Eintrag im Anwendungsmenü"
    "$VENV/bin/python" "$SRC/run.py" --install-desktop >/dev/null
    command -v update-desktop-database >/dev/null \
        && update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications" 2>/dev/null || true
    ok "${XDG_DATA_HOME:-$HOME/.local/share}/applications/$ID.desktop"
fi

# --- 4. Optionale Werkzeuge -------------------------------------------------------------------
step "Optionale Werkzeuge (nur nötig für die jeweilige Sprache)"
hint() {  # Programm  Wofür  pacman-Paket
    if command -v "$1" >/dev/null 2>&1 || [ -x "$HOME/go/bin/$1" ] || [ -x "$HOME/.local/bin/$1" ]; then
        ok "$1 – $2"
    elif command -v pacman >/dev/null 2>&1; then
        warn "$1 fehlt – $2   (sudo pacman -S $3)"
    else
        warn "$1 fehlt – $2"
    fi
}
hint git "Änderungen-Ansicht" git
hint gcc "C/C++ kompilieren" gcc
hint gdb "Debugger für C/C++" gdb
hint clangd "IntelliSense für C/C++" clang
hint node "JavaScript/TypeScript" nodejs
hint go "Go" go
hint dlv "Debugger für Go" delve
hint rustc "Rust" rust
hint dotnet "C#" dotnet-sdk
hint java "Java" jdk-openjdk
hint php "PHP" php
hint claude "Claude-Chat und -Vervollständigung (Claude Code CLI)" "-"
echo "  Alles Weitere zeigt das Programm unter Hilfe → Installierte Werkzeuge prüfen."

printf '\n%sFertig.%s Starten mit: %s%s%s' "$G$B" "$N" "$B" "$ID" "$N"
[ "$DESKTOP" = 1 ] && printf '  (oder im Anwendungsmenü: Visual Death Studio)'
printf '\n'
