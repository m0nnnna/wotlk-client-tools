#!/bin/sh
# Install NekoCore Launcher on Linux (no root): a `nekocore` command and an
# app-menu entry (Categories=Game). Needs python3-tk, wine, wine32:i386 and,
# for good performance, DXVK (Ultimit: scripts/get-dxvk.sh).
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
BIN=${BIN_DIR:-$HOME/.local/bin}
APPS=${XDG_DATA_HOME:-$HOME/.local/share}/applications
mkdir -p "$BIN" "$APPS"
cat >"$BIN/nekocore" <<SH
#!/bin/sh
exec python3 "$REPO/nekocore_launcher.py" "\$@"
SH
chmod +x "$BIN/nekocore"
cat >"$APPS/nekocore-launcher.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=NekoCore
GenericName=World of Warcraft 3.3.5a launcher
Comment=Patch, update and play on the NekoCore realm
Exec=$BIN/nekocore
Icon=applications-games
Terminal=false
Categories=Game;
Keywords=wow;warcraft;wotlk;nekocore;
StartupWMClass=Tk
DESK
echo "installed: $BIN/nekocore and $APPS/nekocore-launcher.desktop"
