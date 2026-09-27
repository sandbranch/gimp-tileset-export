# The test images of Tileset Export and what their exports must hold:
# read by tests/gimp-build.py (inside GIMP, which builds the XCFs and
# exports them) and by tests/check.py (outside GIMP, which checks the
# files with Tiled, Godot and a PNG reader). No GIMP here.
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later

# ---------------------------------------------------------------- main
# 4 x 3 tiles of 16x16 with a margin of 1 and a spacing of 1: the image
# grid is 17x17 with an offset of 1, and the spacing argument is 1.
MAIN = {
    'size': (69, 52), 'grid': (17, 17), 'offset': (1, 1), 'tile': (16, 16),
    'margin': 1, 'spacing': 1, 'columns': 4, 'rows': 3,
}

COLORS = [
    (40, 160, 60), (120, 120, 130), (220, 130, 20), (30, 90, 200),
    (20, 110, 230), (40, 140, 240), (60, 170, 250), (200, 40, 40),
    (250, 200, 30), (250, 120, 20), (140, 60, 170), (0, 0, 0),
]
EMPTY_TILES = [11]


def cell_origin(tid, spec=MAIN):
    col, row = tid % spec['columns'], tid // spec['columns']
    return (spec['margin'] + col * (spec['tile'][0] + spec['spacing']),
            spec['margin'] + row * (spec['tile'][1] + spec['spacing']))


def img_pts(tid, pts, spec=MAIN):
    ox, oy = cell_origin(tid, spec)
    return [(x + ox, y + oy) for x, y in pts]


# which tiles each layer paints: the base layer, the frames of the
# water animation (a group, bottom frame first), the torch strip (one
# layer over two tiles)
BASE_TILES = [0, 1, 2, 3, 7, 10]
WATER_FRAMES = [(4, 'f1'), (5, 'f2 (300ms)'), (6, 'f3')]     # bottom first
TORCH_TILES = [8, 9]

# the labels in the "properties" group: (tile id or None for the
# tileset, where in the tile, the layer name)
LABELS = [
    (0, (2, 3), 'Grass solid=true speed=1.5 name="Big Rock"'),
    (1, (0, 0), 'Wall solid=true hp:int=3 probability=0.5'),
    (2, (15, 15), 'tint=#ff8000 note=\'it is "hot"\''),
    (None, (0, 0), 'tileset: Terrain author=David'),
]

# collision paths ("collision" and "collision ground"): strokes as
# image coordinates of anchors (straight segments)
COLLISION = {
    'collision': [
        img_pts(0, [(0, 0), (16, 0), (16, 16), (0, 16)]),
        img_pts(1, [(0, 16), (8, 0), (16, 16)]),
    ],
    'collision ground': [
        # across tiles 2 and 3 (and the spacing between them)
        [(43, 5), (60, 5), (60, 13), (43, 13)],
    ],
}
# a circle (Bezier curves) in tile 7: centre and radius in tile pixels
CIRCLE = {'tile': 7, 'centre': (8, 8), 'radius': 6}

EXPECT_MAIN = {
    'name': 'main',
    'tilewidth': 16, 'tileheight': 16, 'margin': 1, 'spacing': 1,
    'columns': 4, 'tilecount': 12, 'imagewidth': 69, 'imageheight': 52,
    'class': 'Terrain',
    'properties': {'author': ('string', 'David')},
    'tiles': {
        0: {'class': 'Grass',
            'properties': {'solid': ('bool', True), 'speed': ('float', 1.5),
                           'name': ('string', 'Big Rock')},
            'polygons': [[(0, 0), (16, 0), (16, 16), (0, 16)]]},
        1: {'class': 'Wall', 'probability': 0.5,
            'properties': {'solid': ('bool', True), 'hp': ('int', 3)},
            'polygons': [[(0, 16), (8, 0), (16, 16)]]},
        2: {'properties': {'tint': ('color', '#ff8000'), 'note': ('string', 'it is "hot"')},
            'polygons': [[(8, 4), (16, 4), (16, 12), (8, 12)]]},
        3: {'polygons': [[(0, 4), (8, 4), (8, 12), (0, 12)]]},
        4: {'animation': [(4, 150), (5, 300), (6, 150)]},
        7: {'circle': (8, 8, 6)},
        8: {'animation': [(8, 80), (9, 80)]},
    },
}

# the map for tmxrasterizer: 4 x 2 tiles, tile ids (-1 empty)
MAP = [[0, 1, 2, 3],
       [4, 8, 10, -1]]
