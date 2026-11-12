#!/usr/bin/env bash
set -euo pipefail

# Build from a pinned CI environment; no sudo/root needed for application use.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p build dist
python -m nuitka --standalone --enable-plugin=pyside6 \
  --include-package=appfootprint \
  --output-dir=build --output-filename=AppFootprint \
  --assume-yes-for-downloads \
  packaging/entrypoint.py

test -x build/entrypoint.dist/AppFootprint
APPDIR="$ROOT/build/AppFootprint.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a build/entrypoint.dist/. "$APPDIR/usr/bin/"
cp packaging/appfootprint.desktop "$APPDIR/appfootprint.desktop"
cp packaging/appfootprint.desktop "$APPDIR/usr/share/applications/appfootprint.desktop"
cp assets/appfootprint.svg "$APPDIR/appfootprint.svg"
cp assets/appfootprint.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/appfootprint.svg"
cp assets/appfootprint.svg "$APPDIR/appfootprint.svg"
cp packaging/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
# AppImage desktop metadata requires a root PNG icon matching Icon=appfootprint.
# Convert checked-in scalable SVG to PNG on the build host.
convert -background none assets/appfootprint.svg -resize 256x256 "$APPDIR/appfootprint.png"
cp "$APPDIR/appfootprint.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/appfootprint.png"
ARCH=x86_64 appimagetool "$APPDIR" "$ROOT/dist/AppFootprint-x86_64.AppImage"
chmod +x dist/AppFootprint-x86_64.AppImage
(cd dist && sha256sum AppFootprint-x86_64.AppImage > AppFootprint-x86_64.AppImage.sha256)
