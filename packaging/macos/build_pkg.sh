#!/bin/bash
# Build dist/Arachne-<version>.pkg from dist/Arachne.app.
set -e
VER="${1:-2.0.0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
STAGE="$HERE/../build/pkgroot"
rm -rf "$STAGE" && mkdir -p "$STAGE/Applications"
cp -R dist/Arachne.app "$STAGE/Applications/"
chmod +x "$HERE/scripts/postinstall"
pkgbuild --root "$STAGE" --identifier com.arachne.colony --version "$VER" \
         --scripts "$HERE/scripts" --install-location / "dist/Arachne-$VER.pkg"
