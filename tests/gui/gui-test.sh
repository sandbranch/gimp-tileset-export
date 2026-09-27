#!/bin/sh
# Tests the Export Tileset dialog on a Broadway display with a headless
# Chrome: OK with the Tiled .tsj and the Godot .tres ticked as well (the
# four files are written), Cancel (nothing is written), and Repeat
# Tileset Export on an image that was not exported yet (the dialog
# opens; OK exports). Screenshots are left in tests/output/gui/. Run
# tests/run.sh first (it installs the plug-in into the test profile).
#
# Needs a headless Chrome (google-chrome or chromium), node 22 and
# ../gimp-devtools (or GIMP_PLUGIN_DEVTOOLS) for gui/cdp.mjs.
# Prints PASS or FAIL for each check and exits non-zero if one fails.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later

# (pass never fails, so "check && pass || fail" is an if-then-else)
# shellcheck disable=SC2015
here=$(cd "$(dirname "$0")" && pwd)
status=0
pass () { echo "TSE PASS gui $1"; }
fail () { echo "TSE FAIL gui $1"; status=1; }

# shellcheck source=SCRIPTDIR/common.sh
. "$here/common.sh"
rm -f "$out"/0*.png

# positions in the dialog, from its top left corner (the Broadway canvas,
# with the shadow around the window)
TSJ=66,601
TRES=66,624
OK=372,732
CANCEL=279,732

session () {
    name=$1
    TSE_GUI_MODE="export"
    [ "$name" = REPEAT ] && TSE_GUI_MODE=repeat
    export TSE_GUI_MODE
    # the dialog with the defaults, not the values of an earlier run
    [ "$name" = OK ] && rm -f "$tests/output/profile/plug-in-settings/"*tileset-export*.last
    start_gimp "$name"
    find_dialog
    if [ -z "$at" ]; then
        fail "$name: the dialog did not open (log: $out/gimp-$name.log)"
        stop_all
        return
    fi
    pass "$name: the dialog opened"
    case $name in
    OK)
        $cdp "$view" shot:"$out/01-dialog.png" click:"$(p ${TSJ%,*} ${TSJ#*,})" wait:300 \
          click:"$(p ${TRES%,*} ${TRES#*,})" wait:500 shot:"$out/02-ticked.png" \
          click:"$(p ${OK%,*} ${OK#*,})" >/dev/null;;
    CANCEL)
        $cdp "$view" click:"$(p ${CANCEL%,*} ${CANCEL#*,})" >/dev/null;;
    REPEAT)
        $cdp "$view" shot:"$out/03-repeat-dialog.png" click:"$(p ${OK%,*} ${OK#*,})" >/dev/null;;
    esac
    if ! wait_for "$out/result.txt" 60; then
        fail "$name: no result (log: $out/gimp-$name.log)"
        stop_all
        return
    fi
    touch "$out/done"
    r=$out/result.txt
    case $name in
    OK)
        grep -q '^status success$' "$r" && pass "OK: status success" || fail "OK: $(head -1 "$r")"
        grep -q '^tiles 8$' "$r" && pass "OK: 8 tiles" || fail "OK: $(grep tiles "$r")"
        if [ "$(grep '^file ' "$r" | sort | tr '\n' ' ')" = \
             "file gui.png file gui.tres file gui.tsj file gui.tsx " ]; then
            pass "OK: the PNG, the .tsx and the ticked .tsj and .tres"
        else
            fail "OK: files $(grep '^file ' "$r" | tr '\n' ' ')"
        fi
        grep -q 'type="Grass"' "$out/gui.tsx" 2>/dev/null &&
          grep -q '<polygon points="0,0 16,0 16,16"/>' "$out/gui.tsx" &&
          pass "OK: the label and the collision path are in the .tsx" ||
          fail "OK: the .tsx: $(cat "$out/gui.tsx" 2>/dev/null | head -20)";;
    CANCEL)
        grep -q '^status cancel$' "$r" && pass "Cancel: status cancel" ||
          fail "Cancel: $(head -1 "$r")"
        [ ! -e "$out/gui.png" ] && pass "Cancel: nothing written" || fail "Cancel: gui.png written";;
    REPEAT)
        grep -q '^status success$' "$r" && pass "Repeat: status success" ||
          fail "Repeat: $(head -1 "$r")"
        # the PNG in the dialog is this image's, not the last export's
        grep -q '^file gui-repeat.tsx$' "$r" && pass "Repeat: next to this image's XCF" ||
          fail "Repeat: files $(grep '^file ' "$r" | tr '\n' ' ')";;
    esac
    stop_all
}

for s in ${TSE_GUI_ONLY:-OK CANCEL REPEAT}; do
    session "$s"
done
[ $status = 0 ] && echo "TSE GUI all passed" || echo "TSE GUI FAILED (screenshots in $out)"
exit $status
