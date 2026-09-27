# Run by tests/check.py between two exports: adds a terrain set with one
# terrain to a TileSet .tres, paints tiles 0:0 and 1:0 with it (as the
# TileSet editor does) and saves the .tres with Godot's own writer.
#
#   godot --headless --path <project> --script res://tse/add_terrain.gd -- res://x.tres
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
extends SceneTree

func _init():
	var path = OS.get_cmdline_user_args()[0]
	var ts = load(path)
	ts.add_terrain_set()
	ts.set_terrain_set_mode(0, TileSet.TERRAIN_MODE_MATCH_CORNERS_AND_SIDES)
	ts.add_terrain(0)
	ts.set_terrain_name(0, 0, "grass")
	ts.set_terrain_color(0, 0, Color(0, 1, 0))
	var src = ts.get_source(ts.get_source_id(0))
	for c in [Vector2i(0, 0), Vector2i(1, 0)]:
		var data = src.get_tile_data(c, 0)
		data.terrain_set = 0
		data.terrain = 0
		data.set_terrain_peering_bit(TileSet.CELL_NEIGHBOR_RIGHT_SIDE, 0)
	print("TSESAVE %d" % ResourceSaver.save(ts, path))
	quit()
