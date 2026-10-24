#!/usr/bin/env bash
# Entfernt, was install.sh angelegt hat: Starter, Anwendungsmenü-Eintrag, Icon und – falls von install.sh erzeugt – die virtuelle Umgebung.
# Deine Projekte und dieser Quellcode-Ordner werden nie angefasst. Mit --purge werden zusätzlich die Einstellungen gelöscht.
set -euo pipefail

ID="visual-death-studio"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
VENV="$SRC/venv"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
PURGE=0; YES=0; DRY=0

usage() {
    cat <<USAGE
Aufruf: ./uninstall.sh [Optionen]

  --prefix DIR   Ordner, in dem der Starter liegt (DIR/bin/$ID), Standard: \$HOME/.local
  --venv DIR     Ort der virtuellen Umgebung, falls bei der Installation geändert
  --purge        Zusätzlich Einstellungen (Fensterlayout, zuletzt geöffnete Ordner) und Werkzeug-Ordner löschen
  --dry-run      Nur anzeigen, was entfernt würde
  -y, --yes      Ohne Rückfrage
  -h, --help     Diese Hilfe
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="${2:?--prefix braucht einen Ordner}"; shift 2 ;;
        --venv) VENV="${2:?--venv braucht einen Ordner}"; shift 2 ;;
        --purge) PURGE=1; shift ;;
        --dry-run) DRY=1; shift ;;
        -y|--yes) YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

TARGETS=()
add() { [ -e "$1" ] || [ -L "$1" ] && TARGETS+=("$1") || true; }

add "$PREFIX/bin/$ID"
add "$DATA/applications/$ID.desktop"
add "$DATA/icons/hicolor/scalable/apps/$ID.svg"
if [ -f "$VENV/.vds-install" ]; then
    add "$VENV"
elif [ -d "$VENV" ]; then
    echo "Hinweis: $VENV wurde nicht von install.sh angelegt und bleibt erhalten."
fi
if [ "$PURGE" = 1 ]; then
    add "$CONFIG/VisualDeathStudio"
    add "$DATA/visual-death-studio"
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "Nichts zu entfernen."
    exit 0
fi

echo "Folgendes wird entfernt:"
printf '  %s\n' "${TARGETS[@]}"
[ "$PURGE" = 1 ] || echo "(Einstellungen bleiben erhalten; mit --purge werden sie ebenfalls gelöscht.)"

if [ "$DRY" = 1 ]; then
    echo "Testlauf – es wurde nichts gelöscht."
    exit 0
fi
if [ "$YES" != 1 ]; then
    read -r -p "Fortfahren? [j/N] " answer
    case "$answer" in j|J|y|Y) ;; *) echo "Abgebrochen."; exit 1 ;; esac
fi

for t in "${TARGETS[@]}"; do
    rm -rf -- "$t"
done
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA/applications" 2>/dev/null || true
echo "Entfernt. Der Quellcode in $SRC und deine Projekte sind unverändert."
