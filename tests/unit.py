#!/usr/bin/env python3
# Tests of the parts of Tileset Export that need no GIMP
# (tileset-export/tileset_model.py): the labels, the layout, the
# geometry, the writers. Run by tests/run.sh, or alone:
#
#   python3 tests/unit.py
#
# Prints "TSE PASS unit <test>" or "TSE FAIL unit <test>: <why>".
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import math
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tileset-export'))
import tileset_model as tm     # noqa: E402

failures = 0
tests = []


def test(func):
    tests.append(func)
    return func


def eq(a, b, what=''):
    if a != b:
        raise AssertionError('%s%r, not %r' % (what + ': ' if what else '', a, b))


def P(name, t, v):
    return tm.Prop(name, t, v)


@test
def label_types():
    l = tm.parse_label('Grass solid=true speed=1.5 hp=3 tint=#ff8000 argb=#80ff0000 '
                       'name="Big Rock" word=hello')
    eq(l.cls, 'Grass')
    eq(l.props, {'solid': P('solid', 'bool', True), 'speed': P('speed', 'float', 1.5),
                 'hp': P('hp', 'int', 3), 'tint': P('tint', 'color', (255, 128, 0, 255)),
                 'argb': P('argb', 'color', (255, 0, 0, 128)),
                 'name': P('name', 'string', 'Big Rock'), 'word': P('word', 'string', 'hello')})
    eq(l.errors, [])


@test
def label_explicit_types_and_quotes():
    l = tm.parse_label('n:string=3 f:float=2 b:bool=yes c:color=#000000 path:file=a/b.png '
                       'q="true" e=\'say "hi"\' esc="a\\"b"')
    eq(l.props['n'], P('n', 'string', '3'))
    eq(l.props['f'], P('f', 'float', 2.0))
    eq(l.props['b'], P('b', 'bool', True))
    eq(l.props['c'], P('c', 'color', (0, 0, 0, 255)))
    eq(l.props['path'], P('path', 'file', 'a/b.png'))
    eq(l.props['q'], P('q', 'string', 'true'))
    eq(l.props['e'], P('e', 'string', 'say "hi"'))
    eq(l.props['esc'], P('esc', 'string', 'a"b'))


@test
def label_class_probability_suffixes():
    l = tm.parse_label('class=Water probability=0.25 deep=true #3')
    eq((l.cls, l.probability, list(l.props)), ('Water', 0.25, ['deep']))
    eq(tm.parse_label('Rock copy').cls, 'Rock')
    eq(tm.parse_label('Rock copy #2').cls, 'Rock')
    eq(tm.parse_label('solid=true').cls, '')


@test
def label_errors():
    eq(tm.parse_label('a b').errors, ['"b": a word without "=" (only the first word is the '
                                      'class)'])
    eq(tm.parse_label('x:int=abc').errors, ['x: "abc" is not of type int'])
    eq(tm.parse_label('x:vec=1').errors[0][:24], 'x: unknown type "vec" (o')
    eq(tm.parse_label('k="open').errors, ['a quote is not closed: k="open'])
    eq(tm.parse_label('probability=-1').errors, ['probability: "-1" is not a number >= 0'])
    eq(tm.parse_label('=3').errors, ['"=3": a property without a name'])


@test
def names():
    eq(tm.anim_name('anim:walk (120ms) #2'), 'walk')
    eq(tm.anim_name('Anim: Water Fall (combine)'), 'Water Fall')
    eq(tm.anim_name('animation'), None)
    eq(tm.duration_ms('frame 3 (80ms)'), 80)
    eq(tm.duration_ms('frame (12.6 ms) (replace)'), 13)
    eq(tm.duration_ms('frame'), None)
    eq(tm.is_properties_group('Tile Properties #1'), True)
    eq(tm.is_properties_group('props'), False)
    eq(tm.tileset_label_text('tileset: Terrain a=1'), ' Terrain a=1')
    eq(tm.is_collision_path('Collision ground'), True)
    eq(tm.is_collision_path('outline'), False)


@test
def layout_counts():
    # as Tiled's Tileset::columnCountForWidth and Godot's
    # get_atlas_grid_size: whole tiles after the left margin
    for w in range(16, 120):
        for m in (0, 1, 3):
            for s in (0, 1, 2):
                if w - m < 16:
                    continue
                lay = tm.Layout(w, 16 + m, 16, 16, m, s)
                cols = (w - m + s) // (16 + s)
                godot = 1 + (w - m - 16) // (16 + s)
                eq(lay.columns, cols)
                eq(lay.columns, godot)
                x0, y0, x1, y1 = lay.cell_rect(lay.columns - 1, 0)
                assert x1 <= w


@test
def layout_cells():
    lay = tm.Layout(69, 52, 16, 16, 1, 1)
    eq((lay.columns, lay.rows, lay.tile_count), (4, 3, 12))
    eq(lay.cell_at(1, 1), (0, 0))
    eq(lay.cell_at(16.99, 16.99), (0, 0))
    eq(lay.cell_at(17, 5), None)            # the spacing
    eq(lay.cell_at(0.5, 5), None)           # the margin
    eq(lay.cell_at(18, 5), (1, 0))
    eq(lay.cell_at(68.5, 5), None)          # right of the last tile
    eq(lay.cells_in_rect(10, 2, 30, 10), [(0, 0), (1, 0)])
    eq(lay.leftover(), (1, 1))
    try:
        tm.Layout(10, 10, 16, 16)
        raise AssertionError('no error for an image smaller than a tile')
    except tm.TilesetError:
        pass


@test
def grid():
    eq(tm.layout_from_grid(69, 52, (17.0, 17.0), (1.0, 1.0), 1), (16, 16, 1, 1))
    eq(tm.layout_from_grid(69, 52, (17.0, 17.0), (18.0, -16.0), 1), (16, 16, 1, 1))
    eq(tm.layout_from_grid(64, 64, (32.0, 16.0), (0.0, 0.0), 0), (32, 16, 0, 0))
    try:
        tm.layout_from_grid(64, 64, (4.0, 4.0), (0, 0), 4)
        raise AssertionError('no error')
    except tm.TilesetError:
        pass


@test
def strokes():
    straight = [1, 1, 1, 1, 1, 1, 7, 1, 7, 1, 7, 1, 7, 7, 7, 7, 7, 7]
    eq(tm.flatten_stroke(straight, True), [(1, 1), (7, 1), (7, 7)])
    # a circle of radius 6 as GIMP makes it (4 Bezier segments)
    k = 0.5522847498 * 6
    cps = []
    for (ax, ay), (hx, hy) in (((6, 0), (0, k)), ((0, 6), (-k, 0)), ((-6, 0), (0, -k)),
                               ((0, -6), (k, 0))):
        cps += [ax - hx, ay - hy, ax, ay, ax + hx, ay + hy]
    pts = tm.flatten_stroke(cps, True, 0.25)
    assert len(pts) >= 8, pts
    for x, y in pts:
        assert abs(math.hypot(x, y) - 6) < 0.3, (x, y)


@test
def clipping():
    lay = tm.Layout(69, 52, 16, 16, 1, 1)
    got = tm.polygons_for_cells([(10, 2), (30, 2), (30, 10), (10, 10)], lay)
    eq(got, {(0, 0): [(9.0, 1.0), (16.0, 1.0), (16.0, 9.0), (9.0, 9.0)],
             (1, 0): [(0.0, 1.0), (12.0, 1.0), (12.0, 9.0), (0.0, 9.0)]})
    # exactly a tile: only that tile, no slivers in the neighbours
    got = tm.polygons_for_cells([(1, 1), (17, 1), (17, 17), (1, 17)], lay)
    eq(list(got), [(0, 0)])
    # a triangle over four tiles
    got = tm.polygons_for_cells([(9, 9), (26, 9), (9, 26)], lay)
    eq(sorted(got), [(0, 0), (0, 1), (1, 0)])
    # outside every tile
    eq(tm.polygons_for_cells([(0, 0), (1, 0), (0, 1)], tm.Layout(40, 40, 16, 16, 4, 0)), {})


@test
def simplify_points():
    eq(tm.simplify([(0, 0), (8, 0), (16, 0), (16, 16), (16, 16), (0, 16), (0, 0)]),
       [(0, 0), (16, 0), (16, 16), (0, 16)])


def uid_to_id(text):
    """ResourceUID::text_to_id of Godot 4.7."""
    n = 0
    for c in text[6:]:
        n = n * 34 + (ord(c) - ord('a') if c.isalpha() else ord(c) - ord('0') + 25)
    return n & 0x7FFFFFFFFFFFFFFF


@test
def uids():
    for n in (0, 1, 33, 34, 2 ** 40 + 5, 2 ** 63 - 1):
        u = tm.godot_uid(n)
        eq(uid_to_id(u), n, u)
    for _ in range(200):
        u = tm.godot_uid()
        assert u.startswith('uid://') and len(u) <= 6 + 13, u
        assert all(c in tm.UID_CHARS for c in u[6:]), u


def small_tileset():
    lay = tm.Layout(64, 32, 16, 16)
    ts = tm.Tileset('t & "x"', 't.png', lay)
    for i in range(lay.tile_count):
        ts.tile(i)
    return ts


@test
def godot_animations():
    ts = small_tileset()
    t = ts.tile(0)
    t.animation = [(0, 100), (1, 100), (2, 100)]
    eq(tm.godot_animation_columns(ts, t), 3)
    t.animation = [(0, 100), (1, 100), (4, 100), (5, 100)]
    eq(tm.godot_animation_columns(ts, t), 2)
    t.animation = [(0, 100), (2, 100)]
    eq(tm.godot_animation_columns(ts, t), None)
    t.animation = [(1, 100), (0, 100)]
    eq(tm.godot_animation_columns(ts, t), None)
    t2 = ts.tile(3)
    t2.animation = [(3, 50), (4, 50)]         # would wrap past the right edge
    eq(tm.godot_animation_columns(ts, t2), None)


@test
def godot_layers():
    ts = small_tileset()
    ts.tile(0).props = {'a': P('a', 'int', 1), 'b': P('b', 'int', 1), 'c': P('c', 'bool', True)}
    ts.tile(1).props = {'a': P('a', 'float', 1.5), 'b': P('b', 'string', 'x')}
    ts.tile(1).cls = 'K'
    eq(tm.godot_custom_layers(ts), [('class', 'string'), ('a', 'float'), ('b', 'string'),
                                    ('c', 'bool')])
    assert any('"b" has values of different types' in w for w in ts.warnings), ts.warnings
    text = tm.write_tres(ts, 'res://t.png')
    assert '0:0/0/custom_data_1 = 1.0' in text, text
    assert '0:0/0/custom_data_2 = "1"' in text, text
    assert '1:0/0/custom_data_0 = "K"' in text, text


@test
def godot_text():
    ts = small_tileset()
    ts.tile(0).props = {'s': P('s', 'string', 'a "q" \\ \n b')}
    ts.tile(0).polygons = [[(0, 0), (16, 0), (8, 16)]]
    ts.tile(5).empty = True
    text = tm.write_tres(ts, 'res://a b/t.png', 'uid://abc', 'uid://def')
    assert text.startswith('[gd_resource type="TileSet" format=3 uid="uid://def"]\n'), text
    assert '[ext_resource type="Texture2D" uid="uid://abc" path="res://a b/t.png" ' \
           'id="1_texture"]' in text, text
    assert r'0:0/0/custom_data_0 = "a \"q\" \\ \n b"' in text, text
    assert '0:0/0/physics_layer_0/polygon_0/points = PackedVector2Array(-8, -8, 8, -8, 0, 8)' \
        in text, text
    assert '1:1/0 = 0' not in text, 'an empty tile is in the atlas'
    assert 'tile_size = Vector2i(16, 16)' in text and 'margins' not in text, text


@test
def tsx_text():
    ts = small_tileset()
    ts.cls = 'A<B'
    ts.props = {'n': P('n', 'string', 'x&y\nz')}
    ts.tile(1).cls = 'Q"'
    ts.tile(1).probability = 0.3
    ts.tile(2).polygons = [[(1.5, 2.25), (4, 2.25), (4, 8)]]
    root = ET.fromstring(tm.write_tsx(ts))
    eq(root.get('name'), 't & "x"')
    eq(root.get('class'), 'A<B')
    eq(root.find('properties/property').text, 'x&y\nz')
    tiles = root.findall('tile')
    eq([t.get('id') for t in tiles], ['1', '2'])
    eq((tiles[0].get('type'), tiles[0].get('probability')), ('Q"', '0.3'))
    obj = tiles[1].find('objectgroup/object')
    eq((obj.get('x'), obj.get('y'), obj.find('polygon').get('points')),
       ('1.5', '2.25', '0,0 2.5,0 2.5,5.75'))
    d = json.loads(tm.write_tsj(ts))
    eq(d['tiles'][1]['objectgroup']['objects'][0]['polygon'],
       [{'x': 0.0, 'y': 0.0}, {'x': 2.5, 'y': 0.0}, {'x': 2.5, 'y': 5.75}])


@test
def extrusion():
    # 2 x 1 tiles of 2x2, margin 1, spacing 1, one byte per pixel
    lay = tm.Layout(6, 4, 2, 2, 1, 1)
    src = bytes([0, 0, 0, 0, 0, 0,
                 0, 1, 2, 0, 5, 6,
                 0, 3, 4, 0, 7, 8,
                 0, 0, 0, 0, 0, 0])
    new = tm.extrude_layout(lay, 1)
    eq((new.image_w, new.image_h, new.margin, new.spacing), (8, 4, 1, 2))
    out = tm.extrude_pixels(src, 6, 1, lay, new, 1)
    eq(list(out), [1, 1, 2, 2, 5, 5, 6, 6,
                   1, 1, 2, 2, 5, 5, 6, 6,
                   3, 3, 4, 4, 7, 7, 8, 8,
                   3, 3, 4, 4, 7, 7, 8, 8])


@test
def atomic_write():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'a.tsx')
        tm.write_atomic(p, 'one')
        ino = os.stat(p).st_ino
        tm.write_atomic(p, 'two')
        eq(open(p).read(), 'two')
        assert os.stat(p).st_ino != ino, 'written in place'
        eq(os.listdir(d), ['a.tsx'])


@test
def kept_from_editors():
    with tempfile.TemporaryDirectory() as d:
        old = os.path.join(d, 'x.tsx')
        with open(old, 'w') as f:
            f.write('<tileset>\n <image/>\n <wangsets>\n  <wangset name="w"/>\n </wangsets>\n'
                    '</tileset>\n')
        new = tm.keep_tiled_wangsets('<tileset>\n <image/>\n</tileset>\n', old, 'tsx')
        eq(new, '<tileset>\n <image/>\n <wangsets>\n  <wangset name="w"/>\n </wangsets>\n'
                '</tileset>\n')
        tres = os.path.join(d, 'x.tres')
        with open(tres, 'w') as f:
            f.write('[sub_resource type="TileSetAtlasSource" id="A"]\n0:0/0 = 0\n'
                    '0:0/0/terrain_set = 0\n0:0/0/terrain = 0\n5:5/0/terrain_set = 0\n\n'
                    '[resource]\nterrain_set_0/mode = 0\nterrain_set_0/terrain_0/name = "g"\n'
                    'sources/0 = SubResource("A")\n')
        new = tm.keep_godot_terrains(
            '[sub_resource type="TileSetAtlasSource" id="B"]\n0:0/0 = 0\n\n[resource]\n'
            'tile_size = Vector2i(16, 16)\nsources/0 = SubResource("B")\n', tres)
        eq(new, '[sub_resource type="TileSetAtlasSource" id="B"]\n0:0/0 = 0\n'
                '0:0/0/terrain_set = 0\n0:0/0/terrain = 0\n\n[resource]\n'
                'tile_size = Vector2i(16, 16)\nterrain_set_0/mode = 0\n'
                'terrain_set_0/terrain_0/name = "g"\nsources/0 = SubResource("B")\n')


@test
def godot_project_search():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, 'p', 'a', 'b'))
        open(os.path.join(d, 'p', 'project.godot'), 'w').close()
        eq(tm.find_godot_project(os.path.join(d, 'p', 'a', 'b')), os.path.join(d, 'p'))
        eq(tm.find_godot_project(d), None)


for func in tests:
    try:
        func()
        print('TSE PASS unit %s' % func.__name__)
    except Exception as e:
        failures += 1
        print('TSE FAIL unit %s: %s' % (func.__name__, e))
print('TSE unit failures: %d' % failures)
sys.exit(1 if failures else 0)
