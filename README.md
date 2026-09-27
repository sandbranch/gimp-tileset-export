# Tileset Export for GIMP 3

Paint a tileset in GIMP and export it for the level editors: a PNG, and
next to it the metadata that GIMP could not write so far: tile size,
margin and spacing, tile classes and custom properties, collision
polygons and animations, for

- **Tiled**: a `.tsx` (and a `.tsj` if you want JSON), which Tiled 1.10
  and later load as an external tileset;
- **Godot 4**: a TileSet `.tres` with one atlas source, physics polygons,
  animations and custom data layers, and the PNG's `.import` if it has
  none yet.

The metadata comes from the XCF itself, by a few naming conventions that
you can see and edit in GIMP without any code: a layer group of labels,
paths named `collision`, layer groups named `anim:<name>`. Export again
after a change and both editors pick it up.

A GIMP 3 plug-in in Python 3, free software under the GNU General Public
License, version 3 or later.

## Quick start

1. Draw your tiles on a grid, for example 16x16 pixels.
2. **Image > Configure Grid**: spacing 16 x 16 (the tile size), offset 0.
3. Optional metadata (all explained below):
   - a layer group named `properties` with a text layer on a tile saying
     `Grass solid=true`;
   - a path named `collision` around the solid part of a tile;
   - a layer group named `anim:water` with one layer per frame, each on
     its own tile.
4. Save the XCF, then **File > Export Tileset...**, tick what you need,
   OK. Next to `tiles.xcf` you get `tiles.png` and `tiles.tsx` (and
   `tiles.tsj`, `tiles.tres`, `tiles.png.import` if ticked).
5. From then on **File > Repeat Tileset Export** exports again with the
   same settings, without a dialog. Give it a shortcut in **Edit >
   Keyboard Shortcuts** (search for "Repeat Tileset").

## The conventions

### The tile grid

With **Tile size from: Image grid**, the grid of **Image > Configure
Grid** says where the tiles are:

| Configure Grid | means |
|---|---|
| spacing (width x height) | the tile size plus the spacing between tiles |
| offset (x, y) | the margin: where the first tile starts |

and **Spacing** in the export dialog is the gap between tiles (0 for
most tilesets). A tileset of 16x16 tiles with a 1 pixel margin and
1 pixel between tiles is a grid of 17x17 with an offset of 1, and
Spacing 1: the grid lines then run along the top and left edge of every
tile.

Or choose **Tile size, margin and spacing below** and give them
directly.

- As in Tiled and Godot, only whole tiles count: pixels right of and
  below the last whole tile (beyond a margin as wide as the one at the
  left) are not part of any tile, and the export says so.
- Tiled has one margin for both directions. If the grid offset differs
  in x and y (say 3 and 1), the PNG leaves out the difference on that
  side (2 pixels at the left) so that the margin is the smaller one;
  the export says so.
- An image without a grid of its own (GIMP's default grid is 10x10) is
  not guessed at: the export asks you to set the grid or the tile size.

### Tile classes and properties: labels

Make a layer group named **`properties`** (or `tile properties`). Every
layer in it is a label for the tile under **its top left corner**. The
easiest label is a text layer: take the Text tool, click on a tile and
type. The group is never part of the PNG, visible or not, so you can
keep the labels on while you paint. Hidden labels count too.

A label says:

    [Class] [name=value ...]

    Grass solid=true speed=1.5 name="Big Rock"
    Wall hp:int=3 probability=0.5
    tint=#ff8000

- The first word without `=` is the tile's **class** (Tiled's Class,
  written as `type` in the `.tsx` as Tiled 1.10 and later do). Or write
  `class=Grass`.
- `name=value` is a **custom property**. Its type follows from the
  value: `true` or `false` is a bool, `3` an int, `1.5` a float,
  `#rrggbb` a colour (`#aarrggbb`, alpha first, as in Tiled), anything
  else a string. A value in quotes is always a string (`n="3"`).
- `name:type=value` gives the type: `string`, `int`, `float`, `bool`,
  `color` or `file` (`hp:float=3`, `sound:file=sfx/step.wav`).
- `probability=0.5` is the tile's probability (Tiled's Probability,
  Godot's `probability`), not a custom property.
- A text layer's label is its whole text, all lines (GIMP names a text
  layer only after the first 30 characters of its first line). Other
  layers are labels by their name. What GIMP adds to names (`#1` to keep
  them apart, `copy` for a duplicate) is ignored.
- Several labels on one tile add up.
- A label named **`tileset: Terrain author=David`** is for the tileset
  itself: its class and properties.

Mistakes (a word without `=` after the class, `hp:int=many`, a label in
the margin) do not stop the export: it says what it left out.

### Collision shapes: paths

Every path whose name begins with **`collision`** (`collision`,
`collision ground`, ...) gives collision polygons: each of its strokes
is one closed polygon. Draw it with the Paths tool, with Snap to Grid if
you like.

- A stroke inside one tile is that tile's polygon, in the tile's own
  pixels.
- A stroke that crosses tiles is cut at the tile edges into one polygon
  for each tile it covers (and the spacing between tiles is left out):
  draw a platform's outline once across several tiles.
- Curves are turned into straight segments (to within 0.25 pixels).
- Other paths are left alone.

In Tiled each polygon is an object in the tile's collision object group,
positioned at its first point, as Tiled's collision editor makes them.
In Godot they are polygons of physics layer 0, around the tile's centre
as Godot expects.

### Animations: `anim:` layer groups

A layer group named **`anim:<name>`** is an animation: each layer (or
group) in it is one frame, **the bottom layer first**, as in GIMP's
Filters > Animation > Playback. Paint each frame on a tile of its own;
the frame's tile is the one under the centre of what it has painted.
The animation belongs to the first frame's tile: place that tile in the
map.

    anim:water (150ms)       <- the group: 150 ms for each frame
        frame 3               <- third frame, on tile 6
        frame 2 (300ms)       <- second frame, on tile 5, 300 ms
        frame 1               <- first frame, on tile 4

Durations are written as in GIMP's own animations: `(100ms)` in a
frame's name, else in the group's name, else 100 ms.

A single layer named `anim:torch (80ms)` that covers several tiles is an
animation too: its frames are the tiles it covers, left to right and top
to bottom (a strip of frames on one layer).

Frames stacked on the same tile (the way GIMP animations are usually
painted) cannot be told apart in a tileset: the export says so and
leaves that animation out.

**Godot** holds an animation only as frames next to each other in the
atlas, starting with the first one, in a row (or in rows of equal
length). Other animations are written for Tiled only; the export says
so. The frames after the first are not tiles of their own in Godot
(Godot reserves their cells for the animation), so their own labels and
collision are left out there.

### Terrains and Wang sets

Not made from GIMP (yet): they are easier to set up in the editors. But
they are kept: when the `.tsx` or `.tsj` is written again, the Wang
sets that you made in Tiled are copied over, and when the `.tres` is
written again, the terrain sets and the tiles' terrains that you made
in Godot's TileSet editor stay (for the tiles that are still there).

### What is in the PNG

The visible image as GIMP composites it (modes, opacities, masks,
layers off the canvas), without the `properties` group; or, with
**Export: One layer or layer group**, only that layer or group (visible
or not in the image, with its children as they are). The PNG is 8 bits
per channel for 8-bit images, 16 bits for higher precisions, grey for
grey images and indexed (with its palette) for indexed ones; with alpha,
without a time stamp, colour profile, thumbnail or other metadata.

## The files

For `tiles.png` (by default next to the XCF and named after it):

| File | When | What |
|---|---|---|
| `tiles.png` | always | the tileset image |
| `tiles.tsx` | Tiled .tsx (on by default) | Tiled tileset, TMX format 1.10 |
| `tiles.tsj` | Tiled .tsj | the same as JSON |
| `tiles.tres` | Godot TileSet .tres | Godot 4 TileSet resource (text format 3) |
| `tiles.png.import` | Godot .png.import, and only if there is none | Godot's import settings for the PNG |

Every file is written to a temporary file in the same folder and then
renamed over the old one, so an editor that watches the file never reads
half of it. The settings of the export (the PNG's place relative to the
XCF, the tile settings, which files) are kept in the XCF (a parasite
named `tileset-export-settings`); that is what Repeat Tileset Export
uses, and the dialog opens with them.

## Using it with Tiled

**Map > Add External Tileset...** and choose the `.tsx` (or `.tsj`). In
a map, the tiles have their class, properties, collision (View > Show
Tile Collision Shapes) and animations.

Tiled reloads by itself: it watches the tileset image and reloads it
half a second after a change (also after an atomic rename), and it
reloads a changed `.tsx` or `.tsj` if you have no unsaved changes in it
(else it asks). So keep Tiled open, export from GIMP, and look.
(Tiled's source, `src/libtiled/tilesetmanager.cpp` and
`src/tiled/documentmanager.cpp`; the image reload was tested headless,
see ../gimp-plugin-devtools/docs/level-editors.md.)

Tiled keeps its Wang sets in the same `.tsx`; they survive the next
export (see above). Other things you change in the tileset in Tiled
(properties, collision) are replaced by what the XCF says at the next
export: make them in GIMP.

## Using it with Godot 4

Export into your Godot project (choose a PNG file inside it): the
`.tres` then refers to the PNG as `res://...`, with the PNG's uid if it
has a `.import`. Exported elsewhere, it refers to the PNG by its file
name, which works as long as the two stay side by side (tested by
copying both into a project). Then:

- In a TileMapLayer, set **Tile Set** to the `.tres` (Load).
- Pixel art: set **Texture > Filter** of the TileMapLayer to Nearest, or
  Project Settings > Rendering > Textures > Canvas Textures > **Default
  Texture Filter** to Nearest. In Godot 4 the filter is not an import
  setting.
- The atlas has a tile for every cell with pixels, and for every cell
  with metadata; fully transparent cells without metadata are left out,
  as Godot's own "Create Tiles in Non-Transparent Texture Regions" does.
- Properties are **custom data layers**, one per property name, and one
  named `class` for the classes. A property with ints in some tiles and
  floats in others is a float layer; other mixes are strings (the export
  says so). Colours are Colors, files Strings.
- Collision is **physics layer 0** (collision layer 1).
- `probability` is the tile's probability.

**The .import**: ticked, it is written only when the PNG has none. It
says: a lossless texture, no mipmaps, never switched to VRAM compression
for 3D, and a new uid, which the `.tres` uses. Godot 4.7 imports the PNG
with exactly these settings and keeps the uid (tested: a pre-written
`.import` without `.godot/imported`, then `godot --import`); it fills in
the rest of the file itself. Once Godot has written its own `.import`,
the export leaves it alone, so your import settings stay yours.

**Reloading**: Godot rescans the project when its window gets the focus,
reimports the changed PNG, and reloads a changed `.tres` that is in use
in the editor (`EditorNode::_resources_changed`, which calls
`reload_from_file`; from Godot 4.7.2's source, not tried in the editor
window here). The TileSet editor has been seen to keep an old texture
after the image size changed, until a restart
([godot#74946](https://github.com/godotengine/godot/issues/74946)).

The `.tres` is written as Godot 4.7 writes TileSets (checked against
Godot's own `ResourceSaver` output and `scene/resources/2d/tile_set.cpp`),
and every test loads it in Godot 4.7.2 and compares what Godot sees.

Can Godot import `.xcf` files itself, by asking GIMP? See
[docs/godot.md](docs/godot.md).

## Extrusion

**Extrude tiles by** N repeats each tile's edge pixels N pixels outward,
against the seams that engines with texture filtering or scaling show
between tiles (colour bleeding from the neighbouring tile). The PNG is
laid out again: a margin of N and a spacing of 2N, which the `.tsx` and
`.tres` say, so the tile ids and the metadata stay the same. Godot 4
does not need it: its atlases pad tiles themselves
(`use_texture_padding`, on by default).

## Install

Both files, `tileset-export.py` and `tileset_model.py`, go into a folder
named `tileset-export` in GIMP's plug-in folder, and
`tileset-export.py` must be executable. Then restart GIMP.

**Linux, GIMP from your distribution or the Flatpak** (the Flatpak uses
the same folder, `~/.config/GIMP`):

    mkdir -p ~/.config/GIMP/3.2/plug-ins/tileset-export
    cp tileset-export/*.py ~/.config/GIMP/3.2/plug-ins/tileset-export/
    chmod +x ~/.config/GIMP/3.2/plug-ins/tileset-export/tileset-export.py

**Windows** (`%APPDATA%\GIMP\3.2\plug-ins\tileset-export\`) and **macOS**
(`~/Library/Application Support/GIMP/3.2/plug-ins/tileset-export/`):
copy the two files there. These are GIMP's usual folders; the plug-in
was not tried on either system.

The plug-in needs GIMP 3.2 with its Python 3 support (part of GIMP 3
and of the Flatpak); tested with GIMP 3.2.6 (Flatpak). GIMP 3.0 was not
tried. It adds
**File > Export Tileset...** and **File > Repeat Tileset Export**, next
to GIMP's own Export items.

## From scripts

`plug-in-tileset-export` takes `png-file` (empty: next to the XCF),
`tile-size-from` (`grid` or `explicit`), `tile-width`, `tile-height`,
`margin`, `spacing`, `source` (`visible` or `layer`), `source-layer`,
`write-tsx`, `write-tsj`, `write-tres`, `write-godot-import` and
`extrude`; `plug-in-tileset-export-repeat` takes nothing but the image.
Both return `tile-count`, `files` (the files written, one per line) and
`notes` (what the dialog would have told you, one per line).

## Limits

- One tileset per XCF, from one grid; rectangular tiles only
  (orthogonal; no isometric or hexagonal tile offsets).
- No image collection tilesets (one image per tile), no Tiled tile
  offset or render size, no Godot occlusion or navigation layers, no
  alternative tiles, only physics layer 0.
- Terrains and Wang sets are not made from the XCF (they are kept, see
  above).
- A label applies to one tile (the one under its top left corner).
- What you change in Tiled or Godot other than Wang sets and terrains is
  replaced at the next export.
- GIMP 3.2.6 cannot convert an image with layer groups to indexed
  (`gimp-image-convert-indexed` fails, seen in the tests); an indexed
  image that has groups exports fine.
- LDtk, which reads PNG tilesets, has no metadata format here yet.

## Tests

    tests/get-tiled.sh      # once: the Tiled AppImage (needs the network)
    tests/run.sh            # everything; no network

`tests/run.sh` prints PASS, FAIL or SKIP for each case and exits
non-zero on a failure. In about one and a half minutes it runs 95 checks:

- **unit** (`tests/unit.py`, no GIMP): the labels and their types, the
  layout against Tiled's and Godot's formulas, clipping of paths at tile
  edges, Bezier curves, the writers, Godot uids, extrusion, atomic
  writes, keeping Wang sets and terrains.
- **GIMP** (`tests/gimp-build.py`, headless GIMP, a throwaway profile,
  `--no-fonts`): builds the test images (`tests/fixtures.py`) as XCFs and
  exports them: the main tileset with every convention, 16-bit, 32-bit
  float, grey and indexed images, layers off the canvas, no grid, a size
  that is not a multiple of the tile, unequal grid offsets, odd
  animations (stacked frames, frames apart, one frame), labels off the
  tiles and with wrong values, one layer group, extrusion, and Repeat on
  the XCF opened again (new inodes: written by rename). A second GIMP,
  with fonts, tests a text layer as a label.
- **Tiled 1.12.2** (the official AppImage, `QT_QPA_PLATFORM=offscreen`,
  a throwaway HOME): `tiled --evaluate` reads every `.tsx` and `.tsj`
  with Tiled's own reader and checks tile count, size, margin, spacing,
  classes, typed properties, probability, collision polygons, animation
  frames and durations and Wang sets; Tiled writes the tileset again
  with its own writer and the result must say the same;
  `tmxrasterizer` draws a map with the tileset, compared pixel by pixel
  with `tests/golden/main-map.png` (made from the fixture's colours, not
  from an export), and with the 16-bit, float, grey and indexed PNGs.
- **Godot 4.7.2** (headless): imports the project, loads every `.tres`
  and checks atlas, margins, separation, grid, tiles, polygons,
  animations, custom data layers and values, the uid and settings of the
  `.import`; adds a terrain with Godot's own writer, then GIMP exports
  again and the terrain must still be there.
- **The dialog** on a Broadway display with a headless Chrome
  (`tests/gui/gui-test.sh`, using ../gimp-plugin-devtools): OK, Cancel,
  and Repeat without earlier settings; screenshots in
  `tests/output/gui/`.

Nothing of yours is touched: GIMP, Tiled and Godot run with throwaway
profiles and homes in `tests/output/`. The Flatpaks set `XDG_*` after
`--env`, so the tests set them inside the sandbox
(`flatpak run --command=sh ... -c 'export XDG_CONFIG_HOME=...; exec ...'`),
and GIO runs without GVFS (`GIO_USE_VFS=local`), which otherwise writes
to `~/.var/app/org.gimp.GIMP/data/gvfs-metadata`. `tests/snapshot.sh`
lists your folders of GIMP, Tiled and Godot (names, sizes and times)
before and after the run, which fails if anything there changed.

`tests/get-tiled.sh` downloads `Tiled-1.12.2_Linux_x86_64.AppImage` from
Tiled's GitHub release, checks its SHA-256 against the release page and
unpacks it. The AppImage lacks Qt's offscreen platform plug-in; the
script adds the one of the same Qt 6.10 from the Flatpak runtime
`org.kde.Platform//6.10` if you have it, else from the official
`PyQt6-Qt6` 6.10.2 wheel (checked against PyPI's SHA-256). Without Tiled
the Tiled checks are skipped; without Godot the Godot checks, without
Chrome and node the dialog test.

`TSE_GUI=0 tests/run.sh` leaves out the dialog test; `GIMP_FLATPAK=0`
uses a native GIMP; `TSE_GODOT=/path/to/godot` a native Godot 4.7.
