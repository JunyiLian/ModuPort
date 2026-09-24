(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ModuPortFootprintCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const keyOf = (row, column) => `${row},${column}`;

  function parseKey(key) {
    const [row, column] = key.split(",").map(Number);
    return [row, column];
  }

  function normalizeCells(cells, rows, columns) {
    const output = new Set();
    for (const cell of cells || []) {
      if (!Array.isArray(cell) || cell.length !== 2) continue;
      const row = Number(cell[0]);
      const column = Number(cell[1]);
      if (Number.isInteger(row) && Number.isInteger(column) && row >= 0 && row < rows && column >= 0 && column < columns) {
        output.add(keyOf(row, column));
      }
    }
    return output;
  }

  function sortedCells(cellSet) {
    return Array.from(cellSet, parseKey).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  }

  function rectangleKeys(start, end) {
    const keys = [];
    const top = Math.min(start[0], end[0]);
    const bottom = Math.max(start[0], end[0]);
    const left = Math.min(start[1], end[1]);
    const right = Math.max(start[1], end[1]);
    for (let row = top; row <= bottom; row += 1) {
      for (let column = left; column <= right; column += 1) keys.push(keyOf(row, column));
    }
    return keys;
  }

  function lineCells(start, end) {
    const output = [];
    let row = start[0], column = start[1];
    const deltaColumn = Math.abs(end[1] - column), stepColumn = column < end[1] ? 1 : -1;
    const deltaRow = -Math.abs(end[0] - row), stepRow = row < end[0] ? 1 : -1;
    let error = deltaColumn + deltaRow;
    while (true) {
      output.push([row, column]);
      if (row === end[0] && column === end[1]) break;
      const doubled = 2 * error;
      if (doubled >= deltaRow) { error += deltaRow; column += stepColumn; }
      if (doubled <= deltaColumn) { error += deltaColumn; row += stepRow; }
    }
    return output;
  }

  function connected(cellSet) {
    if (cellSet.size === 0) return false;
    const first = cellSet.values().next().value;
    const visited = new Set([first]);
    const queue = [first];
    while (queue.length) {
      const [row, column] = parseKey(queue.pop());
      for (const [nextRow, nextColumn] of [[row - 1, column], [row + 1, column], [row, column - 1], [row, column + 1]]) {
        const key = keyOf(nextRow, nextColumn);
        if (cellSet.has(key) && !visited.has(key)) {
          visited.add(key);
          queue.push(key);
        }
      }
    }
    return visited.size === cellSet.size;
  }

  function applyStroke(cellSet, traversedCells, erase) {
    const output = new Set(cellSet || []);
    const visited = new Set();
    for (const cell of traversedCells || []) {
      const key = keyOf(cell[0], cell[1]);
      if (visited.has(key)) continue;
      visited.add(key);
      if (erase) output.delete(key); else output.add(key);
    }
    return output;
  }

  function applyRectangle(cellSet, start, end, erase) {
    const output = new Set(cellSet || []);
    for (const key of rectangleKeys(start, end)) {
      if (erase) output.delete(key); else output.add(key);
    }
    return output;
  }

  class History {
    constructor(initialCells, limit) {
      this.limit = Math.max(2, Number(limit) || 50);
      this.stack = [new Set(initialCells || [])];
      this.index = 0;
    }

    current() {
      return new Set(this.stack[this.index]);
    }

    commit(cells) {
      const next = new Set(cells);
      const previous = this.stack[this.index];
      if (next.size === previous.size && Array.from(next).every((key) => previous.has(key))) return false;
      this.stack = this.stack.slice(0, this.index + 1);
      this.stack.push(next);
      if (this.stack.length > this.limit) this.stack.shift();
      this.index = this.stack.length - 1;
      return true;
    }

    undo() {
      if (this.index > 0) this.index -= 1;
      return this.current();
    }

    redo() {
      if (this.index < this.stack.length - 1) this.index += 1;
      return this.current();
    }

    get canUndo() { return this.index > 0; }
    get canRedo() { return this.index < this.stack.length - 1; }
  }

  return { keyOf, parseKey, normalizeCells, sortedCells, rectangleKeys, lineCells, connected, applyStroke, applyRectangle, History };
});
