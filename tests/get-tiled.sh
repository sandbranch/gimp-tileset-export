#!/bin/sh
# Gets the official Tiled 1.12.2 AppImage for the tests, once, into
# tests/output/apps/ (needs the network; tests/run.sh itself does not):
# downloads it from github.com/mapeditor/tiled/releases, checks it against
# the SHA-256 that the release page gives for it, and unpacks it (no FUSE
# needed then).
#
# The AppImage brings only Qt's xcb platform plug-in, so for Tiled
# without a display (QT_QPA_PLATFORM=offscreen) Qt's offscreen plug-in of
# the same Qt (6.10) is added to the unpacked copy: from the Flatpak
# runtime org.kde.Platform//6.10 if it is installed, else from the
# official PyQt6-Qt6 6.10.2 wheel on PyPI (checked against its SHA-256).
#
#   tests/get-tiled.sh
#   TSE_TILED_APPIMAGE=/path/Tiled-1.12.2_Linux_x86_64.AppImage tests/get-tiled.sh
#                          (a copy you have; it is checked the same way)
#   TSE_QT_FROM=pypi tests/get-tiled.sh      (the plug-in from the wheel)
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
set -e
here=$(cd "$(dirname "$0")" && pwd)
apps=$here/output/apps
name=Tiled-1.12.2_Linux_x86_64.AppImage
url=https://github.com/mapeditor/tiled/releases/download/v1.12.2/$name
sha=5e0edbff61314f41af3c72c21ec006b363cf12047cc9cfb5bbd63a98bca3721c
wheel=pyqt6_qt6-6.10.2-py3-none-manylinux_2_34_x86_64.whl
wheel_url=https://files.pythonhosted.org/packages/d5/fe/01fd9b9d2ca139ef61582f2e2da249fa169229144294c1bb27db59ad8420/$wheel
wheel_sha=19c10b5f0806e9f9bac2c9759bd5d7d19a78967f330fd60a2db409177fa76e49
mkdir -p "$apps"

check () {
    echo "$2  $1" | sha256sum -c --quiet - || { echo "get-tiled: $1 does not match its SHA-256"; rm -f "$1"; exit 1; }
}

if [ ! -f "$apps/$name" ]; then
    if [ -n "$TSE_TILED_APPIMAGE" ]; then
        cp "$TSE_TILED_APPIMAGE" "$apps/$name.part"
    else
        curl -fL -o "$apps/$name.part" "$url"
    fi
    check "$apps/$name.part" "$sha"
    mv "$apps/$name.part" "$apps/$name"
fi
check "$apps/$name" "$sha"
chmod +x "$apps/$name"

if [ ! -x "$apps/tiled/AppRun" ]; then
    rm -rf "$apps/tiled" "$apps/squashfs-root"
    (cd "$apps" && "./$name" --appimage-extract >/dev/null)
    mv "$apps/squashfs-root" "$apps/tiled"
fi

platforms=$apps/tiled/usr/plugins/platforms
if [ ! -f "$platforms/libqoffscreen.so" ]; then
    kde=$(flatpak info --show-location org.kde.Platform//6.10 2>/dev/null || true)
    if [ "$TSE_QT_FROM" != pypi ] && [ -n "$kde" ] &&
         [ -f "$kde/files/lib/plugins/platforms/libqoffscreen.so" ]; then
        cp "$kde/files/lib/plugins/platforms/libqoffscreen.so" "$platforms/"
        echo "get-tiled: Qt offscreen plug-in from org.kde.Platform//6.10"
    else
        [ -f "$apps/$wheel" ] || curl -fL -o "$apps/$wheel" "$wheel_url"
        check "$apps/$wheel" "$wheel_sha"
        python3 - "$apps/$wheel" "$platforms" <<'PY'
import sys, zipfile
wheel, dest = sys.argv[1:]
with zipfile.ZipFile(wheel) as z:
    name = 'PyQt6/Qt6/plugins/platforms/libqoffscreen.so'
    with open(dest + '/libqoffscreen.so', 'wb') as f:
        f.write(z.read(name))
PY
        chmod 755 "$platforms/libqoffscreen.so"
        echo "get-tiled: Qt offscreen plug-in from $wheel"
    fi
fi
echo "get-tiled: $apps/tiled/AppRun"
