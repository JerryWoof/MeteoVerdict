import assert from "node:assert/strict";
import { test } from "node:test";

import { binLabel, count, etsColor, etsTextColor, farmChoices, farmGrid, farmRows, plain, score } from "./farm.js";

const COLUMNS = [
  "event", "threshold", "bin", "model", "units", "runs", "stations", "events",
  "hits", "misses", "false_alarms", "correct_negatives", "pod", "far", "csi", "ets", "bias",
];
const DOC = {
  bins: ["1-6", "7-12", "13-24", "25-48", "49-72", "73-120"],
  small_sample: 20,
  events: {
    frost: { thresholds: [0, -2] },
    gust: { thresholds: [10, 15, 20] },
  },
  columns: COLUMNS,
  rows: [
    // gust first in the file: the choices still follow the order of `events`
    ["gust", 10, "1-6", "a", 100, 2, 50, 30, 20, 10, 5, 65, 0.667, 0.2, 0.571, 0.45, 0.833],
    ["frost", 0, "13-24", "a", 300, 4, 95, 10, 8, 2, 3, 287, 0.8, 0.273, 0.615, 0.6, 1.1],
    ["frost", 0, "13-24", "b", 300, 4, 95, 10, 5, 5, 1, 289, 0.5, 0.167, 0.455, 0.44, 0.6],
    ["frost", 0, "13-24", "c", 300, 4, 95, 10, 2, 8, 0, 290, 0.2, 0.0, 0.2, 0.19, 0.2],
    ["frost", 0, "25-48", "a", 800, 9, 95, 40, 10, 30, 20, 740, 0.25, 0.667, 0.167, 0.12, 0.75],
    ["frost", 0, "25-48", "b", 800, 9, 95, 40, 20, 20, 10, 750, 0.5, 0.333, 0.4, 0.37, 0.75],
    ["frost", 0, "73-120", "c", 200, 2, 95, 0, 0, 0, 0, 200, null, null, null, null, null],
    ["frost", -2, "13-24", "a", 300, 4, 95, 3, 1, 2, 0, 297, 0.333, 0.0, 0.333, 0.33, 0.333],
  ],
};

test("rows and the event choices in the order of the file's events", () => {
  assert.equal(farmRows(DOC).length, 8);
  assert.deepEqual(farmRows(null), []);
  assert.deepEqual(farmChoices(DOC).map((c) => c.key), ["frost:0", "frost:-2", "gust:10"]);
});

test("the grid: bins with data, models by mean rank, best per bin, sample sizes", () => {
  const grid = farmGrid(DOC, "frost", 0);
  assert.deepEqual(grid.bins, ["13-24", "25-48", "73-120"]);
  // 13-24: a 0, b 0.5, c 1; 25-48: b 0, a 1 → a 0.5, b 0.25, c 1 (73-120 alone, no ETS)
  assert.deepEqual(grid.models, ["b", "a", "c"]);
  const [early, later, late] = grid.perBin;
  assert.deepEqual(early, { bin: "13-24", events: 10, units: 300, models: 3, small: true, best: ["a"] });
  assert.deepEqual(later.best, ["b"]);
  assert.equal(later.small, false);
  assert.deepEqual(late.best, []); // one model, no events
  const noSkill = { ...DOC, rows: DOC.rows.map((r) => (r[2] === "25-48" ? [...r.slice(0, 15), -0.01, r[16]] : r)) };
  assert.deepEqual(farmGrid(noSkill, "frost", 0).perBin[1].best, []); // nobody beats chance
  assert.equal(grid.cells.get("a|13-24").pod, 0.8);
  assert.equal(grid.cells.get("c|25-48"), undefined);
  assert.deepEqual(farmGrid(DOC, "rain3h", 0.5).bins, []);
});

test("plain-language reading: caught 8 of 10, 3 of 11 warnings false", () => {
  const row = farmGrid(DOC, "frost", 0).cells.get("a|13-24");
  assert.deepEqual(plain(row), { caught: 8, events: 10, falseWarnings: 3, warnings: 11 });
});

test("English number format and labels", () => {
  assert.equal(score(0.4567), "0.46");
  assert.equal(score(-0.05), "-0.05");
  assert.equal(score(-0.002), "0.00");
  assert.equal(score(null), "–");
  assert.equal(count(12345), "12,345");
  assert.equal(binLabel("13-24"), "H+13–24");
});

test("cell colours: white at no skill, dark green at high ETS, grey without a score", () => {
  assert.equal(etsColor(0), "rgb(255, 255, 255)");
  assert.equal(etsColor(-0.2), "rgb(255, 255, 255)");
  assert.equal(etsColor(0.9), "rgb(46, 125, 79)");
  assert.equal(etsColor(null), "#ece9e2");
  assert.equal(etsTextColor(0.6), "#ffffff");
  assert.equal(etsTextColor(0.1), "#1d2329");
});
