// Run by tests/check.py with Tiled's --evaluate: reads a tileset
// (.tsx or .tsj) with Tiled's own reader and prints what Tiled sees as
// one JSON line ("TSEJSON {...}"); with a second argument, also writes
// the tileset there with Tiled's own writer (.tsx or .tsj by the name).
//
// Copyright 2026 David
// SPDX-License-Identifier: GPL-3.0-or-later
var path = tiled.scriptArguments[0];
var fmtName = function (p) { return p.endsWith(".tsj") || p.endsWith(".json") ? "json" : "tsx"; };
var ts = tiled.tilesetFormat(fmtName(path)).read(path);
function props(p) {
    var out = {};
    for (var k in p) {
        var v = p[k];
        var t = typeof v;
        if (t === "object" && v !== null) { t = "object"; v = String(v); }
        out[k] = [t, v];
    }
    return out;
}
var d = {
    name: ts.name, className: ts.className, tileWidth: ts.tileWidth, tileHeight: ts.tileHeight,
    margin: ts.margin, tileSpacing: ts.tileSpacing, columnCount: ts.columnCount,
    tileCount: ts.tileCount, imageWidth: ts.imageWidth, imageHeight: ts.imageHeight,
    image: String(ts.image), properties: props(ts.properties()), wangSets: ts.wangSets.length,
    tiles: {}
};
for (var i = 0; i < ts.tileCount; i++) {
    var t = ts.tile(i);
    var td = { className: t.className, probability: t.probability, properties: props(t.properties()) };
    if (t.objectGroup) {
        td.objects = t.objectGroup.objects.map(function (o) {
            return { x: o.x, y: o.y, shape: o.shape,
                     polygon: o.polygon.map(function (p) { return [p.x + o.x, p.y + o.y]; }) };
        });
    }
    if (t.animated) td.frames = t.frames.map(function (f) { return [f.tileId, f.duration]; });
    d.tiles[i] = td;
}
tiled.log("TSEJSON " + JSON.stringify(d));
if (tiled.scriptArguments.length > 1) {
    var out = tiled.scriptArguments[1];
    var err = tiled.tilesetFormat(fmtName(out)).write(ts, out);
    tiled.log("TSEWRITE " + (err ? err : "ok"));
}
