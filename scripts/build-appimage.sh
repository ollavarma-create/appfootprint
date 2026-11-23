#!/usr/bin/env bash
set -euo pipefail

# Build from a pinned CI environment; no sudo/root needed for application use.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p build dist
python -m nuitka --standalone --enable-plugin=pyside6 \
  --include-package=appfootprint \
  --output-dir=build --output-filename=AppFootprint \
  packaging/entrypoint.py

test -x build/entrypoint.dist/AppFootprint
APPDIR="$ROOT/build/AppFootprint.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a build/entrypoint.dist/. "$APPDIR/usr/bin/"
cp packaging/appfootprint.desktop "$APPDIR/appfootprint.desktop"
cp packaging/appfootprint.desktop "$APPDIR/usr/share/applications/appfootprint.desktop"
cp packaging/io.github.ollavarma_create.appfootprint.metainfo.xml "$APPDIR/usr/share/metainfo/"
cp packaging/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
# Use the approved PNG artwork directly; no SVG approximation or conversion.
cp assets/appfootprint.png "$APPDIR/appfootprint.png"
cp "$APPDIR/appfootprint.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/appfootprint.png"
# Never let appimagetool fetch a moving, unverified runtime at packaging time.
: "${APPIMAGE_RUNTIME_FILE:?Set APPIMAGE_RUNTIME_FILE to a verified type2 runtime}"
test -s "$APPIMAGE_RUNTIME_FILE"
ARCH=x86_64 appimagetool --runtime-file "$APPIMAGE_RUNTIME_FILE" "$APPDIR" "$ROOT/dist/AppFootprint-x86_64.AppImage"
chmod +x dist/AppFootprint-x86_64.AppImage
(cd dist && sha256sum AppFootprint-x86_64.AppImage > AppFootprint-x86_64.AppImage.sha256)
