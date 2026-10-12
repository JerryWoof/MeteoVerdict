import assert from "node:assert/strict";
import { test } from "node:test";

import { seriesRows } from "./series.js";

// the layout `mvd aggregate` writes (aggregate.write_series)
const DOC = {
  from: "2026-07-03",
  to: "2026-09-30",
  series: { temperature_2m: { 1: { icon: [1.2, null, 0.8], ifs: [1.5, 1.4, null] } } },
};

test("one row per scored day and model", () => {
  const rows = seriesRows(DOC, "temperature_2m", 1);
  assert.equal(rows.length, 4);
  assert.deepEqual(rows[0], { date: new Date("2026-07-03T00:00:00Z"), model: "icon", mae: 1.2 });
  assert.deepEqual(rows[1].date, new Date("2026-07-05T00:00:00Z"));
});

test("missing variable, lead day or file", () => {
  assert.deepEqual(seriesRows(DOC, "wind_speed_10m", 1), []);
  assert.deepEqual(seriesRows(DOC, "temperature_2m", 3), []);
  assert.deepEqual(seriesRows(null, "temperature_2m", 1), []);
});
