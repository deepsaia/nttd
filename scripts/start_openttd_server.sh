#!/bin/bash
# Start OpenTTD as a dedicated server for nttd development.
#
# Usage:
#   ./scripts/start_openttd_server.sh              # new random game with nttd GameScript
#   ./scripts/start_openttd_server.sh save.sav     # load a savegame
#
# The server uses ottd_config/ as its config/data directory.
# Admin port: 3977 (password: nttd).
# The nttd GameScript is in ottd_config/game/nttd-gs/.
# A symlink is created in ~/Documents/OpenTTD/game/ for discovery.
#
# To connect as a human player, open OpenTTD normally and
# join multiplayer at 127.0.0.1:3979

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OPENTTD="/Applications/OpenTTD.app/Contents/MacOS/openttd"
CONFIG_DIR="$PROJECT_DIR/ottd_config"
CONFIG="$CONFIG_DIR/openttd.cfg"
SECRETS="$CONFIG_DIR/secrets.cfg"

if [ ! -f "$OPENTTD" ]; then
    echo "Error: OpenTTD not found at $OPENTTD"
    exit 1
fi

# Ensure nttd GameScript is discoverable via ~/Documents/OpenTTD/game/
GS_SOURCE="$CONFIG_DIR/game/nttd-gs"
GS_TARGET="$HOME/Documents/OpenTTD/game/nttd-gs"
if [ ! -L "$GS_TARGET" ] && [ ! -d "$GS_TARGET" ]; then
    echo "Symlinking nttd GameScript..."
    ln -sf "$GS_SOURCE" "$GS_TARGET"
fi

# Patch configs right before launch to ensure GS is selected.
# OpenTTD reads [game_scripts] at startup and uses it for new game generation.
python3 -c "
import re, sys

# 1. Set GameScript in openttd.cfg
cfg = open('$CONFIG').read()
cfg = re.sub(
    r'\[game_scripts\]\n[^\[]*',
    '[game_scripts]\n\"nttd GameScript\" = \n\n',
    cfg
)
open('$CONFIG', 'w').write(cfg)

# 2. Ensure admin password in secrets.cfg
try:
    sec = open('$SECRETS').read()
    if 'admin_password = nttd' not in sec:
        sec = re.sub(r'admin_password = .*', 'admin_password = nttd', sec, count=1)
        open('$SECRETS', 'w').write(sec)
except FileNotFoundError:
    pass
"

echo "Config: nttd GameScript selected, admin port 3977"

if [ -n "$1" ]; then
    echo "Starting OpenTTD dedicated server (loading $1)..."
    exec "$OPENTTD" -D -c "$CONFIG" -g "$1"
else
    echo "Starting OpenTTD dedicated server (new game)..."
    exec "$OPENTTD" -D -c "$CONFIG" -g
fi
