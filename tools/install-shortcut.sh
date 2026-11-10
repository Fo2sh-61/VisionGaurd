#!/usr/bin/env bash
# Put the VisionGuard icon in the Ubuntu application menu and on the Desktop.
# The Linux counterpart of tools/install-shortcut.ps1.
#
#   tools/install-shortcut.sh            create (or refresh) both launchers
#   tools/install-shortcut.sh --remove   delete both
#
# Both are the same launcher, launch.sh, with the icon at assets/visionguard.png.
# Nothing is installed system-wide: the menu entry lives in
# ~/.local/share/applications and the Desktop copy in your Desktop folder.

set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[[ -n "$DESKTOP_DIR" && -d "$DESKTOP_DIR" ]] || DESKTOP_DIR="$HOME/Desktop"
MENU_FILE="$APPS/visionguard.desktop"
DESKTOP_FILE="$DESKTOP_DIR/visionguard.desktop"

case "${1:-}" in
  "") ;;
  --remove)
    rm -f "$MENU_FILE" "$DESKTOP_FILE"
    echo "Removed $MENU_FILE and $DESKTOP_FILE"
    exit 0 ;;
  *) echo "usage: install-shortcut.sh [--remove]" >&2; exit 2 ;;
esac

[[ -x "$ROOT/launch.sh" ]] || { echo "launch.sh is missing or not executable in $ROOT" >&2; exit 1; }
[[ -f "$ROOT/assets/visionguard.png" ]] || { echo "assets/visionguard.png is missing" >&2; exit 1; }

mkdir -p "$APPS" "$DESKTOP_DIR"
cat >"$MENU_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=VisionGuard
Comment=Start VisionGuard and open the console
Exec="$ROOT/launch.sh"
Path=$ROOT
Icon=$ROOT/assets/visionguard.png
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$MENU_FILE"

# The Desktop copy must be marked trusted, or GNOME shows it as a plain text
# file that asks "Allow Launching" before it will run.
cp "$MENU_FILE" "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"
if command -v gio >/dev/null 2>&1; then
  gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null \
    || echo "Could not mark the Desktop icon trusted; right-click it and choose Allow Launching."
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null

echo "Created $MENU_FILE"
echo "Created $DESKTOP_FILE"
