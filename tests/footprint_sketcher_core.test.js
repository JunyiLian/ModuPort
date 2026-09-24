"use strict";

const assert = require("node:assert/strict");
const Core = require("../web/footprint_component/sketcher_core.js");

const cells = (set) => Core.sortedCells(set);

assert.deepEqual(Core.lineCells([0, 0], [0, 4]), [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4]], "fast pointer movement must interpolate crossed cells");

let footprint = new Set();
footprint = Core.applyStroke(footprint, [[0, 0], [0, 1], [0, 1], [1, 1], [2, 1]], false);
assert.deepEqual(cells(footprint), [[0, 0], [0, 1], [1, 1], [2, 1]], "brush should add each traversed cell once");

footprint = Core.applyStroke(footprint, [[0, 1], [1, 1], [1, 1]], true);
assert.deepEqual(cells(footprint), [[0, 0], [2, 1]], "erase stroke should remove traversed cells");

footprint = Core.applyRectangle(new Set(), [0, 0], [1, 2], false);
footprint = Core.applyRectangle(footprint, [1, 1], [2, 3], false);
assert.equal(footprint.size, 10, "overlapping rectangle additions should be a set union");

footprint = Core.applyRectangle(new Set(Core.rectangleKeys([0, 0], [3, 3])), [1, 1], [2, 2], true);
assert.equal(footprint.size, 12, "erase rectangle should subtract an internal opening");
assert(!footprint.has("1,1") && footprint.has("0,0"));

const history = new Core.History([], 5);
const first = Core.applyStroke(history.current(), [[0, 0], [0, 1]], false);
assert(history.commit(first));
const second = Core.applyRectangle(history.current(), [1, 0], [1, 1], false);
assert(history.commit(second));
assert.deepEqual(cells(history.undo()), [[0, 0], [0, 1]], "undo should exactly restore prior footprint");
assert.deepEqual(cells(history.redo()), [[0, 0], [0, 1], [1, 0], [1, 1]], "redo should exactly restore operation");

assert.equal(Core.connected(new Set(["0,0", "0,1", "1,1"])), true);
assert.equal(Core.connected(new Set(["0,0", "2,0"])), false);
assert.deepEqual(cells(Core.normalizeCells([[1, 1], [0, 0], [1, 1], [-1, 0], [9, 9]], 2, 2)), [[0, 0], [1, 1]]);

console.log("footprint sketcher core tests: PASS");
