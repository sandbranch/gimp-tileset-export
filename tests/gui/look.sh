#!/bin/sh
# Opens the Export Tileset dialog on a Broadway display, does the given
# steps (those of gimp-plugin-devtools/gui/cdp.mjs, with click, down,
# move and up at positions from the dialog's top left corner) and leaves
# a screenshot of the page in tests/output/gui/look.png; then stops GIMP.
# For looking at the layout. Run tests/run.sh first.
#
#   tests/gui/look.sh [step...]
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=SCRIPTDIR/common.sh
. "$here/common.sh"
start_gimp look
find_dialog
if [ -z "$at" ]; then
    echo "TSE GUI FAIL the dialog did not open (log: $out/gimp-look.log)"
    exit 1
fi
echo "dialog at $at"
steps=
for step in "$@"; do
    case $step in
        click:*|down:*|move:*|up:*)
            xy=${step#*:}
            step=${step%%:*}:$(p "${xy%,*}" "${xy#*,}");;
    esac
    steps="$steps $step"
done
# shellcheck disable=SC2086
$cdp "$view" $steps wait:500 shot:"$out/look.png" >/dev/null || exit 1
touch "$out/done"
echo "$out/look.png"
