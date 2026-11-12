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
  src/appfootprint/gui.py

test -x build/gui.dist/AppFootprint
APPDIR="$ROOT/build/AppFootprint.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a build/gui.dist/. "$APPDIR/usr/bin/"
cp packaging/appfootprint.desktop "$APPDIR/appfootprint.desktop"
cp packaging/appfootprint.desktop "$APPDIR/usr/share/applications/appfootprint.desktop"
cp assets/appfootprint.svg "$APPDIR/appfootprint.svg"
cp assets/appfootprint.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/appfootprint.svg"
cp packaging/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
ARCH=x86_64 appimagetool "$APPDIR" "$ROOT/dist/AppFootprint-x86_64.AppImage"
chmod +x dist/AppFootprint-x86_64.AppImage
sha256sum dist/AppFootprint-x86_64.AppImage > dist/AppFootprint-x86_64.AppImage.sha256
