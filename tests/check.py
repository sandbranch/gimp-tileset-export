#!/usr/bin/env python3
# Checks the exports that tests/gimp-build.py made, outside GIMP (run by
# tests/run.sh): the PNGs pixel by pixel, the .tsx and .tsj as Tiled
# 1.12's own reader sees them (tiled --evaluate) and against Tiled's own
# writer, a map drawn with them by tmxrasterizer against a golden PNG,
# and the .tres as Godot 4.7 sees it (a Godot without a window, with its
# own throwaway HOME).
#
#   tests/check.py 1    after the first GIMP run (also has Godot add a
#                       terrain for the second)
#   tests/check.py 2    after the second GIMP run
#
# Prints "TSE PASS <what>", "TSE FAIL <what>: <why>" or "TSE SKIP <what>:
# <why>" and "TSE check failures: <n>" at the end. Needs no network.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'output')
CASES = os.path.join(OUT, 'cases')
PROJECT = os.path.join(OUT, 'godot', 'project')
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(SRC, 'tileset-export'))
import fixtures as fx          # noqa: E402
import pngread                 # noqa: E402
import tileset_model as tm     # noqa: E402

PHASE = sys.argv[1] if len(sys.argv) > 1 else '1'
failures = 0


class Fail(Exception):
    pass


class Skip(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


def run(name, func, *args):
    global failures
    try:
        func(*args)
        print('TSE PASS %s' % name, flush=True)
    except Skip as e:
        print('TSE SKIP %s: %s' % (name, e), flush=True)
    except Fail as e:
        failures += 1
        print('TSE FAIL %s: %s' % (name, e), flush=True)
    except Exception as e:
        failures += 1
        import traceback
        traceback.print_exc()
        print('TSE FAIL %s: %r' % (name, e), flush=True)


def case(*parts):
    return os.path.join(CASES, *parts)


# ---------------------------------------------------------------- Tiled

TILED = os.environ.get('TSE_TILED') or os.path.join(OUT, 'apps', 'tiled', 'AppRun')
TILED_HOME = os.path.join(OUT, 'tiled-home')


def have_tiled():
    return os.access(TILED, os.X_OK) and os.path.exists(
        os.path.join(os.path.dirname(TILED), 'usr', 'plugins', 'platforms', 'libqoffscreen.so'))


def tiled_env():
    os.makedirs(TILED_HOME, exist_ok=True)
    return {'PATH': '/usr/bin:/bin', 'HOME': TILED_HOME, 'LANG': 'C.UTF-8',
            'XDG_CONFIG_HOME': os.path.join(TILED_HOME, '.config'),
            'XDG_DATA_HOME': os.path.join(TILED_HOME, '.local', 'share'),
            'XDG_CACHE_HOME': os.path.join(TILED_HOME, '.cache'),
            'XDG_STATE_HOME': os.path.join(TILED_HOME, '.local', 'state'),
            'XDG_RUNTIME_DIR': os.path.join(TILED_HOME, 'run'),
            'QT_QPA_PLATFORM': 'offscreen'}


def tiled(*args):
    if not have_tiled():
        raise Skip('no Tiled 1.12.2 with the offscreen plug-in (run tests/get-tiled.sh once)')
    env = tiled_env()
    os.makedirs(env['XDG_RUNTIME_DIR'], mode=0o700, exist_ok=True)
    p = subprocess.run([TILED] + list(args), env=env, capture_output=True, text=True,
                       timeout=120)
    return p


def tiled_dump(path, write=None):
    args = ['--evaluate', os.path.join(HERE, 'tiled', 'dump.js'), path]
    if write:
        args.append(write)
    p = tiled(*args)
    out = p.stdout + p.stderr
    m = re.search(r'^TSEJSON (.*)$', out, re.M)
    check(m, 'Tiled printed no result for %s: %s' % (path, out[-800:]))
    if write:
        check('TSEWRITE ok' in out, 'Tiled did not write %s: %s' % (write, out[-400:]))
    return json.loads(m.group(1))


def rounded(v):
    """The value with its floats rounded to 3 decimals."""
    if isinstance(v, float):
        return round(v, 3) + 0.0
    if isinstance(v, dict):
        return {k: rounded(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [rounded(x) for x in v]
    return v


def norm_poly(pts):
    """A polygon as a comparable value: the points rounded, starting with
    the smallest, in the same direction."""
    pts = [(round(x, 2) + 0.0, round(y, 2) + 0.0) for x, y in pts]
    i = pts.index(min(pts))
    return tuple(pts[i:] + pts[:i])


def check_circle(pts, cx, cy, r, what):
    check(len(pts) >= 8, '%s: %d points' % (what, len(pts)))
    for x, y in pts:
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        check(abs(d - r) <= 0.3, '%s: point %s is %.2f from the centre' % (what, (x, y), d))


def check_tiled_main(d, what):
    e = fx.EXPECT_MAIN
    for key, want in (('name', e['name']), ('className', e['class']),
                      ('tileWidth', 16), ('tileHeight', 16), ('margin', 1), ('tileSpacing', 1),
                      ('columnCount', 4), ('tileCount', 12), ('imageWidth', 69),
                      ('imageHeight', 52)):
        check(d[key] == want, '%s: %s is %r, not %r' % (what, key, d[key], want))
    check(d['properties'] == {'author': ['string', 'David']},
          '%s: tileset properties %s' % (what, d['properties']))
    for tid in range(12):
        t = d['tiles'][str(tid)]
        want = e['tiles'].get(tid, {})
        check(t['className'] == want.get('class', ''), '%s: tile %d class %r' %
              (what, tid, t['className']))
        check(abs(t['probability'] - want.get('probability', 1.0)) < 1e-9,
              '%s: tile %d probability %r' % (what, tid, t['probability']))
        props = {}
        for k, (typ, v) in want.get('properties', {}).items():
            js = {'string': 'string', 'bool': 'boolean', 'int': 'number', 'float': 'number',
                  'color': 'object'}[typ]
            props[k] = [js, v]
        check(t['properties'] == props, '%s: tile %d properties %s, not %s' %
              (what, tid, t['properties'], props))
        objects = t.get('objects', [])
        if 'circle' in want:
            check(len(objects) == 1, '%s: tile %d has %d objects' % (what, tid, len(objects)))
            check(objects[0]['shape'] == 1, '%s: tile %d: not a polygon' % (what, tid))
            check_circle(objects[0]['polygon'], *want['circle'], what='%s tile %d' % (what, tid))
        else:
            got = sorted(norm_poly(o['polygon']) for o in objects)
            exp = sorted(norm_poly(p) for p in want.get('polygons', []))
            check(got == exp, '%s: tile %d polygons %s, not %s' % (what, tid, got, exp))
            check(all(o['shape'] == 1 for o in objects), '%s: tile %d: not polygons' % (what, tid))
        frames = [tuple(f) for f in t.get('frames', [])]
        check(frames == want.get('animation', []), '%s: tile %d frames %s' % (what, tid, frames))


def canonical_tsx(path):
    """What a .tsx holds, independent of how it is written: attributes
    Tiled adds (tiledversion) and the order of things left out."""
    root = ET.parse(path).getroot()
    ts = dict(root.attrib)
    ts.pop('tiledversion', None)
    ts.pop('version', None)
    out = {'tileset': ts, 'tiles': {}}

    def props(el):
        p = el.find('properties')
        if p is None:
            return {}
        return {q.get('name'): (q.get('type', 'string'), q.get('value', q.text))
                for q in p.findall('property')}
    out['properties'] = props(root)
    out['image'] = dict(root.find('image').attrib)
    out['image']['source'] = os.path.basename(out['image']['source'])
    for t in root.findall('tile'):
        td = {k: v for k, v in t.attrib.items() if k != 'id'}
        td['properties'] = props(t)
        og = t.find('objectgroup')
        if og is not None:
            td['objects'] = []
            for o in og.findall('object'):
                poly = o.find('polygon')
                ox, oy = float(o.get('x')), float(o.get('y'))
                pts = [tuple(float(v) for v in p.split(',')) for p in poly.get('points').split()]
                td['objects'].append(norm_poly([(x + ox, y + oy) for x, y in pts]))
        anim = t.find('animation')
        if anim is not None:
            td['frames'] = [(f.get('tileid'), f.get('duration')) for f in anim.findall('frame')]
        out['tiles'][t.get('id')] = td
    return out


def tiled_main():
    d = tiled_dump(case('main', 'main.tsx'))
    check_tiled_main(d, 'main.tsx')


def tiled_main_tsj():
    d = tiled_dump(case('main', 'main.tsj'))
    check_tiled_main(d, 'main.tsj')
    t = tiled_dump(case('main', 'main.tsx'))
    d.pop('image')
    t.pop('image')
    check(rounded(d) == rounded(t), 'the .tsj and the .tsx differ in Tiled')


def tiled_writer():
    """Tiled reads our .tsx and writes it again with its own writer: the
    same content, and Tiled reads its own file as it read ours."""
    ours = case('main', 'main.tsx')
    theirs = os.path.join(OUT, 'tiled-rewrite', 'main.tsx')
    os.makedirs(os.path.dirname(theirs), exist_ok=True)
    shutil.copy(case('main', 'main.png'), os.path.join(OUT, 'tiled-rewrite', 'main.png'))
    d1 = tiled_dump(ours, theirs)
    a, b = canonical_tsx(ours), canonical_tsx(theirs)
    check(a == b, 'Tiled writes it differently:\nours   %s\nTiled  %s' % (a, b))
    d2 = tiled_dump(theirs)
    d1.pop('image')
    d2.pop('image')
    check(rounded(d1) == rounded(d2), 'Tiled reads its own file differently')
    # and its JSON writer against ours
    tsj = os.path.join(OUT, 'tiled-rewrite', 'main.tsj')
    tiled_dump(ours, tsj)
    theirs_j = json.load(open(tsj))
    ours_j = json.load(open(case('main', 'main.tsj')))
    theirs_j['image'] = os.path.basename(theirs_j['image'])
    for key in ('tilewidth', 'tileheight', 'margin', 'spacing', 'tilecount', 'columns',
                'imagewidth', 'imageheight', 'image', 'class', 'properties', 'name', 'type'):
        check(ours_j.get(key) == theirs_j.get(key), '.tsj %s: ours %r, Tiled %r' %
              (key, ours_j.get(key), theirs_j.get(key)))
    for to, tt in zip(ours_j['tiles'], theirs_j['tiles']):
        for key in ('id', 'type', 'probability', 'properties', 'animation'):
            check(to.get(key) == tt.get(key), '.tsj tile %s %s: ours %r, Tiled %r' %
                  (to['id'], key, to.get(key), tt.get(key)))
        if 'objectgroup' in to:
            po = [o['polygon'] for o in to['objectgroup']['objects']]
            pt = [o['polygon'] for o in tt['objectgroup']['objects']]
            check(po == pt, '.tsj tile %s polygons differ' % to['id'])


def write_map(folder, tsx, name='map'):
    rows = fx.MAP
    data = ','.join(str(t + 1 if t >= 0 else 0) for row in rows for t in row)
    path = os.path.join(folder, name + '.tmx')
    with open(path, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<map version="1.10" orientation="orthogonal" renderorder="right-down" '
                'width="%d" height="%d" tilewidth="16" tileheight="16" infinite="0" '
                'nextlayerid="2" nextobjectid="1">\n'
                ' <tileset firstgid="1" source="%s"/>\n'
                ' <layer id="1" name="ground" width="%d" height="%d">\n'
                '  <data encoding="csv">%s</data>\n </layer>\n</map>\n' %
                (len(rows[0]), len(rows), tsx, len(rows[0]), len(rows), data))
    return path


def rasterize(folder, tsx):
    tmx = write_map(folder, tsx)
    png = os.path.join(folder, 'map-render.png')
    if os.path.exists(png):
        os.unlink(png)
    p = tiled('tmxrasterizer', tmx, png)
    check(p.returncode == 0 and os.path.exists(png),
          'tmxrasterizer failed: %s' % (p.stdout + p.stderr)[-500:])
    return pngread.PNG(png)


def compare(img, want, what, tol=0):
    """want: a function (x, y) -> rgba, or a PNG."""
    get = want.rgba if isinstance(want, pngread.PNG) else want
    for y in range(img.height):
        for x in range(img.width):
            a, b = img.rgba(x, y), get(x, y)
            if a[3] == 0 and b[3] == 0:
                continue
            if any(abs(p - q) > tol for p, q in zip(a, b)):
                raise Fail('%s: pixel %d,%d is %s, not %s' % (what, x, y, a, b))


def tiled_render_golden():
    img = rasterize(case('main'), 'main.tsx')
    golden = pngread.PNG(os.path.join(HERE, 'golden', 'main-map.png'))
    check((img.width, img.height) == (golden.width, golden.height),
          'size %dx%d' % (img.width, img.height))
    compare(img, golden, 'the map against tests/golden/main-map.png')


def tiles_from_png(png, layout):
    """What a map of fx.MAP drawn with the tileset PNG looks like, cut out
    of the PNG itself: to check Tiled's reading of every kind of PNG."""
    def pixel(x, y):
        tid = fx.MAP[y // layout.tile_h][x // layout.tile_w]
        if tid < 0:
            return (0, 0, 0, 0)
        ox, oy = layout.cell_origin(*layout.col_row(tid))
        return png.rgba(ox + x % layout.tile_w, oy + y % layout.tile_h)
    return pixel


def tiled_render_kind(name):
    img = rasterize(case(name), name + '.tsx')
    png = pngread.PNG(case(name, name + '.png'))
    lay = tm.Layout(69, 52, 16, 16, 1, 1)
    compare(img, tiles_from_png(png, lay), '%s: the map' % name, tol=1)


def tiled_other(name, file, want):
    d = tiled_dump(case(name, file))
    for key, value in want.items():
        if key == 'tiles':
            for tid, td in value.items():
                t = d['tiles'][str(tid)]
                for k, v in td.items():
                    got = t.get(k)
                    if k == 'objects':
                        got = [norm_poly(o['polygon']) for o in t.get('objects', [])]
                        v = [norm_poly(p) for p in v]
                    check(got == v, '%s tile %s %s: %r, not %r' % (name, tid, k, got, v))
            continue
        check(d[key] == value, '%s: %s is %r, not %r' % (name, key, d[key], value))


# ---------------------------------------------------------------- PNGs

def main_png_pixels(png, name, tol=0, gray=False):
    for tid in range(12):
        ox, oy = fx.cell_origin(tid)
        for dx, dy in ((0, 0), (15, 15), (7, 9)):
            got = png.rgba(ox + dx, oy + dy)
            if tid in fx.EMPTY_TILES:
                check(got[3] == 0, '%s: tile %d is not empty at %d,%d: %s' %
                      (name, tid, dx, dy, got))
                continue
            want = fx.COLORS[tid] + (255,)
            if gray:
                check(got[3] == 255 and got[0] == got[1] == got[2],
                      '%s: tile %d: %s' % (name, tid, got))
                continue
            check(all(abs(a - b) <= tol for a, b in zip(got, want)),
                  '%s: tile %d at %d,%d is %s, not %s' % (name, tid, dx, dy, got, want))
    # the spacing and the margin are transparent
    for x, y in ((0, 0), (17, 5), (5, 17), (68, 51)):
        check(png.rgba(x, y)[3] == 0, '%s: %d,%d is not transparent' % (name, x, y))


def png_main():
    png = pngread.PNG(case('main', 'main.png'))
    check((png.width, png.height, png.bit_depth, png.color_type) == (69, 52, 8, 6),
          'main.png is %dx%d, %d bit, type %d' % (png.width, png.height, png.bit_depth,
                                                 png.color_type))
    main_png_pixels(png, 'main.png')
    check('tIME' not in png.chunks, 'main.png has a time stamp')


def png_kind(name, depth, ctype, tol=0, gray=False):
    png = pngread.PNG(case(name, name + '.png'))
    check((png.width, png.height) == (69, 52), '%s is %dx%d' % (name, png.width, png.height))
    check((png.bit_depth, png.color_type) == (depth, ctype),
          '%s: %d bit, colour type %d, not %d bit, type %d' %
          (name, png.bit_depth, png.color_type, depth, ctype))
    main_png_pixels(png, name, tol, gray)


def png_offsets():
    png = pngread.PNG(case('layer_offsets', 'offsets.png'))
    check((png.width, png.height) == (32, 32), 'size %dx%d' % (png.width, png.height))
    for (x, y), want in (((0, 0), (255, 0, 0, 255)), ((19, 19), (255, 0, 0, 255)),
                         ((20, 20), (0, 0, 255, 255)), ((27, 27), (0, 0, 255, 255)),
                         ((29, 5), (255, 0, 0, 255)), ((30, 30), None), ((31, 0), None)):
        got = png.rgba(x, y)
        if want is None:
            check(got[3] == 0, '%d,%d is %s, not transparent' % (x, y, got))
        else:
            check(got == want, '%d,%d is %s, not %s' % (x, y, got, want))


def png_unequal_offset():
    png = pngread.PNG(case('unequal_offset', 'uo.png'))
    check((png.width, png.height) == (33, 33), 'size %dx%d' % (png.width, png.height))
    check(png.rgba(0, 5) == (255, 0, 0, 255), 'the margin: %s' % (png.rgba(0, 5),))
    check(png.rgba(1, 1) == (0, 255, 0, 255), 'tile 0: %s' % (png.rgba(1, 1),))
    check(png.rgba(17, 17) == (0, 0, 255, 255), 'tile 3: %s' % (png.rgba(17, 17),))


def png_layer_source():
    png = pngread.PNG(case('layer_source', 'ls.png'))
    check(png.rgba(3, 3)[3] == 0, 'the other group is in it: %s' % (png.rgba(3, 3),))
    check(png.rgba(20, 3) == (0, 0, 255, 255), 'the chosen group: %s' % (png.rgba(20, 3),))


def png_extrude():
    main = pngread.PNG(case('main', 'main.png'))
    ex = pngread.PNG(case('extrude', 'ex.png'))
    lay = tm.Layout(69, 52, 16, 16, 1, 1)
    new = tm.extrude_layout(lay, 2)
    check((ex.width, ex.height) == (new.image_w, new.image_h) == (80, 60),
          'size %dx%d' % (ex.width, ex.height))
    src = b''.join(bytes(main.rgba(x, y)) for y in range(main.height) for x in range(main.width))
    want = tm.extrude_pixels(src, main.width, 4, lay, new, 2)

    def pixel(x, y):
        i = (y * new.image_w + x) * 4
        return tuple(want[i:i + 4])
    compare(ex, pixel, 'ex.png against the extrusion computed from main.png')
    # and by hand: the pixel left of tile 0 is tile 0's edge
    check(ex.rgba(0, 2) == fx.COLORS[0] + (255,), 'the extruded edge: %s' % (ex.rgba(0, 2),))


# ---------------------------------------------------------------- Godot

GODOT_HOME = os.path.join(OUT, 'godot', 'home')


def godot_cmd():
    native = os.environ.get('TSE_GODOT')
    if native:
        return None, native
    p = subprocess.run(['flatpak', 'info', 'org.godotengine.Godot'], capture_output=True)
    if p.returncode != 0:
        return None, None
    return 'flatpak', None


def godot(*args):
    kind, native = godot_cmd()
    if kind is None and native is None:
        raise Skip('no Godot (the Flatpak org.godotengine.Godot, or TSE_GODOT)')
    home = GODOT_HOME
    env = {'HOME': home, 'XDG_CONFIG_HOME': home + '/.config',
           'XDG_DATA_HOME': home + '/.local/share', 'XDG_CACHE_HOME': home + '/.cache',
           'XDG_STATE_HOME': home + '/.local/state', 'APPDATA': home + '/.local/share'}
    os.makedirs(home, exist_ok=True)
    if native:
        e = dict(os.environ)
        e.update(env)
        cmd = [native] + list(args)
    else:
        # The Flatpak sets XDG_* itself, after --env (a --env=XDG_CONFIG_HOME
        # is not seen by Godot), so they are set inside the sandbox, just
        # before Godot starts: Godot's settings, data and cache then go to
        # the throwaway home, never to ~/.var/app/org.godotengine.Godot.
        exports = ' '.join("%s='%s'" % kv for kv in env.items())
        quoted = ' '.join("'%s'" % a.replace("'", "'\\''") for a in args)
        cmd = ['flatpak', 'run', '--no-documents-portal', '--command=sh',
               'org.godotengine.Godot', '-c',
               'export %s; exec /app/bin/godot-bin %s' % (exports, quoted)]
        e = dict(os.environ)
    p = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=300)
    return p


def godot_prepare():
    tse = os.path.join(PROJECT, 'tse')
    os.makedirs(tse, exist_ok=True)
    for f in ('dump.gd', 'add_terrain.gd'):
        shutil.copy(os.path.join(HERE, 'godot', f), tse)
    # exports made outside the project, copied in (as a user would): the
    # .tres finds its texture by its relative path
    for name, base in (('main', 'main'), ('extrude', 'ex'), ('explicit_size', 'explicit'),
                       ('not_multiple', 'nm'), ('unequal_offset', 'uo'),
                       ('animations_odd', 'anim'), ('precision_16bit', 'precision_16bit'),
                       ('precision_float', 'precision_float'), ('gray', 'gray'),
                       ('indexed', 'indexed')):
        dest = os.path.join(PROJECT, 'cases', name)
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        os.makedirs(dest)
        for ext in ('.png', '.png.import', '.tres'):
            f = case(name, base + ext)
            if os.path.exists(f):
                shutil.copy(f, dest)
    global IMPORT_UIDS
    IMPORT_UIDS = {p: tm.read_uid(p) for p in (
        os.path.join(PROJECT, 'tiles', 'main.png.import'),
        os.path.join(PROJECT, 'cases', 'main', 'main.png.import'))}
    p = godot('--headless', '--import', '--path', PROJECT)
    check(p.returncode == 0, 'godot --import: %s' % (p.stdout + p.stderr)[-800:])


IMPORT_UIDS = {}


def godot_dump(res):
    p = godot('--headless', '--path', PROJECT, '--script', 'res://tse/dump.gd', '--', res)
    out = p.stdout + p.stderr
    m = re.search(r'^TSEJSON (.*)$', out, re.M)
    check(m, 'Godot printed nothing for %s: %s' % (res, out[-800:]))
    d = json.loads(m.group(1))
    check('error' not in d, d.get('error', ''))
    errors = [l for l in out.splitlines() if 'ERROR' in l or 'SCRIPT ERROR' in l]
    check(not errors, 'Godot: %s' % '\n'.join(errors[:5]))
    return d


def cell(tid, columns=4):
    return '%d:%d' % (tid % columns, tid // columns)


def check_godot_main(d, texture):
    check(d['texture'] == texture, 'texture %r' % d['texture'])
    for key, want in (('tile_size', [16, 16]), ('margins', [1, 1]), ('separation', [1, 1]),
                      ('region', [16, 16]), ('grid', [4, 3]), ('texture_size', [69, 52]),
                      ('physics_layers', 1), ('sources', 1)):
        check(d[key] == want, '%s is %r, not %r' % (key, d[key], want))
    layers = dict((n, t) for n, t in d['custom_data_layers'])
    check(layers == {'class': 4, 'hp': 2, 'name': 4, 'note': 4, 'solid': 1, 'speed': 3,
                     'tint': 20}, 'custom data layers %s' % d['custom_data_layers'])
    # every tile but the empty one and the frames after the first
    frames = {5, 6, 9}
    want_cells = sorted(cell(t) for t in range(12) if t not in frames and
                        t not in fx.EMPTY_TILES)
    check(sorted(d['tiles']) == want_cells, 'tiles %s, not %s' % (sorted(d['tiles']), want_cells))
    e = fx.EXPECT_MAIN['tiles']
    for tid in range(12):
        c = cell(tid)
        if c not in d['tiles']:
            continue
        t = d['tiles'][c]
        want = e.get(tid, {})
        check(abs(t['probability'] - want.get('probability', 1.0)) < 1e-6,
              'tile %s probability %s' % (c, t['probability']))
        custom = {n: None for n in layers}
        defaults = {1: False, 2: 0, 3: 0.0, 4: '', 20: [0, 0, 0, 255]}
        for n in layers:
            custom[n] = defaults[layers[n]]
        if want.get('class'):
            custom['class'] = want['class']
        for k, (typ, v) in want.get('properties', {}).items():
            custom[k] = [int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16), 255] \
                if typ == 'color' else v
        check(t['custom'] == custom, 'tile %s custom data %s, not %s' % (c, t['custom'], custom))
        if 'circle' in want:
            check(len(t['polygons']) == 1, 'tile %s: %d polygons' % (c, len(t['polygons'])))
            cx, cy, r = want['circle']
            check_circle(t['polygons'][0], cx - 8, cy - 8, r, 'tile %s' % c)
        else:
            got = sorted(norm_poly(p) for p in t['polygons'])
            exp = sorted(norm_poly([(x - 8, y - 8) for x, y in p]) for p in want.get('polygons', []))
            check(got == exp, 'tile %s polygons %s, not %s' % (c, got, exp))
        anim = want.get('animation')
        if anim:
            check(t.get('animation_columns') == len(anim), 'tile %s columns %s' %
                  (c, t.get('animation_columns')))
            durs = [ms / 1000.0 for _, ms in anim]
            check(len(t.get('durations', [])) == len(durs) and
                  all(abs(a - b) < 1e-6 for a, b in zip(t['durations'], durs)),
                  'tile %s durations %s' % (c, t.get('durations')))
        else:
            check('durations' not in t, 'tile %s is animated' % c)


def godot_main():
    d = godot_dump('res://tiles/main.tres')
    check_godot_main(d, 'res://tiles/main.png')


def godot_moved():
    d = godot_dump('res://cases/main/main.tres')
    check_godot_main(d, 'res://cases/main/main.png')


def godot_uids():
    for path, uid in IMPORT_UIDS.items():
        check(uid, 'no uid in %s' % path)
        check(tm.read_uid(path) == uid, 'Godot changed the uid in %s: %s, was %s' %
              (path, tm.read_uid(path), uid))
        text = open(path).read()
        check('mipmaps/generate=false' in text and 'compress/mode=0' in text and
              'detect_3d/compress_to=0' in text, 'the settings in %s changed' % path)
    tres = open(os.path.join(PROJECT, 'tiles', 'main.tres')).read()
    check('uid="%s"' % IMPORT_UIDS[os.path.join(PROJECT, 'tiles', 'main.png.import')] in tres,
          'the .tres does not use the texture uid')


def godot_other(name, res, want):
    d = godot_dump(res)
    for key, value in want.items():
        if key == 'cells':
            check(sorted(d['tiles']) == sorted(value), '%s: tiles %s, not %s' %
                  (name, sorted(d['tiles']), sorted(value)))
        elif key == 'animated':
            for c, cols in value.items():
                check(d['tiles'][c].get('animation_columns') == cols,
                      '%s: tile %s animation %s' % (name, c, d['tiles'][c]))
        elif key == 'polygons':
            for c, polys in value.items():
                got = sorted(norm_poly(p) for p in d['tiles'][c]['polygons'])
                exp = sorted(norm_poly(p) for p in polys)
                check(got == exp, '%s: tile %s polygons %s, not %s' % (name, c, got, exp))
        else:
            check(d[key] == value, '%s: %s is %r, not %r' % (name, key, d[key], value))


def godot_add_terrain():
    p = godot('--headless', '--path', PROJECT, '--script', 'res://tse/add_terrain.gd', '--',
              'res://terrain/terrain.tres')
    check('TSESAVE 0' in p.stdout, 'Godot did not save: %s' % (p.stdout + p.stderr)[-600:])
    d = godot_dump('res://terrain/terrain.tres')
    check(d['terrain_sets'] == 1, 'terrain sets %s' % d['terrain_sets'])


def godot_terrain_kept():
    d = godot_dump('res://terrain/terrain.tres')
    check(d['terrain_sets'] == 1, 'the terrain set is gone: %s' % d['terrain_sets'])
    for c in ('0:0', '1:0'):
        t = d['tiles'][c]
        check(t['terrain_set'] == 0 and t['terrain'] == 0, 'tile %s terrain %s/%s' %
              (c, t['terrain_set'], t['terrain']))
    check(d['tiles']['2:0']['terrain_set'] == -1, 'tile 2:0 has a terrain')
    check_godot_main(d, 'res://terrain/terrain.png')


# ---------------------------------------------------------------- the run

def phase1():
    run('png main (8-bit RGBA, pixels, no labels, no time stamp)', png_main)
    run('png 16-bit', png_kind, 'precision_16bit', 16, 6)
    run('png 32-bit float (exported as 16-bit)', png_kind, 'precision_float', 16, 6, 1)
    run('png grayscale', png_kind, 'gray', 8, 4, 0, True)
    run('png indexed', png_kind, 'indexed', 8, 3)
    run('png layer offsets', png_offsets)
    run('png unequal grid offset (cropped)', png_unequal_offset)
    run('png one layer group', png_layer_source)
    run('png extrusion', png_extrude)

    run('tiled main.tsx', tiled_main)
    run('tiled main.tsj', tiled_main_tsj)
    run('tiled writer (Tiled re-saves our .tsx and .tsj the same)', tiled_writer)
    run('tiled tmxrasterizer map against the golden PNG', tiled_render_golden)
    for name in ('precision_16bit', 'precision_float', 'indexed', 'gray'):
        run('tiled tmxrasterizer %s' % name, tiled_render_kind, name)
    run('tiled explicit size', tiled_other, 'explicit_size', 'explicit.tsx',
        {'tileWidth': 8, 'tileHeight': 8, 'margin': 2, 'tileSpacing': 1, 'columnCount': 4,
         'tileCount': 12})
    run('tiled not a multiple of the tile size', tiled_other, 'not_multiple', 'nm.tsx',
        {'tileWidth': 16, 'columnCount': 2, 'tileCount': 2, 'imageWidth': 40})
    run('tiled unequal grid offset', tiled_other, 'unequal_offset', 'uo.tsx',
        {'margin': 1, 'columnCount': 2, 'tileCount': 4, 'imageWidth': 33,
         'tiles': {0: {'objects': [[(0, 0), (16, 0), (16, 16)]]}}})
    run('tiled extrusion', tiled_other, 'extrude', 'ex.tsx',
        {'margin': 2, 'tileSpacing': 4, 'tileCount': 12, 'columnCount': 4, 'imageWidth': 80,
         'imageHeight': 60, 'tiles': {4: {'frames': [[4, 150], [5, 300], [6, 150]]},
                                      0: {'className': 'Grass'}}})
    run('tiled odd animations', tiled_other, 'animations_odd', 'anim.tsx',
        {'tiles': {0: {'frames': None}, 1: {'frames': [[1, 50], [7, 50]]},
                   2: {'frames': None}}})
    run('tiled labels off the tiles', tiled_other, 'label_off_tile', 'lo.tsx',
        {'tiles': {0: {'properties': {}}, 1: {'properties': {}}}})
    run('tiled Wang sets kept (.tsx)', tiled_other, 'wang_kept', 'wang.tsx', {'wangSets': 1})
    run('tiled Wang sets kept (.tsj)', tiled_other, 'wang_kept', 'wang.tsj', {'wangSets': 1})

    run('godot import (throwaway HOME)', godot_prepare)
    run('godot main.tres in the project (res:// path)', godot_main)
    run('godot main.tres copied into the project (relative path)', godot_moved)
    run('godot keeps the uid and settings of the .import', godot_uids)
    run('godot extrusion', godot_other, 'extrude', 'res://cases/extrude/ex.tres',
        {'margins': [2, 2], 'separation': [4, 4], 'grid': [4, 3], 'texture_size': [80, 60]})
    run('godot explicit size', godot_other, 'explicit_size',
        'res://cases/explicit_size/explicit.tres',
        {'tile_size': [8, 8], 'margins': [2, 2], 'separation': [1, 1], 'grid': [4, 3],
         'cells': ['%d:%d' % (c, r) for r in range(3) for c in range(4)]})
    run('godot not a multiple of the tile size', godot_other, 'not_multiple',
        'res://cases/not_multiple/nm.tres', {'grid': [2, 1], 'cells': ['0:0', '1:0']})
    run('godot unequal grid offset', godot_other, 'unequal_offset',
        'res://cases/unequal_offset/uo.tres',
        {'margins': [1, 1], 'grid': [2, 2], 'cells': ['0:0', '1:1'],
         'polygons': {'0:0': [[(-8, -8), (8, -8), (8, 8)]]}})
    run('godot odd animations', godot_other, 'animations_odd',
        'res://cases/animations_odd/anim.tres',
        {'cells': ['0:0', '1:0', '2:0', '3:1'], 'animated': {'1:0': None}})
    for name in ('precision_16bit', 'precision_float', 'gray', 'indexed'):
        run('godot %s' % name, godot_other, name, 'res://cases/%s/%s.tres' % (name, name),
            {'texture_size': [69, 52], 'grid': [4, 3]})
    run('godot adds a terrain (for the second export)', godot_add_terrain)


def phase2():
    run('godot terrains kept after the next export', godot_terrain_kept)


if __name__ == '__main__':
    if PHASE == '1':
        phase1()
    else:
        phase2()
    print('TSE check failures: %d' % failures, flush=True)
    sys.exit(1 if failures else 0)
