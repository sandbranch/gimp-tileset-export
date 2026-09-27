#!/usr/bin/env python3
# Makes tests/golden/main-map.png: the map of tests/fixtures.py (MAP) as
# it must look when drawn with the main fixture's tileset, made from the
# fixture's colours alone (not from an export), for the tmxrasterizer
# test. Run it when the fixture changes, look at the result, commit it.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import struct
import sys
import zlib

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import fixtures as fx      # noqa: E402

T = 16
rows = fx.MAP
w, h = len(rows[0]) * T, len(rows) * T
raw = b''
for y in range(h):
    raw += b'\x00'
    for x in range(w):
        tid = rows[y // T][x // T]
        if tid < 0 or tid in fx.EMPTY_TILES:
            raw += bytes((0, 0, 0, 0))
        else:
            raw += bytes(fx.COLORS[tid]) + b'\xff'


def chunk(kind, body):
    return (struct.pack('>I', len(body)) + kind + body +
            struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff))


png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
       chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))
out = os.path.join(here, 'golden', 'main-map.png')
with open(out, 'wb') as f:
    f.write(png)
print(out)
