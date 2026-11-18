#!/bin/sh
# Starts the native GIMP on a Broadway display, on the port
# TSE_BROADWAY_PORT (8087 by default; the page is http://127.0.0.1:port/)
# with tests/gui/gui-script.py, in the throwaway profile of tests/run.sh,
# which installs the plug-in there. HOME and the XDG folders are set to
# a throwaway home and GIO uses no GVFS, so that
# nothing of the user's changes (see tests/run.sh). broadwayd stops when
# GIMP quits, also when GIMP fails. GIMP loads no fonts (--no-fonts).
#
# GIMP starts when tests/output/gui/page-open exists: GIMP places its
# windows for the size of the Broadway screen, which is that of the page
# once a browser shows it (common.sh does so first).
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
here=$(cd "$(dirname "$0")" && pwd)
tests=$(dirname "$here")
out=$tests/output/gui
profile=$tests/output/profile
home=$tests/output/gui-home
port=${TSE_BROADWAY_PORT:-8087}
display=$((port - 8080))
mkdir -p "$out" "$home"
# no Welcome dialog: GIMP shows it when the profile is of an older
# version, or when asked to
if ! grep -q config-version "$profile/gimprc" 2>/dev/null; then
    version=$(gimp-console-3.2 --version | sed 's/.* //')
    printf '(config-version "%s")\n' "$version" >> "$profile/gimprc"
fi
grep -q show-welcome-dialog "$profile/gimprc" 2>/dev/null ||
  echo '(show-welcome-dialog no)' >> "$profile/gimprc"
# the windows where GIMP puts them by default, not where they were
rm -f "$profile/sessionrc"
# the interface font the clicks were measured with: GTK's "Sans" is
# DejaVu Sans, not the system's default (Noto Sans on Ubuntu has taller
# rows), as gimp-devtools/gimp-run.sh does for the other repositories
mkdir -p "$home/.config/fontconfig"
cat > "$home/.config/fontconfig/fonts.conf" <<'FONTS'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <match target="pattern">
    <test name="family"><string>Sans</string></test>
    <edit name="family" mode="assign" binding="strong"><string>DejaVu Sans</string></edit>
  </match>
  <match target="pattern">
    <test name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>DejaVu Sans</string></edit>
  </match>
</fontconfig>
FONTS
exec env GDK_BACKEND=broadway BROADWAY_DISPLAY=:$display \
  GIMP3_DIRECTORY="$profile" TSE_OUT="$out" \
  TSE_GUI_MODE="${TSE_GUI_MODE:-export}" \
  GIO_USE_VFS=local HOME="$home" XDG_CONFIG_HOME="$home/.config" \
  XDG_DATA_HOME="$home/.local/share" XDG_CACHE_HOME="$home/.cache" \
  XDG_STATE_HOME="$home/.local/state" sh -c \
  "broadwayd --port $port :$display & bw=\$!; trap 'kill \$bw' EXIT; \
   i=0; while [ ! -f '$out/page-open' ] && [ \$i -lt 300 ]; do sleep 0.2; i=\$((i+1)); done; \
   gimp-3.2 --new-instance --no-splash --no-fonts \
   --batch-interpreter python-fu-eval -b \"exec(open('$here/gui-script.py').read())\""
