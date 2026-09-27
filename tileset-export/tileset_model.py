# Tileset Export for GIMP 3: the parts that do not need GIMP.
#
# The layout of a tileset image (tile size, margin, spacing, columns),
# the naming conventions read from the XCF (tile labels, animations,
# collision paths), the geometry of collision polygons, and the writers
# for Tiled (.tsx, .tsj) and Godot 4 (TileSet .tres, .png.import).
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import math
import os
import re
import secrets

TSX_VERSION = '1.10'    # the TMX format version written (read by Tiled 1.10 and later)


class TilesetError(Exception):
    """An error for the user, shown as a message, never as a traceback."""


# ------------------------------------------------------------ properties

PROPERTY_TYPES = ('string', 'int', 'float', 'bool', 'color', 'file')

INT_RE = re.compile(r'^[+-]?\d+$')
FLOAT_RE = re.compile(r'^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$')
COLOR_RE = re.compile(r'^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')
# what GIMP adds to a layer name to keep names unique, or to a copy
GIMP_SUFFIX_RE = re.compile(r'(\s+copy)?(\s+#\d+)?\s*$')
DURATION_RE = re.compile(r'\(\s*(\d+(?:\.\d+)?)\s*ms\s*\)', re.IGNORECASE)
# GIMP's animation tags in layer names: (combine), (replace)
FRAME_TAG_RE = re.compile(r'\(\s*(combine|replace)\s*\)', re.IGNORECASE)
ANIM_RE = re.compile(r'^anim\s*:\s*(.*)$', re.IGNORECASE)
TILESET_LABEL_RE = re.compile(r'^tileset\s*:(.*)$', re.IGNORECASE)
PROPERTIES_GROUP_NAMES = ('properties', 'tile properties')
COLLISION_PREFIX = 'collision'
DEFAULT_FRAME_MS = 100


class Prop:
    """A custom property: a name, one of PROPERTY_TYPES and a value
    (str, int, float, bool, or a colour as (r, g, b, a) in 0..255)."""

    def __init__(self, name, type_, value):
        self.name = name
        self.type = type_
        self.value = value

    def __eq__(self, other):
        return (isinstance(other, Prop) and (self.name, self.type, self.value) ==
                (other.name, other.type, other.value))

    def __repr__(self):
        return 'Prop(%r, %r, %r)' % (self.name, self.type, self.value)

    def tiled_value(self):
        """The value as Tiled writes it in a .tsx."""
        if self.type == 'bool':
            return 'true' if self.value else 'false'
        if self.type == 'float':
            return fmt_number(self.value)
        if self.type == 'color':
            return color_to_tiled(self.value)
        return str(self.value)

    def json_value(self):
        """The value as Tiled writes it in a .tsj."""
        if self.type == 'color':
            return color_to_tiled(self.value)
        return self.value


def color_to_tiled(rgba):
    """#aarrggbb, as Tiled writes colours (also opaque ones)."""
    r, g, b, a = rgba
    return '#%02x%02x%02x%02x' % (a, r, g, b)


def parse_color(text):
    """#rrggbb or Tiled's #aarrggbb to (r, g, b, a)."""
    h = text[1:]
    if len(h) == 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
    return (int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16), int(h[0:2], 16))


def convert_value(key, type_, text, quoted):
    """A property value from its text: of the given type, or of the type
    the text looks like (true/false, an integer, a number, #rrggbb) when
    there is none; quoted text is always a string."""
    if type_ is None:
        if quoted:
            return 'string', text
        low = text.lower()
        if low in ('true', 'false'):
            return 'bool', low == 'true'
        if INT_RE.match(text):
            return 'int', int(text)
        if FLOAT_RE.match(text):
            return 'float', float(text)
        if COLOR_RE.match(text):
            return 'color', parse_color(text)
        return 'string', text
    if type_ in ('string', 'file'):
        return type_, text
    if type_ == 'bool':
        low = text.lower()
        if low in ('true', 'false', '1', '0', 'yes', 'no'):
            return 'bool', low in ('true', '1', 'yes')
    elif type_ == 'int':
        if INT_RE.match(text):
            return 'int', int(text)
    elif type_ == 'float':
        if FLOAT_RE.match(text):
            return 'float', float(text)
    elif type_ == 'color':
        if COLOR_RE.match(text):
            return 'color', parse_color(text)
    raise ValueError('%s: "%s" is not of type %s' % (key, text, type_))


def tokenize(text):
    """Splits a label into words at spaces, keeping quoted parts ("..."
    or '...', with \\" and \\\\ inside) together. Returns a list of
    (key or None, value, value_quoted): key=value words give their key."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        parts = []           # (text, quoted)
        key = None
        while i < n and not text[i].isspace():
            c = text[i]
            if c in '"\'':
                quote = c
                i += 1
                buf = []
                while i < n and text[i] != quote:
                    if text[i] == '\\' and i + 1 < n and text[i + 1] in (quote, '\\'):
                        i += 1
                    buf.append(text[i])
                    i += 1
                if i >= n:
                    raise ValueError('a quote is not closed: %s' % text)
                i += 1
                parts.append((''.join(buf), True))
            elif c == '=' and key is None:
                key = ''.join(p for p, _ in parts)
                parts = []
                i += 1
            else:
                buf = []
                while i < n and not text[i].isspace() and text[i] not in '"\'' and \
                        not (text[i] == '=' and key is None):
                    buf.append(text[i])
                    i += 1
                parts.append((''.join(buf), False))
        value = ''.join(p for p, _ in parts)
        tokens.append((key, value, any(q for _, q in parts)))
    return tokens


def strip_gimp_suffix(name):
    """The name without what GIMP adds: " #1" to keep names unique, and
    " copy" for a duplicate."""
    return GIMP_SUFFIX_RE.sub('', name)


class Label:
    """What a label says: a class, properties and a probability."""

    def __init__(self):
        self.cls = ''
        self.props = {}
        self.probability = None
        self.errors = []


def parse_label(text, allow_probability=True):
    """A tile label: "[Class] [key=value ...]", with key:type=value to
    give the type (string, int, float, bool, color, file), class=... for
    the class and probability=... for the tile's probability."""
    label = Label()
    text = strip_gimp_suffix(text).strip()
    try:
        tokens = tokenize(text)
    except ValueError as e:
        label.errors.append(str(e))
        return label
    for key, value, quoted in tokens:
        if key is None:
            if not label.cls and not label.props:
                label.cls = value
            else:
                label.errors.append('"%s": a word without "=" (only the first word is the '
                                    'class)' % value)
            continue
        type_ = None
        if ':' in key:
            key, type_ = key.split(':', 1)
            type_ = type_.strip().lower()
            if type_ not in PROPERTY_TYPES:
                label.errors.append('%s: unknown type "%s" (one of %s)' %
                                    (key, type_, ', '.join(PROPERTY_TYPES)))
                continue
        key = key.strip()
        if not key:
            label.errors.append('"=%s": a property without a name' % value)
            continue
        if key == 'class' and type_ is None:
            label.cls = value
            continue
        if key == 'probability' and type_ is None and allow_probability:
            if FLOAT_RE.match(value) and float(value) >= 0:
                label.probability = float(value)
            else:
                label.errors.append('probability: "%s" is not a number >= 0' % value)
            continue
        try:
            t, v = convert_value(key, type_, value, quoted)
        except ValueError as e:
            label.errors.append(str(e))
            continue
        label.props[key] = Prop(key, t, v)
    return label


def is_properties_group(name):
    return strip_gimp_suffix(name).strip().lower() in PROPERTIES_GROUP_NAMES


def tileset_label_text(name):
    """The text after "tileset:" of a tileset label, or None."""
    m = TILESET_LABEL_RE.match(strip_gimp_suffix(name).strip())
    return m.group(1) if m else None


def is_collision_path(name):
    return name.strip().lower().startswith(COLLISION_PREFIX)


def duration_ms(name):
    """The frame duration in a layer name, "(100ms)", or None."""
    m = DURATION_RE.search(name)
    if not m:
        return None
    return max(1, int(round(float(m.group(1)))))


def anim_name(name):
    """The animation's name if the layer is named "anim:<name>", else
    None (the duration and GIMP's suffixes are not part of it)."""
    clean = FRAME_TAG_RE.sub('', DURATION_RE.sub('', strip_gimp_suffix(name))).strip()
    m = ANIM_RE.match(clean)
    if not m:
        return None
    return m.group(1).strip() or 'animation'


# ---------------------------------------------------------------- layout

class Layout:
    """Where the tiles are in the tileset image. Columns and rows as
    Tiled (Tileset::columnCountForWidth) and Godot
    (TileSetAtlasSource::get_atlas_grid_size) count them: pixels at the
    right and the bottom that do not make a whole tile are not part of
    any tile."""

    def __init__(self, image_w, image_h, tile_w, tile_h, margin=0, spacing=0):
        if tile_w < 1 or tile_h < 1:
            raise TilesetError('The tile size must be at least 1x1 pixels, not %dx%d.' %
                               (tile_w, tile_h))
        if margin < 0 or spacing < 0:
            raise TilesetError('Margin and spacing cannot be negative.')
        self.image_w, self.image_h = image_w, image_h
        self.tile_w, self.tile_h = tile_w, tile_h
        self.margin, self.spacing = margin, spacing
        self.columns = max(0, (image_w - margin + spacing) // (tile_w + spacing))
        self.rows = max(0, (image_h - margin + spacing) // (tile_h + spacing))
        if self.columns == 0 or self.rows == 0:
            raise TilesetError('The image (%dx%d) holds no whole tile of %dx%d with a margin '
                               'of %d.' % (image_w, image_h, tile_w, tile_h, margin))

    @property
    def tile_count(self):
        return self.columns * self.rows

    def leftover(self):
        """The pixels right of and below the last whole tile, (x, y)."""
        used_w = self.margin + self.columns * (self.tile_w + self.spacing) - self.spacing
        used_h = self.margin + self.rows * (self.tile_h + self.spacing) - self.spacing
        return self.image_w - used_w, self.image_h - used_h

    def cell_origin(self, col, row):
        return (self.margin + col * (self.tile_w + self.spacing),
                self.margin + row * (self.tile_h + self.spacing))

    def tile_id(self, col, row):
        return row * self.columns + col

    def col_row(self, tile_id):
        return tile_id % self.columns, tile_id // self.columns

    def cell_rect(self, col, row):
        x, y = self.cell_origin(col, row)
        return x, y, x + self.tile_w, y + self.tile_h

    def cell_at(self, x, y):
        """The (col, row) of the tile whose pixels contain the point, or
        None for a point on the margin, the spacing or outside."""
        fx, fy = x - self.margin, y - self.margin
        if fx < 0 or fy < 0:
            return None
        pitch_x, pitch_y = self.tile_w + self.spacing, self.tile_h + self.spacing
        col, row = int(fx // pitch_x), int(fy // pitch_y)
        if col >= self.columns or row >= self.rows:
            return None
        if fx - col * pitch_x >= self.tile_w or fy - row * pitch_y >= self.tile_h:
            return None
        return col, row

    def cells_in_rect(self, x0, y0, x1, y1):
        """The cells that the rectangle [x0, x1) x [y0, y1) overlaps, in
        reading order."""
        cells = []
        for row in range(self.rows):
            for col in range(self.columns):
                cx0, cy0, cx1, cy1 = self.cell_rect(col, row)
                if cx0 < x1 and x0 < cx1 and cy0 < y1 and y0 < cy1:
                    cells.append((col, row))
        return cells


def layout_from_grid(image_w, image_h, grid_spacing, grid_offset, gap):
    """Tile size, margin and cropping from GIMP's image grid: the grid's
    spacing is the distance from one tile to the next (the tile plus the
    gap between tiles), its offset where the first tile starts (the
    margin). Returns (tile_w, tile_h, margin_x, margin_y)."""
    sx, sy = grid_spacing
    ox, oy = grid_offset
    sx, sy = int(round(sx)), int(round(sy))
    if sx < 1 or sy < 1:
        raise TilesetError('The image grid has a spacing of %sx%s.' % grid_spacing)
    tile_w, tile_h = sx - gap, sy - gap
    if tile_w < 1 or tile_h < 1:
        raise TilesetError('The spacing between tiles (%d) leaves no room for a tile in a '
                           'grid of %dx%d.' % (gap, sx, sy))
    # the grid repeats, so an offset of 18 on a grid of 17 is one of 1
    mx, my = int(round(ox)) % sx, int(round(oy)) % sy
    return tile_w, tile_h, mx, my


# -------------------------------------------------------------- geometry

def flatten_stroke(points, closed, tolerance=0.25):
    """A GIMP Bezier stroke (control points: in-handle, anchor,
    out-handle for each anchor, as x, y, x, y, ...) as a list of (x, y):
    straight segments stay two points, curved ones are divided until
    they are within tolerance pixels."""
    trip = [(points[i], points[i + 1]) for i in range(0, len(points) - 1, 2)]
    anchors = []
    for k in range(0, len(trip) - 2, 3):
        anchors.append((trip[k], trip[k + 1], trip[k + 2]))
    if not anchors:
        return []
    out = [anchors[0][1]]
    count = len(anchors) if closed else len(anchors) - 1
    for k in range(count):
        a = anchors[k]
        b = anchors[(k + 1) % len(anchors)]
        p0, p1, p2, p3 = a[1], a[2], b[0], b[1]
        if p1 == p0 and p2 == p3:
            out.append(p3)
        else:
            out.extend(_bezier(p0, p1, p2, p3, tolerance)[1:])
    if closed and len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def _bezier(p0, p1, p2, p3, tolerance, depth=0):
    # flat enough: the control points are close to the chord
    def dist(p):
        (x0, y0), (x1, y1) = p0, p3
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length == 0:
            return math.hypot(p[0] - x0, p[1] - y0)
        return abs((p[0] - x0) * dy - (p[1] - y0) * dx) / length
    if depth >= 12 or max(dist(p1), dist(p2)) <= tolerance:
        return [p0, p3]
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)   # noqa: E731
    p01, p12, p23 = mid(p0, p1), mid(p1, p2), mid(p2, p3)
    p012, p123 = mid(p01, p12), mid(p12, p23)
    m = mid(p012, p123)
    return (_bezier(p0, p01, p012, m, tolerance, depth + 1) +
            _bezier(m, p123, p23, p3, tolerance, depth + 1)[1:])


def polygon_area(poly):
    a = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        a += x0 * y1 - x1 * y0
    return a / 2


def clip_polygon(poly, x0, y0, x1, y1):
    """The part of a polygon inside the rectangle (Sutherland and
    Hodgman)."""
    def clip(points, inside, cross):
        out = []
        for i in range(len(points)):
            cur, prev = points[i], points[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def at_x(x):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_y(y):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    pts = list(poly)
    for inside, cross in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                          (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        if not pts:
            break
        pts = clip(pts, inside, cross)
    return pts


def simplify(poly, eps=1e-6):
    """Without repeated points and points on a straight line between
    their neighbours."""
    pts = []
    for p in poly:
        if not pts or abs(p[0] - pts[-1][0]) > eps or abs(p[1] - pts[-1][1]) > eps:
            pts.append(p)
    while len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) <= eps and \
            abs(pts[0][1] - pts[-1][1]) <= eps:
        pts.pop()
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if abs(cross) <= eps:
                del pts[i]
                changed = True
                break
    return pts


def round_point(p):
    return (round(p[0], 3) + 0.0, round(p[1], 3) + 0.0)


def polygons_for_cells(poly, layout):
    """The collision polygons that one closed path stroke (in image
    pixels) gives: {(col, row): [polygon in tile pixels]}. A stroke in
    one tile is that tile's polygon; one that crosses tiles is cut at
    their edges into a polygon for each."""
    if len(poly) < 3:
        return {}
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    result = {}
    for col, row in layout.cells_in_rect(min(xs), min(ys), max(xs) + 1e-9, max(ys) + 1e-9):
        cx0, cy0, cx1, cy1 = layout.cell_rect(col, row)
        piece = simplify(clip_polygon(poly, cx0, cy0, cx1, cy1))
        if len(piece) >= 3 and abs(polygon_area(piece)) > 0.01:
            result[(col, row)] = [round_point((x - cx0, y - cy0)) for x, y in piece]
    return result


# ---------------------------------------------------------------- the model

class Tile:
    def __init__(self, tile_id):
        self.id = tile_id
        self.cls = ''
        self.props = {}
        self.probability = None
        self.polygons = []          # [[(x, y), ...]] in tile pixels
        self.animation = []         # [(tile_id, ms)]
        self.empty = False          # all pixels transparent

    def has_data(self):
        return bool(self.cls or self.props or self.probability is not None or
                    self.polygons or self.animation)


class Tileset:
    """Everything that is written: the image, the layout, the tileset's
    and the tiles' classes, properties, collision polygons and
    animations."""

    def __init__(self, name, image_file, layout):
        self.name = name
        self.image_file = image_file        # the PNG's file name, next to the metadata
        self.layout = layout
        self.cls = ''
        self.props = {}
        self.tiles = {}
        self.warnings = []

    def tile(self, tile_id):
        if tile_id not in self.tiles:
            self.tiles[tile_id] = Tile(tile_id)
        return self.tiles[tile_id]

    def warn(self, text):
        if text not in self.warnings:
            self.warnings.append(text)


def fmt_number(v):
    """A number as short as it can be written: 16, 0.5, -2.25."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return ('%.6f' % v).rstrip('0').rstrip('.')


# ----------------------------------------------------------------- Tiled

def _xml(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace('\n', '&#10;').replace('\t', '&#9;'))


def _tsx_properties(props, indent):
    if not props:
        return []
    pad = ' ' * indent
    lines = [pad + '<properties>']
    for name in sorted(props):
        p = props[name]
        attrs = ' name="%s"' % _xml(p.name)
        if p.type != 'string':
            attrs += ' type="%s"' % p.type
        value = p.tiled_value()
        if '\n' in value:
            lines.append(pad + ' <property%s>%s</property>' % (attrs, _xml(value)))
        else:
            lines.append(pad + ' <property%s value="%s"/>' % (attrs, _xml(value)))
    lines.append(pad + '</properties>')
    return lines


def _tiled_polygon_object(poly):
    """A Tiled polygon object as Tiled's collision editor makes them: its
    position is the first point, the points are relative to it."""
    ox, oy = poly[0]
    return ox, oy, [round_point((x - ox, y - oy)) for x, y in poly]


def write_tsx(ts):
    lay = ts.layout
    attrs = 'version="%s" name="%s"' % (TSX_VERSION, _xml(ts.name))
    if ts.cls:
        attrs += ' class="%s"' % _xml(ts.cls)
    attrs += ' tilewidth="%d" tileheight="%d"' % (lay.tile_w, lay.tile_h)
    if lay.spacing:
        attrs += ' spacing="%d"' % lay.spacing
    if lay.margin:
        attrs += ' margin="%d"' % lay.margin
    attrs += ' tilecount="%d" columns="%d"' % (lay.tile_count, lay.columns)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<tileset %s>' % attrs]
    lines += _tsx_properties(ts.props, 1)
    lines.append(' <image source="%s" width="%d" height="%d"/>' %
                 (_xml(ts.image_file), lay.image_w, lay.image_h))
    for tid in sorted(ts.tiles):
        t = ts.tiles[tid]
        if not t.has_data():
            continue
        attrs = 'id="%d"' % tid
        if t.cls:
            # Tiled 1.10 and later write a tile's class as "type"
            attrs += ' type="%s"' % _xml(t.cls)
        if t.probability is not None and t.probability != 1.0:
            attrs += ' probability="%s"' % fmt_number(t.probability)
        lines.append(' <tile %s>' % attrs)
        lines += _tsx_properties(t.props, 2)
        if t.polygons:
            lines.append('  <objectgroup draworder="index" id="2">')
            for i, poly in enumerate(t.polygons):
                ox, oy, rel = _tiled_polygon_object(poly)
                lines.append('   <object id="%d" x="%s" y="%s">' %
                             (i + 1, fmt_number(ox), fmt_number(oy)))
                lines.append('    <polygon points="%s"/>' %
                             ' '.join('%s,%s' % (fmt_number(x), fmt_number(y)) for x, y in rel))
                lines.append('   </object>')
            lines.append('  </objectgroup>')
        if t.animation:
            lines.append('  <animation>')
            for frame_id, ms in t.animation:
                lines.append('   <frame tileid="%d" duration="%d"/>' % (frame_id, ms))
            lines.append('  </animation>')
        lines.append(' </tile>')
    lines.append('</tileset>')
    return '\n'.join(lines) + '\n'


def _json_properties(props):
    out = []
    for name in sorted(props):
        p = props[name]
        out.append({'name': p.name, 'type': p.type, 'value': p.json_value()})
    return out


def write_tsj(ts):
    lay = ts.layout
    d = {
        'type': 'tileset',
        'version': TSX_VERSION,
        'name': ts.name,
        'tilewidth': lay.tile_w,
        'tileheight': lay.tile_h,
        'spacing': lay.spacing,
        'margin': lay.margin,
        'tilecount': lay.tile_count,
        'columns': lay.columns,
        'image': ts.image_file,
        'imagewidth': lay.image_w,
        'imageheight': lay.image_h,
    }
    if ts.cls:
        d['class'] = ts.cls
    if ts.props:
        d['properties'] = _json_properties(ts.props)
    tiles = []
    for tid in sorted(ts.tiles):
        t = ts.tiles[tid]
        if not t.has_data():
            continue
        td = {'id': tid}
        if t.cls:
            td['type'] = t.cls
        if t.probability is not None and t.probability != 1.0:
            td['probability'] = t.probability
        if t.props:
            td['properties'] = _json_properties(t.props)
        if t.polygons:
            objects = []
            for i, poly in enumerate(t.polygons):
                ox, oy, rel = _tiled_polygon_object(poly)
                objects.append({'id': i + 1, 'name': '', 'type': '', 'x': ox, 'y': oy,
                                'width': 0, 'height': 0, 'rotation': 0, 'visible': True,
                                'polygon': [{'x': x, 'y': y} for x, y in rel]})
            td['objectgroup'] = {'draworder': 'index', 'id': 2, 'name': '', 'type': 'objectgroup',
                                 'opacity': 1, 'visible': True, 'x': 0, 'y': 0,
                                 'objects': objects}
        if t.animation:
            td['animation'] = [{'tileid': f, 'duration': ms} for f, ms in t.animation]
        tiles.append(td)
    if tiles:
        d['tiles'] = tiles
    return json.dumps(d, indent=1, ensure_ascii=False) + '\n'


# ----------------------------------------------------------------- Godot

GODOT_TYPES = {'bool': 1, 'int': 2, 'float': 3, 'string': 4, 'file': 4, 'color': 20}
GODOT_CLASS_LAYER = 'class'
UID_CHARS = 'abcdefghijklmnopqrstuvwxy012345678'    # core/io/resource_uid.cpp


def godot_uid(number=None):
    """A Godot resource UID, "uid://...", as ResourceUID::id_to_text
    writes a random 63-bit id."""
    n = secrets.randbits(63) if number is None else number & 0x7FFFFFFFFFFFFFFF
    s = ''
    while True:
        s = UID_CHARS[n % len(UID_CHARS)] + s
        n //= len(UID_CHARS)
        if not n:
            break
    return 'uid://' + s


def godot_string(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def godot_float(v):
    s = fmt_number(float(v))
    return s if ('.' in s or 'e' in s) else s + '.0'


def godot_value(type_, value):
    if type_ == 'bool':
        return 'true' if value else 'false'
    if type_ == 'int':
        return str(int(value))
    if type_ == 'float':
        return godot_float(value)
    if type_ == 'color':
        return 'Color(%s)' % ', '.join(godot_float(c / 255.0) if c not in (0, 255) else
                                       str(c // 255) for c in value)
    return godot_string(value)


def godot_custom_layers(ts):
    """The custom data layers: the class (if any tile has one) and one
    for each property name, with one type for all tiles: int and float
    together become float, other mixes become strings."""
    types = {}
    for t in ts.tiles.values():
        for p in t.props.values():
            types.setdefault(p.name, set()).add(p.type)
    layers = []
    if any(t.cls for t in ts.tiles.values()):
        layers.append((GODOT_CLASS_LAYER, 'string'))
    for name in sorted(types):
        if name == GODOT_CLASS_LAYER and layers and layers[0][0] == GODOT_CLASS_LAYER:
            ts.warn('Godot: the property "class" is left out: the custom data layer "class" '
                    'holds the tile classes.')
            continue
        tset = types[name]
        if len(tset) == 1:
            t = next(iter(tset))
        elif tset <= {'int', 'float'}:
            t = 'float'
        else:
            t = 'string'
            ts.warn('Godot: the property "%s" has values of different types (%s); '
                    'they are written as strings.' % (name, ', '.join(sorted(tset))))
        layers.append((name, t))
    return layers


def _godot_convert(prop, want):
    if prop.type == want or (want == 'string' and prop.type == 'file'):
        return prop.value
    if want == 'float':
        return float(prop.value)
    return prop.tiled_value()


def godot_animation_columns(ts, tile):
    """How Godot can hold an animation: its frames must follow each other
    in the atlas from the first one, in rows of animation_columns.
    Returns the number of columns, or None if the frames are placed
    otherwise."""
    lay = ts.layout
    base_col, base_row = lay.col_row(tile.animation[0][0])
    cells = [lay.col_row(f) for f, _ in tile.animation]
    n = len(cells)
    for columns in [n] + list(range(1, n)):
        if all(cells[i] == (base_col + i % columns, base_row + i // columns) for i in range(n)):
            if base_col + min(columns, n) <= lay.columns:
                return columns
    return None


def godot_plan(ts, skip_empty=True):
    """Which tiles the Godot atlas has and which cells animations cover:
    returns ({tile_id: columns or None}, [tile ids], covered cells)."""
    anims = {}
    covered = {}
    for tid in sorted(ts.tiles):
        t = ts.tiles[tid]
        if len(t.animation) < 2:
            continue
        columns = godot_animation_columns(ts, t)
        if columns is None:
            ts.warn('Godot: the animation of tile %d is left out: Godot needs its frames next '
                    'to each other in the atlas, starting with tile %d.' % (tid, tid))
            continue
        cells = [f for f, _ in t.animation[1:]]
        clash = [c for c in cells if c in covered or c in anims]
        if clash or tid in covered:
            ts.warn('Godot: the animation of tile %d is left out: its frames overlap another '
                    'animation.' % tid)
            continue
        anims[tid] = columns
        for c in cells:
            covered[c] = tid
    tiles = []
    for tid in range(ts.layout.tile_count):
        if tid in covered:
            t = ts.tiles.get(tid)
            if t is not None and t.has_data() and tid != covered[tid]:
                ts.warn('Godot: tile %d is a frame of the animation of tile %d, so its own '
                        'class, properties and collision are left out (Godot keeps them for '
                        'the first frame only).' % (tid, covered[tid]))
            continue
        t = ts.tiles.get(tid)
        if t is None or (skip_empty and t.empty and not t.has_data()):
            continue
        tiles.append(tid)
    return anims, tiles, covered


def write_tres(ts, texture_path, texture_uid=None, resource_uid=None, skip_empty=True):
    """A Godot 4 TileSet resource (text format 3, as Godot 4.7 writes
    it) with one TileSetAtlasSource on the tileset PNG."""
    lay = ts.layout
    layers = godot_custom_layers(ts)
    anims, tile_ids, covered = godot_plan(ts, skip_empty)
    has_physics = any(ts.tiles[t].polygons for t in tile_ids if t in ts.tiles)
    head = '[gd_resource type="TileSet" format=3'
    if resource_uid:
        head += ' uid="%s"' % resource_uid
    lines = [head + ']', '']
    ext = '[ext_resource type="Texture2D"'
    if texture_uid:
        ext += ' uid="%s"' % texture_uid
    ext += ' path=%s id="1_texture"]' % godot_string(texture_path)
    lines += [ext, '']
    lines.append('[sub_resource type="TileSetAtlasSource" id="TileSetAtlasSource_1"]')
    lines.append('texture = ExtResource("1_texture")')
    if lay.margin:
        lines.append('margins = Vector2i(%d, %d)' % (lay.margin, lay.margin))
    if lay.spacing:
        lines.append('separation = Vector2i(%d, %d)' % (lay.spacing, lay.spacing))
    lines.append('texture_region_size = Vector2i(%d, %d)' % (lay.tile_w, lay.tile_h))
    half_w, half_h = lay.tile_w / 2.0, lay.tile_h / 2.0
    for tid in tile_ids:
        col, row = lay.col_row(tid)
        key = '%d:%d' % (col, row)
        t = ts.tiles.get(tid)
        if tid in anims:
            lines.append('%s/animation_columns = %d' % (key, anims[tid]))
            for i, (_, ms) in enumerate(t.animation):
                lines.append('%s/animation_frame_%d/duration = %s' %
                             (key, i, godot_float(ms / 1000.0)))
        lines.append('%s/0 = 0' % key)
        if t is None:
            continue
        if t.probability is not None and t.probability != 1.0:
            lines.append('%s/0/probability = %s' % (key, godot_float(t.probability)))
        for i, poly in enumerate(t.polygons):
            # Godot's tile polygons are centred on the tile
            pts = ', '.join('%s, %s' % (fmt_number(x - half_w), fmt_number(y - half_h))
                            for x, y in poly)
            lines.append('%s/0/physics_layer_0/polygon_%d/points = PackedVector2Array(%s)' %
                         (key, i, pts))
        for index, (name, type_) in enumerate(layers):
            if name == GODOT_CLASS_LAYER and index == 0 and layers[0][0] == GODOT_CLASS_LAYER:
                if t.cls:
                    lines.append('%s/0/custom_data_%d = %s' % (key, index, godot_string(t.cls)))
                continue
            p = t.props.get(name)
            if p is not None:
                lines.append('%s/0/custom_data_%d = %s' %
                             (key, index, godot_value(type_, _godot_convert(p, type_))))
    lines += ['', '[resource]']
    lines.append('tile_size = Vector2i(%d, %d)' % (lay.tile_w, lay.tile_h))
    if has_physics:
        lines.append('physics_layer_0/collision_layer = 1')
    for index, (name, type_) in enumerate(layers):
        lines.append('custom_data_layer_%d/name = %s' % (index, godot_string(name)))
        lines.append('custom_data_layer_%d/type = %d' % (index, GODOT_TYPES[type_]))
    lines.append('sources/0 = SubResource("TileSetAtlasSource_1")')
    return '\n'.join(lines) + '\n'


def write_godot_import(uid):
    """A .png.import for a new texture in a Godot project: lossless, no
    mipmaps, never switched to VRAM compression for 3D. Godot 4.7 imports
    the PNG with these settings and keeps the uid (tested); it fills in
    the rest of the file itself."""
    return ('[remap]\n\nimporter="texture"\ntype="CompressedTexture2D"\nuid="%s"\n\n'
            '[params]\n\ncompress/mode=0\nmipmaps/generate=false\ndetect_3d/compress_to=0\n'
            % uid)


def read_uid(path, section_line_re=re.compile(r'^\s*uid\s*=\s*"(uid://[a-z0-9]+)"', re.M)):
    """The uid in a .import file, or None."""
    try:
        with open(path, encoding='utf-8') as f:
            m = section_line_re.search(f.read())
    except OSError:
        return None
    return m.group(1) if m else None


def read_tres_uid(path):
    """The uid in the header of an existing .tres, or None."""
    try:
        with open(path, encoding='utf-8') as f:
            first = f.readline()
    except OSError:
        return None
    m = re.search(r'\buid="(uid://[a-z0-9]+)"', first)
    return m.group(1) if m else None


def find_godot_project(folder):
    """The folder of the project.godot above (or at) folder, or None."""
    folder = os.path.abspath(folder)
    while True:
        if os.path.isfile(os.path.join(folder, 'project.godot')):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent


# ------------------------------------------- what the editors add

def keep_tiled_wangsets(text, path, kind):
    """The new .tsx or .tsj, with the Wang (terrain) sets of the file it
    replaces: those are made in Tiled, not in GIMP."""
    try:
        with open(path, encoding='utf-8') as f:
            old = f.read()
    except OSError:
        return text
    if kind == 'tsx':
        m = re.search(r'\n( *<wangsets>.*?</wangsets>)\n', old, re.S)
        if not m:
            return text
        return text.replace('\n</tileset>', '\n' + m.group(1) + '\n</tileset>', 1)
    try:
        old_d = json.loads(old)
        new_d = json.loads(text)
    except ValueError:
        return text
    if 'wangsets' not in old_d:
        return text
    new_d['wangsets'] = old_d['wangsets']
    return json.dumps(new_d, indent=1, ensure_ascii=False) + '\n'


TERRAIN_TILE_RE = re.compile(r'^(\d+:\d+)/\d+/(terrain_set|terrain|terrains_peering_bit/\w+) = ')
TERRAIN_SET_RE = re.compile(r'^terrain_set_\d+/')


def keep_godot_terrains(text, path):
    """The new .tres with the terrains of the file it replaces (made in
    Godot's TileSet editor): the terrain sets of the TileSet and the
    terrain settings of the tiles that are still there."""
    try:
        with open(path, encoding='utf-8') as f:
            old = f.read().splitlines()
    except OSError:
        return text
    tile_lines = [l for l in old if TERRAIN_TILE_RE.match(l)]
    set_lines = [l for l in old if TERRAIN_SET_RE.match(l)]
    if not tile_lines and not set_lines:
        return text
    lines = text.splitlines()
    present = set()
    for l in lines:
        m = re.match(r'^(\d+:\d+)/0 = 0$', l)
        if m:
            present.add(m.group(1))
    # the tiles' terrain lines at the end of the atlas source, the sets
    # before the sources in the TileSet
    out = []
    in_atlas = False
    for l in lines:
        if l.startswith('[sub_resource type="TileSetAtlasSource"'):
            in_atlas = True
        elif l.startswith('[') and in_atlas:
            # the blank line before the next section
            if out and out[-1] == '':
                out.pop()
            out += [t for t in tile_lines if TERRAIN_TILE_RE.match(t).group(1) in present]
            out.append('')
            in_atlas = False
        if l.startswith('sources/0 = '):
            out += set_lines
        out.append(l)
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------- the files

def write_atomic(path, data):
    """Writes the file next to its place and renames it there, so that a
    program watching it never reads half a file."""
    folder = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(folder, '.%s.%s.tmp' % (os.path.basename(path), secrets.token_hex(4)))
    mode = 'w' if isinstance(data, str) else 'wb'
    try:
        with open(tmp, mode, **({'encoding': 'utf-8', 'newline': '\n'} if mode == 'w' else {})) \
                as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ------------------------------------------------------------ extrusion

def extrude_layout(layout, extrude):
    """The layout of the tiles after extrusion: each tile gets a border of
    extrude pixels copied from its edge; the margin is then extrude and
    the spacing twice that (the old margin and spacing are dropped)."""
    margin = extrude
    spacing = 2 * extrude
    w = 2 * margin + layout.columns * layout.tile_w + (layout.columns - 1) * spacing
    h = 2 * margin + layout.rows * layout.tile_h + (layout.rows - 1) * spacing
    return Layout(w, h, layout.tile_w, layout.tile_h, margin, spacing)


def extrude_pixels(src, src_w, bpp, layout, new_layout, extrude):
    """The pixels of the extruded image (bytes, bpp bytes per pixel, rows
    of src_w pixels in src): each tile at its new place, with its edge
    pixels repeated outward; the rest transparent (zero)."""
    nw, nh = new_layout.image_w, new_layout.image_h
    out = bytearray(nw * nh * bpp)
    tw, th = layout.tile_w, layout.tile_h
    for row in range(layout.rows):
        for col in range(layout.columns):
            sx, sy = layout.cell_origin(col, row)
            dx, dy = new_layout.cell_origin(col, row)
            for y in range(-extrude, th + extrude):
                yy = min(max(y, 0), th - 1)
                s = ((sy + yy) * src_w + sx) * bpp
                line = src[s:s + tw * bpp]
                left = line[:bpp] * extrude
                right = line[-bpp:] * extrude
                d = ((dy + y) * nw + dx - extrude) * bpp
                out[d:d + (tw + 2 * extrude) * bpp] = left + line + right
    return bytes(out)
