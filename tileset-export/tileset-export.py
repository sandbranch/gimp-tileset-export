#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Tileset Export for GIMP 3
# Copyright 2026 David
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tileset Export for GIMP 3.

Exports the image as a tileset: a PNG, and the metadata of the tiles for
Tiled (.tsx, .tsj) and Godot 4 (a TileSet .tres, and optionally the
PNG's .import). The tile grid comes from Image > Configure Grid or is
given; tile classes and properties come from labels in a layer group
named "properties", collision polygons from paths named "collision",
animations from layer groups named "anim:<name>". See README.md.
"""

import json
import os
import re
import sys
import traceback

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio, GLib, GObject

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tileset_model as tm      # noqa: E402

PLUG_IN_BINARY = 'tileset-export'
PROC = 'plug-in-tileset-export'
PROC_REPEAT = 'plug-in-tileset-export-repeat'
PARASITE = 'tileset-export-settings'
SETTINGS_VERSION = 1
MENU = '<Image>/File/[Export]'
AUTHOR = 'David'
COPYRIGHT = 'David'
DATE = '2026'

TILE_SIZE_FROM = [('grid', 'Image grid (Image > Configure Grid)'),
                  ('explicit', 'Tile size, margin and spacing below')]
SOURCES = [('visible', 'Visible image'), ('layer', 'One layer or layer group')]

# the arguments of the export and their defaults, also the keys of the
# settings stored in the image
DEFAULTS = {
    'tile-size-from': 'grid',
    'tile-width': 16,
    'tile-height': 16,
    'margin': 0,
    'spacing': 0,
    'source': 'visible',
    'write-tsx': True,
    'write-tsj': False,
    'write-tres': False,
    'write-godot-import': False,
    'extrude': 0,
}


def make_choice(table):
    choice = Gimp.Choice.new()
    for i, (nick, label) in enumerate(table):
        choice.add(nick, i, label, '')
    return choice


# ------------------------------------------------------------ settings

def settings_from_config(config):
    s = {}
    for key in DEFAULTS:
        s[key] = config.get_property(key)
    f = config.get_property('png-file')
    path = f.get_path() if f is not None else ''
    # GIMP 3.2 keeps a file argument's last value as "file:////home/...",
    # which comes back as "//home/..."
    s['png-file'] = re.sub(r'^//+', '/', path or '')
    layer = config.get_property('source-layer')
    s['source-layer'] = layer
    return s


def config_from_settings(config, s):
    for key in DEFAULTS:
        if key in s:
            config.set_property(key, s[key])
    if s.get('png-file'):
        config.set_property('png-file', Gio.File.new_for_path(s['png-file']))
    if s.get('source-layer') is not None:
        config.set_property('source-layer', s['source-layer'])


def image_folder(image):
    f = image.get_file()
    path = f.get_path() if f is not None else None
    return os.path.dirname(path) if path else None


def stored_settings(image):
    """The settings of the last export of this image (kept in the XCF),
    or None. The PNG's path is kept relative to the XCF's folder."""
    p = image.get_parasite(PARASITE)
    if p is None:
        return None
    try:
        data = json.loads(bytes(p.get_data()).decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    if data.get('version') != SETTINGS_VERSION:
        return None
    s = dict(DEFAULTS)
    for key in DEFAULTS:
        if key in data:
            s[key] = data[key]
    png = data.get('png-file', '')
    folder = image_folder(image)
    if png and not os.path.isabs(png) and folder:
        png = os.path.normpath(os.path.join(folder, png))
    s['png-file'] = png if os.path.isabs(png) else ''
    layer = None
    tattoo = data.get('source-layer-tattoo')
    if tattoo:
        layer = image.get_layer_by_tattoo(tattoo)
    if layer is None and data.get('source-layer-name'):
        layer = image.get_layer_by_name(data['source-layer-name'])
    s['source-layer'] = layer
    return s


def store_settings(image, s, png_path):
    data = {'version': SETTINGS_VERSION}
    for key in DEFAULTS:
        data[key] = s[key]
    folder = image_folder(image)
    if folder:
        rel = os.path.relpath(png_path, folder)
        data['png-file'] = rel
    else:
        data['png-file'] = png_path
    layer = s.get('source-layer')
    if layer is not None:
        data['source-layer-tattoo'] = layer.get_tattoo()
        data['source-layer-name'] = layer.get_name()
    text = json.dumps(data, sort_keys=True)
    old = image.get_parasite(PARASITE)
    if old is not None and bytes(old.get_data()).decode('utf-8', 'replace') == text:
        return
    image.attach_parasite(Gimp.Parasite.new(PARASITE, Gimp.PARASITE_PERSISTENT,
                                            list(text.encode('utf-8'))))


def default_png_path(image):
    f = image.get_file()
    path = f.get_path() if f is not None else None
    if not path:
        return ''
    return os.path.splitext(path)[0] + '.png'


# ------------------------------------------------------------ the image

def walk(items):
    """All layers of a tree of layers, depth first, groups before their
    children."""
    for it in items:
        yield it
        if it.is_group():
            yield from walk(it.get_children())


def content_bounds(image, item):
    """The bounds of the item's non-transparent pixels in image
    coordinates, (x0, y0, x1, y1), or None if it has none. Changes the
    selection: used on the copy of the image only."""
    image.select_item(Gimp.ChannelOps.REPLACE, item)
    r = Gimp.Selection.bounds(image)
    Gimp.Selection.none(image)
    ok, non_empty, x1, y1, x2, y2 = r
    if not non_empty:
        return None
    return x1, y1, x2, y2


def label_text(layer):
    """What a label says: a text layer's text (GIMP cuts the names of text
    layers at 30 characters and at the first line), else its name."""
    if layer.is_text_layer():
        text = layer.get_text()
        if not text:
            markup = layer.get_markup() or ''
            text = re.sub(r'<[^>]*>', '', markup)
            text = (text.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
                    .replace('&apos;', "'").replace('&amp;', '&'))
        return ' '.join(text.split())
    return layer.get_name()


def all_paths(image):
    def rec(paths):
        for p in paths:
            yield p
            try:
                children = p.get_children()
            except Exception:
                children = []
            if children:
                yield from rec(children)
    return list(rec(image.get_paths()))


class Export:
    """One export: reads the settings, the image and its conventions,
    writes the files."""

    def __init__(self, image, s):
        self.image = image
        self.s = s
        self.files = []

    # -- where

    def png_path(self):
        path = self.s.get('png-file') or default_png_path(self.image)
        if not path:
            raise tm.TilesetError('The image has not been saved yet, so there is no folder to '
                                  'export to: save it, or choose a PNG file.')
        if not path.lower().endswith('.png'):
            path += '.png'
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            raise tm.TilesetError('The folder %s does not exist.' % folder)
        return path

    # -- the grid

    def layout(self):
        """The layout of the exported image (after cropping), and the crop
        (x, y) from the image's top left corner."""
        s = self.s
        w, h = self.image.get_width(), self.image.get_height()
        if s['tile-size-from'] == 'grid':
            ok, gx, gy = self.image.grid_get_spacing()
            ok2, ox, oy = self.image.grid_get_offset()
            if (gx, gy, ox, oy) == (10.0, 10.0, 0.0, 0.0) and \
                    self.image.get_parasite('gimp-image-grid') is None:
                raise tm.TilesetError(
                    'The image has no grid of its own (GIMP\'s default grid is 10x10 pixels), '
                    'so the tile size is not known. Set it in Image > Configure Grid (the '
                    'spacing is the tile size plus the spacing between tiles, the offset the '
                    'margin), or give the tile size in the dialog.')
            tw, th, mx, my = tm.layout_from_grid(w, h, (gx, gy), (ox, oy), s['spacing'])
        else:
            tw, th, mx, my = s['tile-width'], s['tile-height'], s['margin'], s['margin']
        margin = min(mx, my)
        crop = (mx - margin, my - margin)
        layout = tm.Layout(w - crop[0], h - crop[1], tw, th, margin, s['spacing'])
        return layout, crop

    # -- the conventions

    def read_labels(self, ts, img, crop):
        lay = ts.layout
        for group in walk(img.get_layers()):
            if not (group.is_group() and tm.is_properties_group(group.get_name())):
                continue
            for layer in walk(group.get_children()):
                if layer.is_group():
                    continue
                text = label_text(layer)
                where = 'label "%s"' % layer.get_name()
                tileset_text = tm.tileset_label_text(text)
                if tileset_text is not None:
                    label = tm.parse_label(tileset_text, allow_probability=False)
                    for e in label.errors:
                        ts.warn('%s: %s' % (where, e))
                    if label.cls:
                        ts.cls = label.cls
                    ts.props.update(label.props)
                    continue
                ok, x, y = layer.get_offsets()
                cell = lay.cell_at(x - crop[0], y - crop[1])
                if cell is None:
                    ts.warn('%s: its top left corner (%d, %d) is not on a tile; it is left '
                            'out.' % (where, x, y))
                    continue
                label = tm.parse_label(text)
                for e in label.errors:
                    ts.warn('%s: %s' % (where, e))
                tile = ts.tile(lay.tile_id(*cell))
                if label.cls:
                    if tile.cls and tile.cls != label.cls:
                        ts.warn('%s: tile %d has the class "%s" from another label already.'
                                % (where, tile.id, tile.cls))
                    tile.cls = label.cls
                tile.props.update(label.props)
                if label.probability is not None:
                    tile.probability = label.probability

    def read_collision(self, ts, img, crop):
        lay = ts.layout
        for path in all_paths(img):
            if not tm.is_collision_path(path.get_name()):
                continue
            for sid in path.get_strokes():
                kind, points, closed = path.stroke_get_points(sid)
                poly = tm.flatten_stroke(list(points), True)
                poly = [(x - crop[0], y - crop[1]) for x, y in poly]
                poly = tm.simplify(poly)
                if len(poly) < 3:
                    ts.warn('path "%s": a stroke with fewer than 3 points is left out.' %
                            path.get_name())
                    continue
                pieces = tm.polygons_for_cells(poly, lay)
                if not pieces:
                    ts.warn('path "%s": a stroke is not on any tile.' % path.get_name())
                for cell, piece in pieces.items():
                    ts.tile(lay.tile_id(*cell)).polygons.append(piece)

    def frame_cell(self, ts, img, item, crop):
        b = content_bounds(img, item)
        if b is None:
            return None
        cx = (b[0] + b[2]) / 2.0 - crop[0]
        cy = (b[1] + b[3]) / 2.0 - crop[1]
        return ts.layout.cell_at(cx, cy)

    def read_animations(self, ts, img, crop):
        lay = ts.layout
        for item in walk(img.get_layers()):
            name = tm.anim_name(item.get_name())
            if name is None:
                continue
            if self.in_properties(item):
                continue
            default_ms = tm.duration_ms(item.get_name()) or tm.DEFAULT_FRAME_MS
            where = 'animation "%s"' % item.get_name()
            frames = []
            if item.is_group():
                # bottom layer first, as in GIMP's Playback
                for child in reversed(item.get_children()):
                    cell = self.frame_cell(ts, img, child, crop)
                    if cell is None:
                        ts.warn('%s: the frame "%s" is empty or not on a tile; it is left '
                                'out.' % (where, child.get_name()))
                        continue
                    ms = tm.duration_ms(child.get_name()) or default_ms
                    frames.append((lay.tile_id(*cell), ms, child.get_name()))
            else:
                b = content_bounds(img, item)
                if b is not None:
                    for cell in lay.cells_in_rect(b[0] - crop[0], b[1] - crop[1],
                                                  b[2] - crop[0], b[3] - crop[1]):
                        frames.append((lay.tile_id(*cell), default_ms, None))
            if len(frames) < 2:
                ts.warn('%s: an animation needs at least 2 frames on tiles; it has %d.' %
                        (where, len(frames)))
                continue
            seen = {}
            clash = None
            for tid, ms, fname in frames:
                if tid in seen:
                    clash = (seen[tid], fname, tid)
                    break
                seen[tid] = fname
            if clash:
                ts.warn('%s: the frames "%s" and "%s" are both on tile %d; put each frame on a '
                        'tile of its own. The animation is left out.' % ((where,) + clash))
                continue
            first = ts.tile(frames[0][0])
            if first.animation:
                ts.warn('%s: tile %d has an animation already; this one replaces it.' %
                        (where, first.id))
            first.animation = [(tid, ms) for tid, ms, _ in frames]

    def in_properties(self, item):
        p = item.get_parent()
        while p is not None:
            if tm.is_properties_group(p.get_name()):
                return True
            p = p.get_parent()
        return False

    # -- the pixels

    def flatten(self, img, crop, layout):
        """Merges the image (the copy) into one layer of the size of the
        exported image: without the label groups, and only the chosen
        layer or group if there is one."""
        for item in list(walk(img.get_layers())):
            if item.is_group() and tm.is_properties_group(item.get_name()) and item.is_valid():
                img.remove_layer(item)
        if self.s['source'] == 'layer':
            src = self.s.get('source-layer')
            if src is None:
                raise tm.TilesetError('Choose the layer or layer group to export.')
            copy = img.get_layer_by_tattoo(src.get_tattoo())
            if copy is None:
                raise tm.TilesetError('The layer "%s" is not in the image.' % src.get_name())
            keep = copy
            while keep is not None:
                keep.set_visible(True)
                parent = keep.get_parent()
                siblings = parent.get_children() if parent is not None else img.get_layers()
                for sib in siblings:
                    if sib.get_id() != keep.get_id():
                        sib.set_visible(False)
                keep = parent
        visible = [l for l in img.get_layers() if l.get_visible()]
        if not visible:
            raise tm.TilesetError('Nothing is visible to export.')
        # a transparent layer the size of the image at the bottom, so that
        # the merged layer is the size of the image
        base_type = img.get_base_type()
        itype = {Gimp.ImageBaseType.RGB: Gimp.ImageType.RGBA_IMAGE,
                 Gimp.ImageBaseType.GRAY: Gimp.ImageType.GRAYA_IMAGE,
                 Gimp.ImageBaseType.INDEXED: Gimp.ImageType.INDEXEDA_IMAGE}[base_type]
        floor = Gimp.Layer.new(img, 'tileset-export-floor', img.get_width(), img.get_height(),
                               itype, 100, Gimp.LayerMode.NORMAL)
        img.insert_layer(floor, None, len(img.get_layers()))
        floor.fill(Gimp.FillType.TRANSPARENT)
        merged = img.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)
        for layer in list(img.get_layers()):
            if layer.get_id() != merged.get_id():
                img.remove_layer(layer)
        if crop != (0, 0):
            img.crop(layout.image_w, layout.image_h, crop[0], crop[1])
        return merged

    def empty_tiles(self, layer, layout):
        """The ids of the tiles whose pixels are all transparent."""
        if not layer.has_alpha():
            return set()
        w, h = layer.get_width(), layer.get_height()
        data = layer.get_buffer().get(Gegl.Rectangle.new(0, 0, w, h), 1.0, 'A u8',
                                      Gegl.AbyssPolicy.NONE)
        empty = set()
        for row in range(layout.rows):
            for col in range(layout.columns):
                x0, y0, x1, y1 = layout.cell_rect(col, row)
                if all(not any(data[y * w + x0:y * w + x1]) for y in range(y0, y1)):
                    empty.add(layout.tile_id(col, row))
        return empty

    def extrude(self, img, layer, layout, n):
        """Each tile moved to its place in the extruded layout, with its
        edge pixels repeated n pixels outward: GEGL copies from a buffer
        cut to the tile, whose abyss repeats the edge (CLAMP), in the
        layer's own format (also indexed)."""
        new = tm.extrude_layout(layout, n)
        if not layer.has_alpha():
            layer.add_alpha()
        img.resize(new.image_w, new.image_h, 0, 0)
        out = Gimp.Layer.new(img, 'tileset-export-extruded', new.image_w, new.image_h,
                             layer.type(), 100, Gimp.LayerMode.NORMAL)
        img.insert_layer(out, None, 0)
        out.fill(Gimp.FillType.TRANSPARENT)
        src = layer.get_buffer()
        dst = out.get_buffer()
        for row in range(layout.rows):
            for col in range(layout.columns):
                sx, sy = layout.cell_origin(col, row)
                dx, dy = new.cell_origin(col, row)
                tile = src.create_sub_buffer(Gegl.Rectangle.new(sx, sy, layout.tile_w,
                                                                layout.tile_h))
                w, h = layout.tile_w + 2 * n, layout.tile_h + 2 * n
                tile.copy(Gegl.Rectangle.new(sx - n, sy - n, w, h), Gegl.AbyssPolicy.CLAMP,
                          dst, Gegl.Rectangle.new(dx - n, dy - n, w, h))
        dst.flush()
        img.remove_layer(layer)
        return new, out

    def export_png(self, img, path):
        folder = os.path.dirname(path)
        tmp = os.path.join(folder, '.%s.%s.tmp.png' % (os.path.basename(path),
                                                        os.urandom(4).hex()))
        proc = Gimp.get_pdb().lookup_procedure('file-png-export')
        config = proc.create_config()
        config.set_property('run-mode', Gimp.RunMode.NONINTERACTIVE)
        config.set_property('image', img)
        config.set_property('file', Gio.File.new_for_path(tmp))
        for key, value in (('interlaced', False), ('bkgd', False), ('offs', False),
                           ('phys', False), ('time', False), ('save-transparent', False),
                           ('optimize-palette', False), ('format', 'auto'),
                           ('include-exif', False), ('include-iptc', False),
                           ('include-xmp', False), ('include-color-profile', False),
                           ('include-thumbnail', False), ('include-comment', False)):
            config.set_property(key, value)
        try:
            result = proc.run(config)
            if result.index(0) != Gimp.PDBStatusType.SUCCESS:
                err = result.index(1) if result.length() > 1 else None
                raise tm.TilesetError('The PNG could not be written: %s' %
                                      (err or 'file-png-export failed'))
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- all of it

    def run(self):
        png = self.png_path()
        base = os.path.splitext(png)[0]
        layout, crop = self.layout()
        ts = tm.Tileset(os.path.basename(base), os.path.basename(png), layout)
        # pixels right of and below the tiles beyond a margin as wide as
        # the one on the left and at the top
        dx, dy = [max(0, v - layout.margin) for v in layout.leftover()]
        if dx or dy:
            ts.warn('The image is %d pixels wider and %d pixels higher than its %dx%d whole '
                    'tiles and their margins; those pixels are not part of any tile.' %
                    (dx, dy, layout.columns, layout.rows))
        if crop != (0, 0):
            ts.warn('The grid offset differs in x and y (Tiled has one margin for both): the '
                    'PNG leaves out %d pixels on the left and %d at the top, so that the '
                    'margin is %d.' % (crop[0], crop[1], layout.margin))
        img = self.image.duplicate()
        try:
            self.read_labels(ts, img, crop)
            self.read_collision(ts, img, crop)
            self.read_animations(ts, img, crop)
            layer = self.flatten(img, crop, layout)
            for tid in self.empty_tiles(layer, layout):
                ts.tile(tid).empty = True
            for tid in range(layout.tile_count):
                ts.tile(tid)
            if self.s['extrude'] > 0:
                ts.layout, layer = self.extrude(img, layer, layout, self.s['extrude'])
            self.export_png(img, png)
        finally:
            img.delete()
        self.files.append(png)
        self.write_metadata(ts, png, base)
        return ts

    def write_metadata(self, ts, png, base):
        s = self.s
        if s['write-tsx']:
            text = tm.keep_tiled_wangsets(tm.write_tsx(ts), base + '.tsx', 'tsx')
            tm.write_atomic(base + '.tsx', text)
            self.files.append(base + '.tsx')
        if s['write-tsj']:
            text = tm.keep_tiled_wangsets(tm.write_tsj(ts), base + '.tsj', 'tsj')
            tm.write_atomic(base + '.tsj', text)
            self.files.append(base + '.tsj')
        if s['write-tres'] or s['write-godot-import']:
            folder = os.path.dirname(png)
            project = tm.find_godot_project(folder)
            import_path = png + '.import'
            texture_uid = tm.read_uid(import_path)
            if s['write-godot-import'] and not os.path.exists(import_path):
                texture_uid = tm.godot_uid()
                tm.write_atomic(import_path, tm.write_godot_import(texture_uid))
                self.files.append(import_path)
            elif s['write-godot-import']:
                ts.warn('Godot: %s exists already and is kept (Godot keeps its import '
                        'settings there).' % os.path.basename(import_path))
            if s['write-tres']:
                tres = base + '.tres'
                if project:
                    rel = os.path.relpath(png, project).replace(os.sep, '/')
                    texture_path = 'res://' + rel
                else:
                    texture_path = os.path.basename(png)
                    texture_uid = texture_uid if os.path.exists(import_path) else None
                text = tm.write_tres(ts, texture_path, texture_uid,
                                     tm.read_tres_uid(tres) or tm.godot_uid())
                tm.write_atomic(tres, tm.keep_godot_terrains(text, tres))
                self.files.append(tres)


# ------------------------------------------------------------ the dialog

def show_dialog(procedure, config, image):
    gi.require_version('GimpUi', '3.0')
    from gi.repository import GimpUi
    GimpUi.init(PLUG_IN_BINARY)
    dialog = GimpUi.ProcedureDialog.new(procedure, config, 'Export Tileset')
    ok, gx, gy = image.grid_get_spacing()
    ok, ox, oy = image.grid_get_offset()
    dialog.get_label('grid-info', 'The image grid: %gx%g pixels, offset %g, %g' %
                     (gx, gy, ox, oy), False, False)
    dialog.get_widget('tile-size-from', GimpUi.IntRadioFrame)
    dialog.get_widget('source', GimpUi.IntRadioFrame)
    dialog.fill_box('tiles-box', ['tile-size-from', 'grid-info', 'tile-width', 'tile-height',
                                  'margin', 'spacing'])
    dialog.get_label('tiles-label', 'Tiles', False, False)
    dialog.fill_frame('tiles-frame', 'tiles-label', False, 'tiles-box')
    dialog.fill_box('image-box', ['source', 'source-layer', 'extrude'])
    dialog.get_label('image-label', 'Tileset image', False, False)
    dialog.fill_frame('image-frame', 'image-label', False, 'image-box')
    dialog.fill_box('files-box', ['png-file', 'write-tsx', 'write-tsj', 'write-tres',
                                  'write-godot-import'])
    dialog.get_label('files-label', 'Files', False, False)
    dialog.fill_frame('files-frame', 'files-label', False, 'files-box')
    try:
        explicit = Gimp.ValueArray.new_from_values([GObject.Value(GObject.TYPE_STRING,
                                                                  'explicit')])
        for prop in ('tile-width', 'tile-height', 'margin'):
            dialog.set_sensitive_if_in(prop, None, 'tile-size-from', explicit, True)
        layer_mode = Gimp.ValueArray.new_from_values([GObject.Value(GObject.TYPE_STRING,
                                                                    'layer')])
        dialog.set_sensitive_if_in('source-layer', None, 'source', layer_mode, True)
    except Exception:
        traceback.print_exc()
    dialog.fill(['tiles-frame', 'image-frame', 'files-frame'])
    try:
        return dialog.run()
    finally:
        dialog.destroy()


# ------------------------------------------------------------ the plug-in

def run_export(procedure, run_mode, image, s, config=None):
    try:
        exp = Export(image, s)
        ts = exp.run()
        store_settings(image, s, exp.png_path())
    except tm.TilesetError as e:
        if run_mode != Gimp.RunMode.NONINTERACTIVE:
            Gimp.message(str(e))
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, GLib.Error(str(e)))
    except Exception as e:
        traceback.print_exc()
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR,
                                           GLib.Error('Tileset Export failed: %s' % e))
    if ts.warnings and run_mode != Gimp.RunMode.NONINTERACTIVE:
        Gimp.message('Tileset exported to %s, with notes:\n\n%s' %
                     (exp.files[0], '\n'.join('- ' + w for w in ts.warnings)))
    for w in ts.warnings:
        print('tileset-export: note: %s' % w, flush=True)
    retval = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
    retval.remove(1)
    retval.insert(1, GObject.Value(GObject.TYPE_INT, ts.layout.tile_count))
    retval.insert(2, GObject.Value(GObject.TYPE_STRING, '\n'.join(exp.files)))
    retval.insert(3, GObject.Value(GObject.TYPE_STRING, '\n'.join(ts.warnings)))
    return retval


def run_main(procedure, run_mode, image, drawables, config, data):
    if run_mode == Gimp.RunMode.INTERACTIVE:
        # GIMP fills the dialog with the values of the last run, which may
        # have been for another image: the PNG and the layer are always
        # this image's (its last export, or next to its XCF)
        stored = stored_settings(image)
        if stored is not None:
            config_from_settings(config, stored)
        if stored is None or not stored.get('png-file'):
            default = default_png_path(image)
            config.set_property('png-file', Gio.File.new_for_path(default) if default else None)
        layer = stored.get('source-layer') if stored else None
        if layer is None:
            layer = next((d for d in drawables if isinstance(d, Gimp.Layer)), None)
        config.set_property('source-layer', layer)
        if not show_dialog(procedure, config, image):
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
    return run_export(procedure, run_mode, image, settings_from_config(config), config)


def run_repeat(procedure, run_mode, image, drawables, config, data):
    s = stored_settings(image)
    if s is None:
        if run_mode == Gimp.RunMode.INTERACTIVE:
            # nothing to repeat yet: the full export, with its dialog
            proc = Gimp.get_pdb().lookup_procedure(PROC)
            c = proc.create_config()
            c.set_property('run-mode', Gimp.RunMode.INTERACTIVE)
            c.set_property('image', image)
            c.set_core_object_array('drawables', drawables)
            result = proc.run(c)
            status = result.index(0)
            retval = procedure.new_return_values(status, GLib.Error())
            if status == Gimp.PDBStatusType.SUCCESS:
                retval.remove(1)
                for i in range(1, 4):
                    retval.insert(i, GObject.Value(
                        GObject.TYPE_INT if i == 1 else GObject.TYPE_STRING, result.index(i)))
            return retval
        return procedure.new_return_values(
            Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error('The image has not been exported as a tileset yet (File > Export '
                       'Tileset...).'))
    return run_export(procedure, run_mode, image, s)


class TilesetExport(Gimp.PlugIn):

    def do_set_i18n(self, name):
        return False

    def do_query_procedures(self):
        return [PROC, PROC_REPEAT]

    def do_create_procedure(self, name):
        Gegl.init(None)
        flags = GObject.ParamFlags.READWRITE
        if name == PROC:
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                                run_main, None)
            procedure.set_menu_label('Export _Tileset...')
            procedure.set_documentation(
                'Export the image as a tileset PNG with metadata for Tiled and Godot.',
                'Writes the image (or one layer group) as a PNG and next to it the tileset '
                'metadata: a Tiled .tsx or .tsj, a Godot 4 TileSet .tres and optionally the '
                'PNG\'s Godot .import. The tile grid comes from the image grid or is given. '
                'Tile classes and properties come from labels in a layer group named '
                '"properties", collision polygons from paths named "collision...", '
                'animations from layer groups named "anim:<name>".', name)
            procedure.add_file_argument('png-file', '_PNG file',
                                        'The tileset PNG; the metadata files go next to it '
                                        '(empty: next to the XCF, named after it)',
                                        Gimp.FileChooserAction.SAVE, True, None, flags)
            procedure.add_choice_argument('tile-size-from', 'Tile size from',
                                          'Where the tile size, margin and spacing come from',
                                          make_choice(TILE_SIZE_FROM), 'grid', flags)
            procedure.add_int_argument('tile-width', 'Tile _width', 'Tile width in pixels',
                                       1, 8192, 16, flags)
            procedure.add_int_argument('tile-height', 'Tile _height', 'Tile height in pixels',
                                       1, 8192, 16, flags)
            procedure.add_int_argument('margin', '_Margin',
                                       'Pixels around the tiles (with the image grid: its '
                                       'offset)', 0, 8192, 0, flags)
            procedure.add_int_argument('spacing', '_Spacing',
                                       'Pixels between the tiles (with the image grid: the '
                                       'grid spacing is the tile size plus this)',
                                       0, 8192, 0, flags)
            procedure.add_choice_argument('source', 'Export', 'What the tileset image is made of',
                                          make_choice(SOURCES), 'visible', flags)
            procedure.add_layer_argument('source-layer', '_Layer or group',
                                         'The layer or layer group to export (with Export: '
                                         'one layer or group)', True, flags)
            procedure.add_boolean_argument('write-tsx', 'Tiled .ts_x', 'Write a Tiled .tsx',
                                           True, flags)
            procedure.add_boolean_argument('write-tsj', 'Tiled .ts_j (JSON)',
                                           'Write a Tiled .tsj', False, flags)
            procedure.add_boolean_argument('write-tres', '_Godot TileSet .tres',
                                           'Write a Godot 4 TileSet resource', False, flags)
            procedure.add_boolean_argument('write-godot-import', 'Godot .png._import',
                                           'Write the PNG\'s Godot import settings (lossless, '
                                           'no mipmaps) if it has none yet', False, flags)
            procedure.add_int_argument('extrude', '_Extrude tiles by',
                                       'Repeat the edge pixels of each tile outward by this '
                                       'many pixels (against bleeding in engines that filter '
                                       'textures); the margin and spacing are set to match',
                                       0, 64, 0, flags)
        else:
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN,
                                                run_repeat, None)
            procedure.set_menu_label('Repeat Tileset E_xport')
            procedure.set_documentation(
                'Export the tileset again with the settings of its last export.',
                'Exports the tileset with the settings of the last File > Export Tileset of '
                'this image (they are kept in the XCF), without a dialog. Give it a shortcut '
                'in Edit > Keyboard Shortcuts. Without an earlier export it opens the dialog.',
                name)
        procedure.add_int_return_value('tile-count', 'Tile count', 'The number of tiles',
                                       0, GLib.MAXINT32, 0, flags)
        procedure.add_string_return_value('files', 'Files', 'The files written, one per line',
                                          '', flags)
        procedure.add_string_return_value('notes', 'Notes',
                                          'What the user should know, one note per line', '',
                                          flags)
        procedure.set_image_types('*')
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE |
                                       Gimp.ProcedureSensitivityMask.DRAWABLES |
                                       Gimp.ProcedureSensitivityMask.NO_DRAWABLES)
        procedure.set_attribution(AUTHOR, COPYRIGHT, DATE)
        procedure.add_menu_path(MENU)
        return procedure


if __name__ == '__main__':
    Gimp.main(TilesetExport.__gtype__, sys.argv)
