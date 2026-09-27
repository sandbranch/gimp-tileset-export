# Run by tests/check.py in a Godot without a window: loads a TileSet
# .tres and prints what Godot sees in it as one JSON line
# ("TSEJSON {...}").
#
#   godot --headless --path <project> --script res://tse/dump.gd -- res://x.tres
#
# Copyright 2026 David
# SPDX-License-Identifier: GPL-3.0-or-later
extends SceneTree

func _init():
	var path = OS.get_cmdline_user_args()[0]
	var ts = load(path)
	var d = {}
	if ts == null or not (ts is TileSet):
		d["error"] = "not a TileSet: %s" % path
		print("TSEJSON " + JSON.stringify(d))
		quit()
		return
	d["tile_size"] = [ts.tile_size.x, ts.tile_size.y]
	d["physics_layers"] = ts.get_physics_layers_count()
	var layers = []
	for i in ts.get_custom_data_layers_count():
		layers.append([ts.get_custom_data_layer_name(i), ts.get_custom_data_layer_type(i)])
	d["custom_data_layers"] = layers
	d["terrain_sets"] = ts.get_terrain_sets_count()
	d["sources"] = ts.get_source_count()
	var src = ts.get_source(ts.get_source_id(0))
	var tex = src.texture
	d["texture"] = tex.resource_path if tex else ""
	d["texture_size"] = [tex.get_width(), tex.get_height()] if tex else []
	d["margins"] = [src.margins.x, src.margins.y]
	d["separation"] = [src.separation.x, src.separation.y]
	d["region"] = [src.texture_region_size.x, src.texture_region_size.y]
	d["grid"] = [src.get_atlas_grid_size().x, src.get_atlas_grid_size().y]
	var tiles = {}
	for i in src.get_tiles_count():
		var c = src.get_tile_id(i)
		var td = {}
		var n = src.get_tile_animation_frames_count(c)
		if n > 1:
			td["animation_columns"] = src.get_tile_animation_columns(c)
			var durs = []
			for f in n:
				durs.append(src.get_tile_animation_frame_duration(c, f))
			td["durations"] = durs
		var data = src.get_tile_data(c, 0)
		td["probability"] = data.probability
		var polys = []
		if ts.get_physics_layers_count() > 0:
			for p in data.get_collision_polygons_count(0):
				var pts = []
				for v in data.get_collision_polygon_points(0, p):
					pts.append([v.x, v.y])
				polys.append(pts)
		td["polygons"] = polys
		var custom = {}
		for l in layers:
			var v = data.get_custom_data(l[0])
			if v != null and typeof(v) == TYPE_COLOR:
				v = [v.r8, v.g8, v.b8, v.a8]
			custom[l[0]] = v
		td["custom"] = custom
		td["terrain_set"] = data.terrain_set
		td["terrain"] = data.terrain
		tiles["%d:%d" % [c.x, c.y]] = td
	d["tiles"] = tiles
	print("TSEJSON " + JSON.stringify(d))
	quit()
