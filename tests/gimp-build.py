# Runs inside GIMP (tests/run.sh), without a window: builds the test
# images of tests/fixtures.py as XCFs in tests/output/cases/<case>/, runs
# Tileset Export on them and writes what it returned to result.json
# there, for tests/check.py. Checks here only what GIMP itself tells
# (statuses, return values, notes, the settings kept in the XCF).
# Prints "TSE PASS <case>" or "TSE FAIL <case>: <why>" and
# "TSE GIMP failures: <n>" at the end.
#
#   TSE_PHASE=1 (default): all cases
#   TSE_PHASE=2: the re-exports of the cases whose files were changed
#                in between (by Tiled's and Godot's own tools)
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import builtins
import functools
import json
import os
import sys
import traceback

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio, GObject

print = functools.partial(builtins.print, flush=True)
SRC = os.environ['TSE_SRC']
OUT = os.environ['TSE_OUT']
ONLY = os.environ.get('TSE_ONLY', '')
PHASE = os.environ.get('TSE_PHASE', '1')
sys.path.insert(0, os.path.join(SRC, 'tests'))
import fixtures as fx     # noqa: E402

Gegl.init(None)
PDB = Gimp.get_pdb()
CASES = os.path.join(OUT, 'cases')
failures = 0


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)


# ------------------------------------------------------------ building

def hexcolor(rgb):
    return '#%02x%02x%02x' % tuple(rgb)


def new_image(w, h, grid=None, offset=(0, 0), indexed=False):
    image = Gimp.Image.new(w, h, Gimp.ImageBaseType.RGB)
    if indexed:
        # GIMP 3.2.6 does not convert an image with layer groups to
        # indexed (gimp-image-convert-indexed fails), so the image is
        # made indexed first, with a palette of the fixture's colours
        tmp = add_layer(image, 'palette')
        for i, rgb in enumerate(fx.COLORS):
            fill_rect(image, tmp, i, 0, 1, 1, rgb)
        fill_rect(image, tmp, 20, 0, 1, 1, (255, 0, 255))
        check(image.convert_indexed(Gimp.ConvertDitherType.NONE,
                                    Gimp.ConvertPaletteType.GENERATE, 255, False, False, ''),
              'the conversion to indexed failed')
        image.remove_layer(tmp)
    if grid:
        image.grid_set_spacing(*grid)
        image.grid_set_offset(*offset)
    return image


def add_layer(image, name, w=None, h=None, x=0, y=0, parent=None, position=0, alpha=True):
    w = w or image.get_width()
    h = h or image.get_height()
    if image.get_base_type() == Gimp.ImageBaseType.INDEXED:
        itype = Gimp.ImageType.INDEXEDA_IMAGE if alpha else Gimp.ImageType.INDEXED_IMAGE
    else:
        itype = Gimp.ImageType.RGBA_IMAGE if alpha else Gimp.ImageType.RGB_IMAGE
    layer = Gimp.Layer.new(image, name, w, h, itype, 100, Gimp.LayerMode.NORMAL)
    image.insert_layer(layer, parent, position)
    layer.set_offsets(x, y)
    if alpha:
        layer.fill(Gimp.FillType.TRANSPARENT)
    return layer


def add_group(image, name, parent=None, position=0):
    group = Gimp.GroupLayer.new(image, name)
    image.insert_layer(group, parent, position)
    return group


def fill_rect(image, layer, x, y, w, h, rgb):
    """Fills a rectangle in image coordinates."""
    Gimp.context_set_antialias(False)
    Gimp.context_set_feather(False)
    image.select_rectangle(Gimp.ChannelOps.REPLACE, x, y, w, h)
    Gimp.context_set_foreground(Gegl.Color.new(hexcolor(rgb)))
    layer.edit_fill(Gimp.FillType.FOREGROUND)
    Gimp.Selection.none(image)


def fill_tile(image, layer, tid, spec=fx.MAIN, rgb=None):
    x, y = fx.cell_origin(tid, spec)
    fill_rect(image, layer, x, y, spec['tile'][0], spec['tile'][1], rgb or fx.COLORS[tid])


def add_path(image, name, strokes):
    path = Gimp.Path.new(image, name)
    image.insert_path(path, None, 0)
    for pts in strokes:
        cps = []
        for x, y in pts:
            cps += [x, y, x, y, x, y]
        path.stroke_new_from_points(Gimp.PathStrokeType.BEZIER, cps, True)
    return path


def add_label(image, group, tid, at, name, spec=fx.MAIN):
    if tid is None:
        x, y = at
    else:
        ox, oy = fx.cell_origin(tid, spec)
        x, y = ox + at[0], oy + at[1]
    layer = add_layer(image, name, 4, 4, x, y, parent=group)
    # magenta: must never show in the exported PNG
    fill_rect(image, layer, x, y, 4, 4, (255, 0, 255))
    return layer


def build_main(indexed=False):
    spec = fx.MAIN
    image = new_image(*spec['size'], grid=spec['grid'], offset=spec['offset'], indexed=indexed)
    base = add_layer(image, 'tiles')
    for tid in fx.BASE_TILES:
        fill_tile(image, base, tid)
    water = add_group(image, 'anim:water (150ms)')
    for i, (tid, name) in enumerate(fx.WATER_FRAMES):
        # bottom first: each frame goes below the ones before it
        frame = add_layer(image, name, parent=water, position=0)
        fill_tile(image, frame, tid)
    torch = add_layer(image, 'anim:torch (80ms)')
    for tid in fx.TORCH_TILES:
        fill_tile(image, torch, tid)
    labels = add_group(image, 'properties')
    for tid, at, name in fx.LABELS:
        add_label(image, labels, tid, at, name)
    for name, strokes in fx.COLLISION.items():
        add_path(image, name, strokes)
    circle = Gimp.Path.new(image, 'collision circle')
    image.insert_path(circle, None, 0)
    ox, oy = fx.cell_origin(fx.CIRCLE['tile'])
    cx, cy = fx.CIRCLE['centre']
    r = fx.CIRCLE['radius']
    circle.bezier_stroke_new_ellipse(ox + cx, oy + cy, r, r, 0.0)
    # a path that is not for collision
    add_path(image, 'outline', [[(0, 0), (60, 0), (60, 40)]])
    return image


# ------------------------------------------------------------ running

def case_dir(name):
    d = os.path.join(CASES, name)
    os.makedirs(d, exist_ok=True)
    return d


def save_xcf(image, path):
    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path), None)
    image.set_file(Gio.File.new_for_path(path))


def run_export(image, png=None, repeat=False, **settings):
    proc = PDB.lookup_procedure('plug-in-tileset-export-repeat' if repeat
                                else 'plug-in-tileset-export')
    check(proc is not None, 'the procedure is not registered')
    config = proc.create_config()
    config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
    config.set_property('image', image)
    config.set_core_object_array('drawables', image.get_selected_drawables())
    if not repeat:
        if png:
            config.set_property('png-file', Gio.File.new_for_path(png))
        for key, value in settings.items():
            config.set_property(key, value)
    result = proc.run(config)
    status = result.index(0)
    out = {'status': status.value_nick}
    if status == Gimp.PDBStatusType.SUCCESS:
        out['tile-count'] = result.index(1)
        out['files'] = [f for f in result.index(2).split('\n') if f]
        out['notes'] = [n for n in result.index(3).split('\n') if n]
    else:
        err = result.index(1) if result.length() > 1 else None
        out['error'] = str(err.message if hasattr(err, 'message') else err)
    return out


def write_result(name, result):
    with open(os.path.join(case_dir(name), 'result.json'), 'w') as f:
        json.dump(result, f, indent=1)


cases = []


def case(func):
    cases.append(func)
    return func


def ok(result, what='export'):
    check(result['status'] == 'success', '%s: %s %s' % (what, result['status'],
                                                         result.get('error', '')))


ALL = {'write-tsx': True, 'write-tsj': True, 'write-tres': True, 'write-godot-import': True,
       'spacing': 1}


# ------------------------------------------------------------ the cases

@case
def registered():
    for name, label in (('plug-in-tileset-export', 'Export _Tileset...'),
                        ('plug-in-tileset-export-repeat', 'Repeat Tileset E_xport')):
        p = PDB.lookup_procedure(name)
        check(p is not None, '%s is not registered' % name)
        check(p.get_menu_label() == label, '%s: menu label %r' % (name, p.get_menu_label()))
        check('<Image>/File/[Export]' in p.get_menu_paths(),
              '%s: menu paths %s' % (name, p.get_menu_paths()))
    args = [a.get_name() for a in PDB.lookup_procedure('plug-in-tileset-export').get_arguments()]
    check(args == ['run-mode', 'image', 'drawables', 'png-file', 'tile-size-from', 'tile-width',
                   'tile-height', 'margin', 'spacing', 'source', 'source-layer', 'write-tsx',
                   'write-tsj', 'write-tres', 'write-godot-import', 'extrude'],
          'arguments %s' % args)


@case
def main():
    """The main fixture, next to its XCF: every file."""
    d = case_dir('main')
    image = build_main()
    save_xcf(image, os.path.join(d, 'main.xcf'))
    result = run_export(image, **ALL)
    ok(result)
    write_result('main', result)
    check(result['tile-count'] == 12, 'tile count %s' % result['tile-count'])
    want = [os.path.join(d, 'main' + e) for e in ('.png', '.tsx', '.tsj', '.png.import', '.tres')]
    check(sorted(result['files']) == sorted(want), 'files %s' % result['files'])
    # no temporary files left
    left = [f for f in os.listdir(d) if f.startswith('.')]
    check(not left, 'temporary files left: %s' % left)
    # the settings are kept in the image, with the PNG relative to the XCF
    p = image.get_parasite('tileset-export-settings')
    check(p is not None, 'no settings parasite')
    data = json.loads(bytes(p.get_data()).decode())
    check(data['png-file'] == 'main.png', 'stored png %r' % data['png-file'])
    check(data['write-tres'] is True and data['spacing'] == 1, 'stored %s' % data)
    # the image itself is unchanged: layers, selection, paths
    check([l.get_name() for l in image.get_layers()] ==
          ['properties', 'anim:torch (80ms)', 'anim:water (150ms)', 'tiles'],
          'layers %s' % [l.get_name() for l in image.get_layers()])
    check(Gimp.Selection.is_empty(image), 'the selection changed')
    check(len(image.get_paths()) == 4, 'paths %d' % len(image.get_paths()))
    save_xcf(image, os.path.join(d, 'main.xcf'))
    image.delete()


@case
def repeat():
    """Repeat Tileset Export on the saved XCF, opened again: the same
    files, written anew (atomically: a new inode)."""
    d = case_dir('main')
    xcf = os.path.join(d, 'main.xcf')
    inodes = {f: os.stat(os.path.join(d, f)).st_ino for f in ('main.png', 'main.tsx', 'main.tres')}
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(xcf))
    result = run_export(image, repeat=True)
    ok(result, 'repeat')
    write_result('repeat', result)
    check(result['tile-count'] == 12, 'tile count %s' % result['tile-count'])
    # (the .import is there already and is kept)
    check(len(result['files']) == 4, 'files %s' % result['files'])
    for f, ino in inodes.items():
        check(os.stat(os.path.join(d, f)).st_ino != ino, '%s was written in place' % f)
    image.delete()


@case
def repeat_without_settings():
    image = new_image(32, 32, grid=(16, 16))
    add_layer(image, 'a')
    result = run_export(image, repeat=True)
    check(result['status'] == 'calling-error', 'status %s' % result['status'])
    check('not been exported' in result['error'], 'error %r' % result['error'])
    image.delete()


@case
def godot_project():
    """Into a Godot project: res:// paths and the .import."""
    project = os.path.join(OUT, 'godot', 'project')
    os.makedirs(os.path.join(project, 'tiles'), exist_ok=True)
    with open(os.path.join(project, 'project.godot'), 'w') as f:
        f.write('config_version=5\n\n[application]\n\nconfig/name="tileset-export tests"\n')
    image = build_main()
    png = os.path.join(project, 'tiles', 'main.png')
    for f in (png + '.import', png[:-4] + '.tres'):
        if os.path.exists(f):
            os.unlink(f)
    result = run_export(image, png, **ALL)
    ok(result)
    write_result('godot_project', result)
    # a second export keeps the .import and the uids
    first_import = open(png + '.import').read()
    first_tres = open(png[:-4] + '.tres').read().splitlines()[0]
    result = run_export(image, png, **ALL)
    ok(result, 'second export')
    check(open(png + '.import').read() == first_import, 'the .import was rewritten')
    check(open(png[:-4] + '.tres').read().splitlines()[0] == first_tres,
          'the uid of the .tres changed')
    check(any('exists already' in n for n in result['notes']), 'notes %s' % result['notes'])
    image.delete()


@case
def explicit_size():
    """Tile size, margin and spacing given, no grid: 8x8 tiles, margin 2,
    spacing 1 in 40x30 (4 x 3 tiles, leftover 1 x 1)."""
    image = new_image(40, 30)
    layer = add_layer(image, 'a')
    fill_rect(image, layer, 0, 0, 40, 30, (10, 200, 10))
    d = case_dir('explicit_size')
    result = run_export(image, os.path.join(d, 'explicit.png'), **{
        'tile-size-from': 'explicit', 'tile-width': 8, 'tile-height': 8, 'margin': 2,
        'spacing': 1, 'write-tsx': True, 'write-tres': True})
    ok(result)
    write_result('explicit_size', result)
    check(result['tile-count'] == 12, 'tile count %s' % result['tile-count'])
    check(any('not part of any tile' in n for n in result['notes']), 'notes %s' % result['notes'])
    image.delete()


@case
def no_grid():
    """Tile size from the grid, but the image has none of its own."""
    image = new_image(64, 64)
    add_layer(image, 'a')
    d = case_dir('no_grid')
    result = run_export(image, os.path.join(d, 'nogrid.png'))
    check(result['status'] == 'calling-error', 'status %s' % result['status'])
    check('no grid of its own' in result['error'], 'error %r' % result['error'])
    check(not os.path.exists(os.path.join(d, 'nogrid.png')), 'a PNG was written')
    # the same grid set in an XCF (as a parasite) counts as set
    image.grid_set_spacing(10, 10)
    image.attach_parasite(Gimp.Parasite.new('gimp-image-grid', Gimp.PARASITE_PERSISTENT,
                                            list(b'(style solid)')))
    result = run_export(image, os.path.join(d, 'nogrid.png'))
    ok(result, 'with the grid parasite')
    check(result['tile-count'] == 36, 'tile count %s' % result['tile-count'])
    image.delete()


@case
def not_multiple():
    """40x20 with 16x16 tiles: 2 x 1 tiles and a note."""
    image = new_image(40, 20, grid=(16, 16))
    layer = add_layer(image, 'a')
    fill_rect(image, layer, 0, 0, 40, 20, (200, 10, 10))
    d = case_dir('not_multiple')
    result = run_export(image, os.path.join(d, 'nm.png'), **{'write-tres': True})
    ok(result)
    write_result('not_multiple', result)
    check(result['tile-count'] == 2, 'tile count %s' % result['tile-count'])
    check(any('8 pixels wider and 4 pixels higher' in n for n in result['notes']),
          'notes %s' % result['notes'])
    image.delete()


def converted(name, convert, base=None, precision=None, indexed=False):
    image = build_main(indexed)
    check(convert(image) is not False, 'the conversion failed: %s' % PDB.get_last_error())
    if base is not None:
        check(image.get_base_type() == base, 'the image is %s' % image.get_base_type())
    if precision is not None:
        check(image.get_precision() == precision, 'the image is %s' % image.get_precision())
    d = case_dir(name)
    result = run_export(image, os.path.join(d, name + '.png'), **ALL)
    ok(result)
    write_result(name, result)
    check(result['tile-count'] == 12, 'tile count %s' % result['tile-count'])
    image.delete()


@case
def precision_16bit():
    converted('precision_16bit',
              lambda im: im.convert_precision(Gimp.Precision.U16_NON_LINEAR),
              precision=Gimp.Precision.U16_NON_LINEAR)


@case
def precision_float():
    converted('precision_float',
              lambda im: im.convert_precision(Gimp.Precision.FLOAT_LINEAR),
              precision=Gimp.Precision.FLOAT_LINEAR)


@case
def gray():
    converted('gray', lambda im: im.convert_grayscale(), base=Gimp.ImageBaseType.GRAY)


@case
def indexed():
    converted('indexed', lambda im: None, base=Gimp.ImageBaseType.INDEXED, indexed=True)


@case
def layer_offsets():
    """Layers that stick out of the canvas and one that does not cover it:
    the PNG is the canvas, composited."""
    image = new_image(32, 32, grid=(16, 16))
    a = add_layer(image, 'big', 40, 40, -10, -10)
    fill_rect(image, a, -10, -10, 40, 40, (255, 0, 0))
    b = add_layer(image, 'small', 8, 8, 20, 20)
    fill_rect(image, b, 20, 20, 8, 8, (0, 0, 255))
    d = case_dir('layer_offsets')
    result = run_export(image, os.path.join(d, 'offsets.png'))
    ok(result)
    write_result('layer_offsets', result)
    image.delete()


@case
def unequal_offset():
    """A grid offset of 3, 1: Tiled has one margin, so the PNG leaves out
    2 pixels on the left and the margin is 1."""
    image = new_image(3 + 32, 1 + 32, grid=(16, 16), offset=(3, 1))
    layer = add_layer(image, 'a')
    fill_rect(image, layer, 0, 0, 3, 33, (255, 0, 0))          # the left margin
    fill_rect(image, layer, 3, 1, 16, 16, (0, 255, 0))         # tile 0
    fill_rect(image, layer, 19, 17, 16, 16, (0, 0, 255))       # tile 3
    path = add_path(image, 'collision', [[(3, 1), (19, 1), (19, 17)]])
    d = case_dir('unequal_offset')
    result = run_export(image, os.path.join(d, 'uo.png'), **{'write-tres': True})
    ok(result)
    write_result('unequal_offset', result)
    check(any('leaves out 2 pixels on the left and 0 at the top' in n for n in result['notes']),
          'notes %s' % result['notes'])
    del path
    image.delete()


@case
def animations_odd():
    """Frames stacked on one tile (as in GIMP's own animations), frames
    that Godot cannot hold (not next to each other), one frame only."""
    image = new_image(64, 32, grid=(16, 16))
    stacked = add_group(image, 'anim:stacked')
    for i in range(2):
        f = add_layer(image, 'frame %d' % i, parent=stacked)
        fill_rect(image, f, 0, 0, 16, 16, (50 * i, 100, 100))
    apart = add_group(image, 'anim:apart (50ms)')
    f = add_layer(image, 'a', parent=apart)
    fill_rect(image, f, 16, 0, 16, 16, (0, 200, 0))
    f = add_layer(image, 'b', parent=apart, position=0)
    fill_rect(image, f, 48, 16, 16, 16, (0, 0, 200))
    single = add_group(image, 'anim:single')
    f = add_layer(image, 'only', parent=single)
    fill_rect(image, f, 32, 0, 16, 16, (200, 0, 0))
    d = case_dir('animations_odd')
    result = run_export(image, os.path.join(d, 'anim.png'), **{'write-tres': True,
                                                               'write-tsx': True})
    ok(result)
    write_result('animations_odd', result)
    notes = '\n'.join(result['notes'])
    check('both on tile 0' in notes, 'notes %s' % result['notes'])
    check('needs at least 2 frames' in notes, 'notes %s' % result['notes'])
    check('Godot needs its frames next to each other' in notes, 'notes %s' % result['notes'])
    image.delete()


@case
def label_off_tile():
    """A label in the spacing between tiles, a label with a bad value."""
    image = new_image(33, 16, grid=(17, 17))
    add_layer(image, 'tiles')
    group = add_group(image, 'Properties')
    add_label(image, group, None, (16, 2), 'lost=1')
    add_label(image, group, None, (0, 0), 'hp:int=many')
    d = case_dir('label_off_tile')
    result = run_export(image, os.path.join(d, 'lo.png'), spacing=1)
    ok(result)
    write_result('label_off_tile', result)
    notes = '\n'.join(result['notes'])
    check('is not on a tile' in notes, 'notes %s' % result['notes'])
    check('"many" is not of type int' in notes, 'notes %s' % result['notes'])
    image.delete()


@case
def layer_source():
    """Only one layer group is exported, even though another is visible
    above it and it is hidden itself."""
    image = new_image(32, 16, grid=(16, 16))
    other = add_group(image, 'other')
    o = add_layer(image, 'o', parent=other)
    fill_rect(image, o, 0, 0, 32, 16, (255, 0, 0))
    chosen = add_group(image, 'chosen', position=1)
    c = add_layer(image, 'c', parent=chosen)
    fill_rect(image, c, 16, 0, 16, 16, (0, 0, 255))
    chosen.set_visible(False)
    d = case_dir('layer_source')
    result = run_export(image, os.path.join(d, 'ls.png'), **{'source': 'layer',
                                                             'source-layer': chosen})
    ok(result)
    write_result('layer_source', result)
    check(not chosen.get_visible(), 'the group was made visible in the image')
    image.delete()


@case
def extrude():
    """Extrusion by 2 of the main fixture."""
    image = build_main()
    d = case_dir('extrude')
    result = run_export(image, os.path.join(d, 'ex.png'), **dict(ALL, extrude=2))
    ok(result)
    write_result('extrude', result)
    check(result['tile-count'] == 12, 'tile count %s' % result['tile-count'])
    image.delete()


@case
def wang_kept():
    """A Tiled Wang set added to the .tsx (as Tiled writes it) survives
    the next export; phase 2 has Godot add a terrain to the .tres."""
    image = build_main()
    d = case_dir('wang_kept')
    png = os.path.join(d, 'wang.png')
    result = run_export(image, png, **ALL)
    ok(result)
    tsx = png[:-4] + '.tsx'
    text = open(tsx).read().replace('\n</tileset>', '''
 <wangsets>
  <wangset name="ground" type="corner" tile="-1">
   <wangcolor name="grass" color="#ff0000" tile="-1" probability="1"/>
   <wangtile tileid="0" wangid="0,1,0,1,0,1,0,1"/>
  </wangset>
 </wangsets>
</tileset>''')
    with open(tsx, 'w') as f:
        f.write(text)
    tsj = png[:-4] + '.tsj'
    data = json.load(open(tsj))
    data['wangsets'] = [{'name': 'ground', 'type': 'corner', 'tile': -1,
                         'colors': [{'name': 'grass', 'color': '#ff0000', 'tile': -1,
                                     'probability': 1}],
                         'wangtiles': [{'tileid': 0, 'wangid': [0, 1, 0, 1, 0, 1, 0, 1]}]}]
    json.dump(data, open(tsj, 'w'))
    result = run_export(image, png, **ALL)
    ok(result, 'second export')
    write_result('wang_kept', result)
    check('<wangset name="ground"' in open(tsx).read(), 'the Wang set is gone from the .tsx')
    check('wangsets' in json.load(open(tsj)), 'the Wang set is gone from the .tsj')
    save_xcf(image, os.path.join(d, 'wang.xcf'))
    image.delete()


@case
def terrain_kept():
    """Phase 2: the .tres that Godot changed (a terrain set, tiles 0 and
    1 painted with it) is exported again from the XCF; the terrains
    stay."""
    if PHASE != '2':
        return 'skip'
    d = case_dir('godot_terrain')
    xcf = os.path.join(d, 'terrain.xcf')
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(xcf))
    result = run_export(image, repeat=True)
    ok(result, 'repeat')
    write_result('terrain_kept', result)
    image.delete()


@case
def godot_terrain_prepare():
    """Phase 1: the export that Godot adds terrains to before phase 2."""
    if PHASE != '1':
        return 'skip'
    project = os.path.join(OUT, 'godot', 'project')
    d = os.path.join(project, 'terrain')
    os.makedirs(d, exist_ok=True)
    image = build_main()
    png = os.path.join(d, 'terrain.png')
    for f in os.listdir(d):
        os.unlink(os.path.join(d, f))
    result = run_export(image, png, **ALL)
    ok(result)
    save_xcf(image, os.path.join(d, 'terrain.xcf'))
    image.delete()
    # the case folder points there for phase 2
    link = os.path.join(CASES, 'godot_terrain')
    if os.path.islink(link):
        os.unlink(link)
    os.symlink(d, link)


@case
def text_label():
    """TSE_PHASE=fonts (a GIMP with fonts): a text layer as a label, with
    more than 30 characters on two lines. GIMP names the layer after the
    first line, cut at 30 characters; the label is its whole text."""
    if PHASE != 'fonts':
        return 'skip'
    image = new_image(32, 16, grid=(16, 16))
    add_layer(image, 'tiles')
    group = add_group(image, 'properties')
    font = Gimp.context_get_font()
    text = 'Lava damage:int=5 hot=true\nglow=#ffaa00 speed=0.5'
    layer = Gimp.TextLayer.new(image, text, font, 4.0, Gimp.Unit.pixel())
    check(layer is not None, 'no text layer (font %s)' % font)
    image.insert_layer(layer, group, 0)
    layer.set_offsets(17, 1)
    check(layer.get_name() != text.replace('\n', ' '), 'the layer name is the whole text: %r' %
          layer.get_name())
    d = case_dir('text_label')
    result = run_export(image, os.path.join(d, 'text.png'))
    ok(result)
    write_result('text_label', result)
    tsx = open(os.path.join(d, 'text.tsx')).read()
    for want in ('<tile id="1" type="Lava">', 'name="damage" type="int" value="5"',
                 'name="hot" type="bool" value="true"', 'name="glow" type="color" '
                 'value="#ffffaa00"', 'name="speed" type="float" value="0.5"'):
        check(want in tsx, '%s is not in the .tsx:\n%s' % (want, tsx))
    image.delete()


# ------------------------------------------------------------ the run

PHASE2 = ('terrain_kept',)

for func in cases:
    name = func.__name__
    if ONLY and ONLY not in name:
        continue
    if PHASE == '2' and name not in PHASE2 and name != 'registered':
        continue
    if PHASE == 'fonts' and name != 'text_label':
        continue
    try:
        r = func()
        if r == 'skip':
            continue
        print('TSE PASS gimp %s' % name)
    except Fail as e:
        failures += 1
        print('TSE FAIL gimp %s: %s' % (name, e))
    except Exception as e:
        failures += 1
        print('TSE FAIL gimp %s: %s' % (name, e))
        traceback.print_exc()
print('TSE GIMP failures: %d' % failures)
