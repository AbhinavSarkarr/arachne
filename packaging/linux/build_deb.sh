#!/bin/bash
# Build dist/arachne_<version>_amd64.deb from the PyInstaller binary dist/arachne.
set -e
VER="${1:-2.0.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../build/deb"
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" "$ROOT/opt/arachne" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/etc/xdg/autostart" "$ROOT/usr/share/icons/hicolor/256x256/apps"
install -m 755 dist/arachne "$ROOT/opt/arachne/arachne"
ln -s /opt/arachne/arachne "$ROOT/usr/bin/arachne"
cp "$HERE/../build/arachne.png" "$ROOT/usr/share/icons/hicolor/256x256/apps/arachne.png"

cat > "$ROOT/usr/share/applications/arachne.desktop" << EOD
[Desktop Entry]
Type=Application
Name=Arachne
GenericName=Spider Colony
Comment=A living spider colony on your desktop (Ctrl+Shift+B to start/stop)
Exec=arachne
Icon=arachne
Terminal=false
Categories=Amusement;Simulation;
StartupNotify=false
EOD

# every login: GNOME gets its Ctrl+Shift+B shortcut, other desktops get the hotkey agent
cat > "$ROOT/etc/xdg/autostart/arachne-agent.desktop" << EOD
[Desktop Entry]
Type=Application
Name=Arachne hotkey
Exec=arachne --agent
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOD

cat > "$ROOT/DEBIAN/control" << EOD
Package: arachne
Version: $VER
Architecture: amd64
Maintainer: Arachne
Depends: libxcb-xinerama0, libxkbcommon-x11-0, libgl1
Section: games
Priority: optional
Description: A living spider colony on your desktop
 Dozens of researched spider species build webs, hunt, court, lay eggs and
 grow up on top of your desktop. Ctrl+Shift+B starts or saves-and-stops it.
EOD

# set the shortcut up for whoever ran "sudo apt install", without waiting for a re-login
cat > "$ROOT/DEBIAN/postinst" << 'EOD'
#!/bin/sh
set -e
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    uid=$(id -u "$SUDO_USER")
    su "$SUDO_USER" -c "XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus DISPLAY=${DISPLAY:-:0} /usr/bin/arachne --setup" >/dev/null 2>&1 || true
fi
exit 0
EOD
cat > "$ROOT/DEBIAN/prerm" << 'EOD'
#!/bin/sh
if [ "$1" = "remove" ] && [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    uid=$(id -u "$SUDO_USER")
    su "$SUDO_USER" -c "XDG_RUNTIME_DIR=/run/user/$uid DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$uid/bus /usr/bin/arachne --unsetup" >/dev/null 2>&1 || true
fi
exit 0
EOD
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"
dpkg-deb --build --root-owner-group "$ROOT" "dist/arachne_${VER}_amd64.deb"
