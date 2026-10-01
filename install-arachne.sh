#!/bin/bash
# Install Arachne from this folder: app-menu entry + Ctrl+Shift+B to start/stop.
#   ./install-arachne.sh              install
#   ./install-arachne.sh --uninstall  remove the menu entry and the shortcut
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$DIR/venv/bin/python" ]; then
    echo "Setting up the Python environment..."
    python3 -m venv "$DIR/venv" && "$DIR/venv/bin/pip" install -q PyQt5 python-xlib numpy || exit 1
fi
chmod +x "$DIR/arachne-toggle"
if [ "$1" = "--uninstall" ]; then
    exec "$DIR/venv/bin/python" "$DIR/arachne.py" --unsetup
fi
exec "$DIR/venv/bin/python" "$DIR/arachne.py" --setup
