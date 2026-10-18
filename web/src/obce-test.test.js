import assert from "node:assert/strict";
import { test } from "node:test";

import { obecSeries, obecTimes, placeOf } from "./obce-test.js";

const doc = {
  times: ["2026-10-18T02:00+00:00", "2026-10-18T03:00+00:00"],
  places: [
    { name: "Lovosice", elevation: 160, temperature_2m: [9, 8], precipitation: [0, 0.2], wind_speed_10m: [2, 3], models: { m1: [9.1, 8.2] } },
  ],
};

test("an obec's series as the forecast page wants them", () => {
  assert.deepEqual(obecTimes(doc), [Date.parse("2026-10-18T02:00Z"), Date.parse("2026-10-18T03:00Z")]);
  assert.equal(placeOf(doc, "Bechlín"), null);
  const { forecast, combined } = obecSeries(doc, placeOf(doc, "Lovosice"));
  assert.deepEqual(forecast.values.temperature_2m, { m1: [9.1, 8.2] });
  assert.deepEqual(forecast.values.precipitation, {});
  assert.deepEqual(combined.precipitation, [0, 0.2]);
});
