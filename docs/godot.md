# Could Godot import .xcf files by asking GIMP?

A note, not a plan that is built: could a Godot 4 editor plug-in
(an EditorImportPlugin) import `.xcf` files by having GIMP convert them,
so that an XCF in a Godot project is a texture like a PNG? Checked on
2026-09-27 with Godot 4.7.2 (Flatpak `org.godotengine.Godot` and the
source at tag `4.7.2-stable`), GIMP 3.2.6 (Flatpak) and Aseprite Wizard
9.8.0. Marks: **[source]** read in the source, **[tested]** run here,
**UNVERIFIED** not checked.

**Short answer: yes.** Godot's import plug-ins may run programs, the
Godot Flatpak may start programs on the host, and a headless GIMP turns
an XCF into a PNG in about 4.3 seconds. Tested end to end from inside
the Godot sandbox, without Godot itself: `flatpak-spawn --host flatpak
run --command=gimp-console-3.2 org.gimp.GIMP ...` wrote a correct PNG in
4.4 s [tested]. It is how Aseprite Wizard imports Aseprite files.

## What Godot allows

An import plug-in (GDScript, `@tool`, registered by an EditorPlugin)
[source: `editor/import/editor_import_plugin.cpp`, `doc/classes/EditorImportPlugin.xml`]:

- `_get_recognized_extensions()` returns `["xcf"]`. No importer of
  Godot's own claims `xcf`; with several, `_get_priority()` decides.
- `_import(source_file, save_path, options, platform_variants, gen_files)`
  saves one resource to `save_path + "." + _get_save_extension()` and
  returns an Error. Extra files written into `res://` are listed in
  `gen_files`.
- It cannot write Godot's own `.ctex` (no script can: the only savers
  are text, binary, shader, JSON and shader include). So it saves a
  `PortableCompressedTexture2D` (lossless) or an `ImageTexture` as
  `.res`, which is what Aseprite Wizard does.
  `append_import_external_resource()` could hand a PNG to Godot's own
  texture importer instead (UNVERIFIED).
- `OS.execute()` blocks until the program ends; nothing forbids it in
  `_import`. Import plug-ins run on the main thread one file at a time
  unless `_can_import_threaded()` returns true (default false), so the
  editor waits while GIMP works.
- A changed source file is reimported when the editor window gets the
  focus (`editor/editor_node.cpp`, `NOTIFICATION_APPLICATION_FOCUS_IN`
  calls `EditorFileSystem::scan_changes()`); change is noticed by mtime,
  then by the source's MD5. So: save the XCF in GIMP, switch to Godot,
  and it reimports.
- `OS.is_sandboxed()` tells a Flatpak Godot (it checks for
  `/.flatpak-info`).

## What the Flatpak sandbox allows

For `org.godotengine.Godot` 4.7.2 from Flathub (no overrides here)
[tested]:

- `filesystems=host`: Godot sees the home folder, including
  `~/.config/GIMP` and wherever the project is. But **`/tmp` is its
  own**, not the host's (the GIMP Flatpak does get the host's `/tmp`), so
  files for GIMP must be under `$HOME`, not in `/tmp`.
- Inside, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` point into
  `~/.var/app/org.godotengine.Godot/`, while `HOME` is the real home:
  paths for GIMP must be built from `HOME`.
- `shared=network`: 127.0.0.1 is the host's. A test listener on the host
  got a connection from inside the sandbox.
- Session bus `org.freedesktop.Flatpak=talk`: `flatpak-spawn --host`
  exists inside and works (`flatpak-spawn --host true` returns 0), so the
  sandboxed Godot can run any program on the host, for example
  `flatpak run org.gimp.GIMP`. (That is full host access; a user
  override could take it away.)
- GIMP is not on the host's PATH when it is a Flatpak, so the command is
  `flatpak-spawn --host flatpak run --command=gimp-console-3.2
  org.gimp.GIMP ...`, and natively `gimp-console-3.2`.

## How Aseprite Wizard does it (MIT, © 2020 Vinicius Gerevini)

[source: github.com/viniciusgerevini/godot-aseprite-wizard at 18ebea98,
`addons/AsepriteWizard/`]

- It runs Aseprite with `OS.execute(command, arguments, output, true,
  true)` (`aseprite/aseprite.gd`). The command is the editor setting
  `aseprite/general/command_path`, by default `aseprite` on Linux (a
  Steam path on Windows, the .app on macOS).
- Arguments: `-b --list-tags --list-slices --data <json> --format
  json-array --sheet <png> <file>`, plus layer, trim, sheet type, scale
  and similar options; `--export-tileset` for tilesets.
- The PNG and JSON go next to the source; it loads the PNG with
  `Image.load_from_file`, makes a `PortableCompressedTexture2D`
  (lossless) and saves it as `.res`; it can delete the temporary files.
- Importers for `aseprite` and `ase`: SpriteFrames, textures (also a
  tileset texture, but no TileSet resource), and one that imports
  nothing (for files handled otherwise). Import order 1; none imports in
  threads.
- It can keep "baked" files so that a project builds without Aseprite
  (in CI, or for someone who has none).
- Flatpak: its FAQ only says that a Flatpak Godot reports "command not
  found" and suggests Flatseal; it does not use `flatpak-spawn`.

## Two ways to get the PNG from GIMP

### A. Through GIMP's resident listener (gimp-blender-link)

`../gimp-blender-link` has a listener inside GIMP [source]: a persistent
procedure started with GIMP (also by gimp-console) that serves one JSON
line per connection on 127.0.0.1 (port 29317 by default, or the
setting `port`, or `GIMP_BLENDER_LINK_PORT`), with a token from
`~/.local/share/gimp-blender-link/gimp-listener.json` (mode 0600:
`port`, `token`, `pid`, `version`; written at start, removed at stop;
a literal `$HOME` path because each Flatpak has its own
`XDG_DATA_HOME`). Godot reads it as `OS.get_environment("HOME") +
"/.local/share/gimp-blender-link/gimp-listener.json"` and talks with
`StreamPeerTCP`.

Missing: a command that exports an XCF. The commands there are for
Blender (`open`, `send`, `uv_changed` answer "queued" at once and work
later; `status` answers directly). An `export` command `{xcf, png,
bit_depth}` would load the XCF, flatten it with the code that is there
(`gbl_gimp.flattened()`, `gbl_png.write`), write the PNG atomically,
close the image and answer `{ok, png, width, height}` when done (or give
a job to poll). A file, not pixels in the reply: a line is limited to
1 MiB.

Fast (GIMP is running already; latency UNVERIFIED), but only while GIMP
runs with the listener.

### B. A headless GIMP for each file

`OS.execute()` of `gimp-console-3.2 --no-interface --no-fonts --no-data
--batch-interpreter=python-fu-eval -b "<load, flatten, export PNG>"
--quit`, through `flatpak-spawn --host flatpak run
--command=gimp-console-3.2 org.gimp.GIMP` when Godot is sandboxed.
Measured [tested]: 4.3 s for each file (the load and export itself about
0.7 s), the first run with a new GIMP profile about 35 s. A headless
GIMP never hands its work to a running GIMP (`--no-interface` forces a
new instance; `app/main.c`), so it works with GIMP open. Whether it may
share the user's own profile with a running GIMP is UNVERIFIED; a
profile of its own avoids that, but has none of the user's plug-ins.

Needs no running GIMP, but the editor freezes for 4 seconds per XCF.

## A sketch

    addons/xcf_import/
      plugin.cfg, plugin.gd            EditorPlugin: add_import_plugin(XcfImporter)
      xcf_importer.gd                  EditorImportPlugin
        _get_recognized_extensions()   ["xcf"]
        _get_resource_type()           "PortableCompressedTexture2D"
        _get_save_extension()          "res"
        _get_import_options()          visible layers only / one layer group;
                                       lossless or lossy; mipmaps
        _import():
          png = project's .godot/xcf_import/<hash>.png (under $HOME, never /tmp)
          ask the listener (A); if there is none, run gimp-console (B)
          Image.load_from_file(png) -> PortableCompressedTexture2D
            .create_from_image(LOSSLESS) -> ResourceSaver.save(save_path + ".res")
      settings: the GIMP command (native or Flatpak), the listener on/off,
                "bake": keep a PNG next to the XCF for machines without GIMP

With Tileset Export the same importer could also read the XCF's
conventions and make the TileSet, but a TileSet refers to its texture,
so importing both from one XCF needs two resources (`gen_files`, or the
texture as a sub-resource of the TileSet); to be checked.

**Effort**: B alone, 1 to 2 days (finding the command, errors shown in
the editor, the bake fallback, tests with a headless Godot); A on top,
half a day to a day for the `export` command in gimp-blender-link with
its tests, and half a day for the client in Godot.

**Risks**: the first import of many XCFs takes 4 s each (35 s more for a
new profile); `flatpak-spawn --host` is broad and could be removed by an
override; project paths under `/tmp` break the Flatpak route; every team
member needs GIMP, or the baked files are committed; a `.res` texture
skips Godot's VRAM compression options unless the PNG goes through
Godot's own importer. Not checked: bit depth and colour when a 16-bit
XCF becomes an 8-bit texture.
