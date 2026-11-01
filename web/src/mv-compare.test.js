import assert from "node:assert/strict";
import { test } from "node:test";

import { MV_AI, MV_COLUMNS, MV_MODEL, modelId, periodEntry, regionRows, windowStart } from "./mv-compare.js";
import { bestByRegion, records } from "./data.js";

const DOC = {
  region: "CZ0100", name: "Praha", level: "okres",
  entries: {
    "temperature_2m/1": {
      days: 60, stations: 7, small_sample: false,
      series: [
        { id: "combined", kind: "outlook", mae: 0.7, low: 0, high: 0, p_best: 0.8, tied: false },
        { id: "blend", kind: "mean", mae: 0.8 },
        { id: "dwd_icon_d2", kind: "model", mae: 0.9, low: 0.05, high: 0.3, p_best: 0.1, tied: true },
        { id: "ai", kind: "ai", mae: 1.0, low: 0.1, high: 0.4, p_best: 0.1, tied: false },
      ],
    },
    "wind_speed_10m/2": { days: 60, stations: 2, series: [{ id: "x", kind: "model", mae: 1 }] },
  },
};

test("series ids: ours and the AI get the page's ids, the mean stays blend", () => {
  assert.equal(modelId({ kind: "outlook", id: "combined" }), MV_MODEL);
  assert.equal(modelId({ kind: "ai", id: "ai" }), MV_AI);
  assert.equal(modelId({ kind: "mean", id: "blend" }), "blend");
  assert.equal(modelId({ kind: "model", id: "ecmwf_ifs" }), "ecmwf_ifs");
});

test("rows rank the models, leave the mean unranked and work with the map's best-per-region", () => {
  const byVariable = regionRows(DOC, 3);
  const rows = records({ columns: MV_COLUMNS, rows: byVariable.get("temperature_2m") });
  assert.deepEqual(rows.map((r) => [r.model, r.rank]), [[MV_MODEL, 1], ["blend", null], ["dwd_icon_d2", 2], [MV_AI, 3]]);
  const best = bestByRegion(rows, 1).get("CZ0100");
  assert.equal(best.model, MV_MODEL);
  assert.equal(best.enough, true);
  assert.deepEqual(best.tied, ["dwd_icon_d2"]);
  // too few stations: the region is grey, as on the other maps
  assert.equal(bestByRegion(records({ columns: MV_COLUMNS, rows: byVariable.get("wind_speed_10m") }), 2).get("CZ0100").enough, false);
});

test("a file without entries gives nothing", () => {
  assert.equal(regionRows(null).size, 0);
  assert.equal(regionRows({ region: "X", entries: { "bad": {} } }).size, 0);
});

const LIVE = {
  region: "CZ0100", name: "Praha", level: "okres",
  entries: {
    "temperature_2m/1": {
      days: 10, stations: 7, small_sample: true,
      date_list: ["2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31"],
      series: [
        { id: "combined", kind: "outlook", mae: 0.5, daily: [9, 9, 9, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4] },
        { id: "ai", kind: "ai", mae: 0.9, daily: [0, 0, 0, 1, 1, 1, 1, 1, 1, 1] },
        { id: "ecmwf_ifs", kind: "model", mae: 0.8, daily: [0, 0, 0, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8] },
      ],
    },
  },
};

test("the week is the last 7 days up to the sample's end, the same days for every series", () => {
  assert.equal(windowStart("2026-10-31", 7), "2026-10-25");
  assert.equal(windowStart("2026-03-02", 7), "2026-02-24");
  const rows = regionRows(LIVE, 3, { from: "2026-10-25", to: "2026-10-31" }).get("temperature_2m");
  assert.deepEqual(rows.map((r) => [r[3], r[9], r[5]]), [[MV_MODEL, 1, 7], ["ecmwf_ifs", 2, 7], [MV_AI, 3, 7]]);
  assert.ok(Math.abs(rows[0][6] - 0.4) < 1e-9);
  const best = bestByRegion(records({ columns: MV_COLUMNS, rows }), 1).get("CZ0100");
  assert.equal(best.model, MV_MODEL);
  assert.equal(best.small, false);
});

test("a period with too few of its days, or a series without daily values, is left out", () => {
  assert.equal(periodEntry(LIVE.entries["temperature_2m/1"], { from: "2026-10-30", to: "2026-11-05" }), null);
  const noDaily = { ...LIVE.entries["temperature_2m/1"], series: [{ id: "combined", kind: "outlook", mae: 1 }] };
  assert.equal(periodEntry(noDaily, { from: "2026-10-25", to: "2026-10-31" }).series.length, 0);
});
