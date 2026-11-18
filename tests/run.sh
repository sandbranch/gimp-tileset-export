#!/bin/sh
# Tests Tileset Export: installs the plug-in into a throwaway GIMP profile
# in tests/output (GIMP3_DIRECTORY), builds the test images and exports
# them in the native GIMP 3 (gimp-console-3.2 or gimp-console on the
# PATH) without a window (tests/gimp-build.py), then checks the
# files outside GIMP (tests/check.py): with Tiled 1.12.2 (tiled
# --evaluate and tmxrasterizer, offscreen, throwaway HOME) and with Godot
# 4.7 (headless, throwaway HOME set inside its Flatpak sandbox); a second
# GIMP run exports again what Godot changed in between. Then, if a
# headless Chrome and node are there, the dialog on a Broadway display
# (tests/gui/gui-test.sh).
#
# Before and after, it lists the user's own folders of GIMP, Tiled and
# Godot (tests/snapshot.sh: names, sizes, times) and fails if anything
# there changed.
#
#   tests/run.sh                   all tests
#   TSE_GUI=0 tests/run.sh         without the Broadway test
#   TSE_GODOT=/path/godot tests/run.sh   a native Godot 4.7 instead of the
#                                  Flatpak (run with a throwaway HOME too)
#
# Tiled comes from tests/get-tiled.sh (run it once; it needs the
# network); without it the Tiled checks are skipped. Nothing here needs
# the network. Prints PASS, FAIL or SKIP for each case and exits non-zero
# if any case fails.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
here=$(cd "$(dirname "$0")" && pwd)
src=$(dirname "$here")
out=$here/output
profile=$out/profile
status=0
mkdir -p "$out"

"$here/snapshot.sh" > "$out/snapshot-before.txt"

echo "== unit"
python3 "$here/unit.py" || status=1

rm -rf "$profile" "$out/cases" "$out/godot" "$out/tiled-home" "$out/tiled-rewrite" \
  "$out/gimp-home"
mkdir -p "$profile/plug-ins/tileset-export"
cp "$src/tileset-export/tileset-export.py" "$src/tileset-export/tileset_model.py" \
   "$profile/plug-ins/tileset-export/"
chmod 755 "$profile/plug-ins/tileset-export/tileset-export.py"

# GIMP loads no fonts (--no-fonts): GIMP 3.2 can hang while loading them.
# HOME and the XDG folders point to a throwaway home, and GIO uses no
# GVFS (GIO_USE_VFS=local): otherwise GIO's metadata journal in
# ~/.local/share/gvfs-metadata changes, and GIMP, GEGL and babl write
# their caches into ~/.cache.
gimp_home=$out/gimp-home
run_gimp () {
    phase=$1
    fonts=--no-fonts
    limit=1800
    # GIMP with fonts, for the text layer label, with a time limit: it
    # can hang while loading them
    [ "$phase" = fonts ] && fonts= && limit=300
    mkdir -p "$gimp_home"
    console=$(command -v gimp-console-3.2 || command -v gimp-console)
    [ -n "$console" ] || { echo "TSE FAIL gimp: no gimp-console on the PATH"; return 1; }
    HOME=$gimp_home XDG_CONFIG_HOME=$gimp_home/.config \
      XDG_DATA_HOME=$gimp_home/.local/share XDG_CACHE_HOME=$gimp_home/.cache \
      XDG_STATE_HOME=$gimp_home/.local/state GIO_USE_VFS=local \
      GIMP3_DIRECTORY="$profile" TSE_SRC="$src" TSE_OUT="$out" TSE_PHASE="$phase" \
      TSE_ONLY="$TSE_ONLY" timeout "$limit" "$console" --no-interface $fonts \
      --batch-interpreter python-fu-eval \
      -b "exec(open('$here/gimp-build.py').read())" --quit
}

gimp_phase () {
    log=$out/gimp-$1.log
    run_gimp "$1" >"$log" 2>&1
    if [ $? = 124 ]; then
        echo "TSE SKIP gimp $1: GIMP did not finish in time (log: $log)"
        return
    fi
    grep -E "^TSE|Traceback|^  File" "$log"
    grep -q "^TSE GIMP failures: 0$" "$log" || status=1
    # messages of the plug-in (its process is named after it)
    if grep -E "tileset-export.py.*(WARNING|CRITICAL)|Traceback" "$log"; then
        echo "TSE FAIL gimp: warnings or tracebacks from the plug-in, see $log"
        status=1
    fi
}

echo "== GIMP (build and export)"
gimp_phase 1
echo "== Tiled and Godot"
python3 "$here/check.py" 1 || status=1
echo "== GIMP (export again what Godot changed)"
gimp_phase 2
echo "== Godot"
python3 "$here/check.py" 2 || status=1
echo "== GIMP with fonts (a text layer as a label)"
gimp_phase fonts

if [ "$TSE_GUI" != 0 ]; then
    echo "== GUI (Broadway)"
    "$here/gui/gui-test.sh" || status=1
fi

echo "== your folders of GIMP, Tiled and Godot"
"$here/snapshot.sh" > "$out/snapshot-after.txt"
if cmp -s "$out/snapshot-before.txt" "$out/snapshot-after.txt"; then
    echo "TSE PASS nothing changed in them ($(wc -l < "$out/snapshot-after.txt") entries)"
else
    echo "TSE FAIL they changed:"
    diff "$out/snapshot-before.txt" "$out/snapshot-after.txt" | head -20
    status=1
fi

[ $status = 0 ] && echo "TSE all passed" || echo "TSE FAILED (logs in $out)"
exit $status
