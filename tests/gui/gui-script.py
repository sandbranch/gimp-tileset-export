# Runs inside GIMP on a Broadway display (tests/gui/start.sh). Opens
# tests/output/gui/gui.xcf or gui-repeat.xcf (4 x 2 tiles of 16x16, the image grid set, a
# label and a collision path), shows it, and runs Export Tileset with its
# dialog. When the dialog is closed, writes the status and the files
# written to TSE_OUT/result.txt, waits for TSE_OUT/done (the test takes
# its last screenshot meanwhile) and quits GIMP. With TSE_GUI_MODE=repeat
# it runs Repeat Tileset Export instead, which opens the same dialog for
# an image that has not been exported yet.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

import gi
gi.require_version('Gimp', '3.0')
gi.require_version('Gegl', '0.4')
from gi.repository import Gimp, Gegl, Gio

out = os.environ['TSE_OUT']
mode = os.environ.get('TSE_GUI_MODE', 'export')
# the repeat session has an XCF of its own: its dialog must show its own
# PNG, not the last one of the export session
xcf = os.path.join(out, 'gui-repeat.xcf' if mode == 'repeat' else 'gui.xcf')
pdb = Gimp.get_pdb()


def write(name, lines):
    with open(os.path.join(out, name + '.tmp'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.rename(os.path.join(out, name + '.tmp'), os.path.join(out, name))


image = Gimp.Image.new(64, 32, Gimp.ImageBaseType.RGB)
image.grid_set_spacing(16, 16)
layer = Gimp.Layer.new(image, 'tiles', 64, 32, Gimp.ImageType.RGBA_IMAGE, 100,
                       Gimp.LayerMode.NORMAL)
image.insert_layer(layer, None, 0)
layer.fill(Gimp.FillType.TRANSPARENT)
Gimp.context_set_antialias(False)
Gimp.context_set_feather(False)
for i, color in enumerate(('#2aa03c', '#7a7a82', '#dc8214', '#1e5ac8',
                           '#c82828', '#f0c81e', '#8c3caa', '#28c8c8')):
    image.select_rectangle(Gimp.ChannelOps.REPLACE, (i % 4) * 16, (i // 4) * 16, 16, 16)
    Gimp.context_set_foreground(Gegl.Color.new(color))
    layer.edit_fill(Gimp.FillType.FOREGROUND)
Gimp.Selection.none(image)
group = Gimp.GroupLayer.new(image, 'properties')
image.insert_layer(group, None, 0)
label = Gimp.Layer.new(image, 'Grass solid=true', 4, 4, Gimp.ImageType.RGBA_IMAGE, 100,
                       Gimp.LayerMode.NORMAL)
image.insert_layer(label, group, 0)
label.set_offsets(1, 1)
path = Gimp.Path.new(image, 'collision')
image.insert_path(path, None, 0)
path.stroke_new_from_points(Gimp.PathStrokeType.BEZIER,
                            [0, 0, 0, 0, 0, 0, 16, 0, 16, 0, 16, 0, 16, 16, 16, 16, 16, 16],
                            True)
for f in os.listdir(out):
    if f.startswith('gui') and not f.endswith('.xcf') and not f.endswith('.log'):
        os.unlink(os.path.join(out, f))
Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(xcf), None)
image.set_file(Gio.File.new_for_path(xcf))
image.clean_all()
display = Gimp.Display.new(image)
Gimp.displays_flush()

proc = pdb.lookup_procedure('plug-in-tileset-export-repeat' if mode == 'repeat'
                            else 'plug-in-tileset-export')
config = proc.create_config()
config.set_property('run-mode', Gimp.RunMode.INTERACTIVE)
config.set_property('image', image)
config.set_core_object_array('drawables', [layer])
result = proc.run(config)
status = result.index(0)
lines = ['status %s' % status.value_nick]
if status == Gimp.PDBStatusType.SUCCESS:
    lines.append('tiles %d' % result.index(1))
    lines += ['file %s' % os.path.basename(f) for f in result.index(2).split('\n') if f]
    lines += ['note %s' % n for n in result.index(3).split('\n') if n]
write('result.txt', lines)
t = time.time()
while not os.path.exists(os.path.join(out, 'done')) and time.time() - t < 60:
    time.sleep(0.5)
quit_proc = pdb.lookup_procedure('gimp-quit')
quit_config = quit_proc.create_config()
quit_config.set_property('force', True)
quit_proc.run(quit_config)
