import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { test } from "node:test";

import { levelOf, rankingTable } from "./compare.js";
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

test("a model with too short a record comes last, unranked and out of the charts", () => {
  const withShort = [
    ...CZ.map((r) => ({ ...r, short_record: false, coverage: 1 })),
    { region: "cz", lead_day: 1, model: "new", stations: 450, days: 10, mae: 0.9, bias: 0, rmse: 1.1, rank: null, short_record: true, coverage: 0.25 },
  ];
  const table = rankingTable(withShort, 1);
  assert.deepEqual(table.map((r) => r.model), ["icon", "ifs", "blend", "new"]);
  assert.equal(table.at(-1).short, true);
  assert.equal(table.at(-1).coverage, 0.25);
  assert.equal(table[0].short, false);
  // files from before the rule have no short_record: nothing changes
  assert.deepEqual(rankingTable(CZ, 1).map((r) => r.short), [false, false, false]);
});

const OKRES = records(JSON.parse(readFileSync(new URL("./fixtures/scores-90d-okres-precipitation_24h.json", import.meta.url))));

test("levels of region codes", () => {
  assert.equal(levelOf("cz"), "cz");
  assert.equal(levelOf("CZ064"), "kraj");
  assert.equal(levelOf("CZ0642"), "okres");
  assert.equal(levelOf("CZ020A"), "okres");
});

test("levels of region codes", () => {
  assert.equal(levelOf("cz"), "cz");
  assert.equal(levelOf("CZ064"), "kraj");
  assert.equal(levelOf("CZ0642"), "okres");
  assert.equal(levelOf("CZ020A"), "okres");
});

test("ranking of one okres, with skill against the mean and event scores", () => {
  const table = rankingTable(OKRES, 1, "CZ0423");
  assert.equal(table[0].rank, 1);
  assert.equal(table.at(-1).model, "blend");
  assert.equal(table.at(-1).skill, null);
  const blend = table.at(-1);
  for (const r of table.slice(0, -1)) {
    assert.ok(Math.abs(r.skill - (1 - r.mae / blend.mae)) < 1e-12);
  }
  assert.ok(table.every((r) => r.ets == null || (r.ets >= -1 / 3 && r.ets <= 1)));
  assert.ok(table.every((r) => r.stations >= 3));
  assert.deepEqual(rankingTable(OKRES, 1, "CZ9999"), []);
});
