#!/bin/bash
# Install Papillon as an Ubuntu desktop application.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
DESKTOP_FILE="$HOME/.local/share/applications/papillon.desktop"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: venv not found at $SCRIPT_DIR/venv"
    echo "Create it with:  python3 -m venv venv && venv/bin/pip install PyQt5 python-xlib numpy"
    exit 1
fi

mkdir -p "$HOME/.local/share/applications"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Papillon
GenericName=Butterfly Animation
Comment=Fill your screen with beautiful butterflies
Exec=$VENV_PYTHON $SCRIPT_DIR/papillon.py
Icon=preferences-desktop-wallpaper
Terminal=false
Categories=Graphics;Amusement;
Keywords=butterfly;animation;desktop;overlay;
StartupNotify=false
EOF

chmod +x "$DESKTOP_FILE"

echo "Papillon installed."
echo "Find it in your application menu, or run directly:"
echo "  $VENV_PYTHON $SCRIPT_DIR/papillon.py"
