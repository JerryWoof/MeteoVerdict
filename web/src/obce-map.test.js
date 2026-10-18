import assert from "node:assert/strict";
import { test } from "node:test";

import { obcePartRows } from "./obce-map.js";

test("an obec's parts of day, as the outlook sums them", () => {
  // 18 Oct 2026, Prague = UTC+2: 10:00Z..15:00Z is 12-18 local
  const times = [9, 10, 11, 12, 13, 14, 15].map((h) => `2026-10-18T${String(h).padStart(2, "0")}:00+00:00`);
  const doc = {
    times,
    places: [{
      name: "Lovosice",
      temperature_2m: [10, 11, 12, 14, 13, 12, 11],
      precipitation: [0, 0.4, 0, 0, 0.2, 0, 0],
      wind_speed_10m: [1, 2, 3, 2, 1, 1, 1],
    }],
  };
  const rows = obcePartRows(doc).get("Lovosice");
  const afternoon = rows.get("2026-10-18|afternoon");
  // 12:00..17:00 local: the values at 10Z..15Z
  assert.equal(afternoon.tmax, 14);
  assert.equal(afternoon.tmin, 11);
  assert.equal(afternoon.wind, 3);
  // rain in the hour ending at the time: 10Z (11-12 local) is the morning's, 13Z the afternoon's
  assert.equal(afternoon.precipitation, 0.2);
  assert.equal(afternoon.single, true);
  // too few hours for a whole day
  assert.equal(rows.has("2026-10-18|day"), false);
});
