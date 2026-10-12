import assert from "node:assert/strict";
import { test } from "node:test";

import { biasByElevation, fmt, rankingTable } from "./compare.js";
import { records } from "./data.js";

const CZ = records({
  columns: ["region", "lead_day", "model", "stations", "days", "mae", "bias", "rmse", "rank", "diff_ci_low", "diff_ci_high", "tied_with_best"],
  rows: [
    ["cz", 1, "ifs", 450, 90, 1.3, 0.2, 1.7, 2, 0.02, 0.15, false],
    ["cz", 1, "blend", 450, 90, 1.1, 0.0, 1.4, null, -0.3, -0.1, true],
    ["cz", 1, "icon", 450, 90, 1.2, -0.1, 1.6, 1, 0, 0, false],
    ["cz", 2, "icon", 450, 90, 1.5, -0.1, 1.9, 1, 0, 0, false],
  ],
});

test("ranked models first, the blend last, differences to the best", () => {
  const table = rankingTable(CZ, 1);
  assert.deepEqual(table.map((r) => r.model), ["icon", "ifs", "blend"]);
  assert.equal(table[0].diff, 0);
  assert.ok(Math.abs(table[1].diff - 0.1) < 1e-9);
  assert.ok(table[2].diff < 0);
  assert.deepEqual(table[1].ci, [0.02, 0.15]);
});

test("bias by elevation class, in order, without the blend", () => {
  const rows = records({
    columns: ["region", "lead_day", "model", "bias"],
    rows: [
      ["mountain", 1, "icon", -0.8],
      ["lowland", 1, "icon", 0.1],
      ["lowland", 1, "blend", 0.0],
      ["upland", 2, "icon", 0.3],
    ],
  });
  assert.deepEqual(biasByElevation(rows, 1), [
    { elevation: "lowland", model: "icon", bias: 0.1 },
    { elevation: "mountain", model: "icon", bias: -0.8 },
  ]);
});

test("number format", () => {
  assert.equal(fmt(1.234), "1.23");
  assert.equal(fmt(0.5, true), "+0.50");
  assert.equal(fmt(-0.5, true), "-0.50");
  assert.equal(fmt(null), "–");
});
