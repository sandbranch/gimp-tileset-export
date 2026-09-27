# A small PNG reader for the tests (no PIL needed): non-interlaced PNGs
# of every colour type and bit depth, with the palette's transparency.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import struct
import zlib


class PNG:
    """width, height, bit_depth, color_type, and rgba(x, y): the pixel as
    (r, g, b, a) in 0..255 (16-bit values are rounded to 8)."""

    def __init__(self, path):
        with open(path, 'rb') as f:
            data = f.read()
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('%s is not a PNG' % path)
        pos = 8
        idat = b''
        self.palette = []
        self.trns = None
        self.chunks = []
        while pos < len(data):
            length, kind = struct.unpack('>I4s', data[pos:pos + 8])
            body = data[pos + 8:pos + 8 + length]
            pos += 12 + length
            kind = kind.decode('latin-1')
            self.chunks.append(kind)
            if kind == 'IHDR':
                (self.width, self.height, self.bit_depth, self.color_type, _, _,
                 interlace) = struct.unpack('>IIBBBBB', body)
                if interlace:
                    raise ValueError('interlaced PNGs are not read here')
            elif kind == 'PLTE':
                self.palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
            elif kind == 'tRNS':
                self.trns = body
            elif kind == 'IDAT':
                idat += body
            elif kind == 'IEND':
                break
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[self.color_type]
        bits = channels * self.bit_depth
        self.bpp = max(1, bits // 8)
        stride = (self.width * bits + 7) // 8
        raw = zlib.decompress(idat)
        rows = []
        prev = bytearray(stride)
        p = 0
        for _ in range(self.height):
            ftype = raw[p]
            line = bytearray(raw[p + 1:p + 1 + stride])
            p += 1 + stride
            self._unfilter(ftype, line, prev)
            rows.append(line)
            prev = line
        self.rows = rows
        self.channels = channels

    def _unfilter(self, ftype, line, prev):
        bpp = self.bpp
        for i in range(len(line)):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:
                line[i] = (line[i] + a) & 255
            elif ftype == 2:
                line[i] = (line[i] + b) & 255
            elif ftype == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ftype == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255

    def samples(self, x, y):
        """The raw samples of the pixel (16-bit ones as 0..65535)."""
        line = self.rows[y]
        if self.bit_depth < 8:
            per = 8 // self.bit_depth
            byte = line[x // per]
            shift = 8 - self.bit_depth * (x % per + 1)
            return ((byte >> shift) & ((1 << self.bit_depth) - 1),)
        n = self.channels
        if self.bit_depth == 8:
            return tuple(line[x * n:x * n + n])
        return tuple(struct.unpack('>%dH' % n, bytes(line[x * n * 2:x * n * 2 + n * 2])))

    def rgba(self, x, y):
        s = self.samples(x, y)
        if self.color_type == 3:
            i = s[0]
            r, g, b = self.palette[i]
            a = self.trns[i] if self.trns is not None and i < len(self.trns) else 255
            return (r, g, b, a)
        if self.bit_depth == 16:
            s = tuple(int(round(v / 257.0)) for v in s)
        elif self.bit_depth < 8:
            s = tuple(v * 255 // ((1 << self.bit_depth) - 1) for v in s)
        if self.color_type == 0:
            return (s[0], s[0], s[0], 255)
        if self.color_type == 4:
            return (s[0], s[0], s[0], s[1])
        if self.color_type == 2:
            return s + (255,)
        return s
