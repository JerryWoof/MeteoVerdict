import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  bestModel, combine, dailySummary, forecastUrl, leadDay, localDay, parseForecast,
  weightTable, weightedModels, weightsAt,
} from "./forecast.js";

// real samples: the Open-Meteo Forecast API at Benešov's point (12 Oct 2026) and the
// weights `mvd aggregate` wrote for okres Benešov from the published September scores
const API = JSON.parse(readFileSync(new URL("./fixtures/open-meteo-forecast-CZ0201.json", import.meta.url)));
const WEIGHTS = JSON.parse(readFileSync(new URL("./fixtures/weights-CZ0201.json", import.meta.url)));
const TABLE = weightTable(WEIGHTS);
const MODELS = weightedModels(TABLE);
const FORECAST = parseForecast(API, MODELS);
const NOW = Date.parse("2026-10-12T06:00Z");

test("request: all models, three variables, UTC, m/s", () => {
  const url = new URL(forecastUrl({ lat: 49.717, lon: 14.7767 }, ["a", "b"]));
  assert.equal(url.origin + url.pathname, "https://api.open-meteo.com/v1/forecast");
  assert.equal(url.searchParams.get("models"), "a,b");
  assert.equal(url.searchParams.get("hourly"), "temperature_2m,precipitation,wind_speed_10m");
  assert.equal(url.searchParams.get("timezone"), "GMT");
  assert.equal(url.searchParams.get("wind_speed_unit"), "ms");
});

test("parsing the API answer per variable and model", () => {
  assert.equal(FORECAST.times.length, 144);
  assert.equal(FORECAST.times[0], Date.parse("2026-10-12T00:00Z"));
  assert.equal(MODELS.length, 11);
  // every model sent temperature; the short-range ones end early
  assert.deepEqual(Object.keys(FORECAST.values.temperature_2m).sort(), [...MODELS].sort());
  const d2 = FORECAST.values.temperature_2m.dwd_icon_d2;
  assert.equal(d2.at(-1), null);
  assert.equal(typeof d2[0], "number");
});

test("lead day: the next 24 h use D+1, at most D+5", () => {
  assert.equal(leadDay(NOW - 3 * 3600e3, NOW), 1);
  assert.equal(leadDay(NOW + 23 * 3600e3, NOW), 1);
  assert.equal(leadDay(NOW + 49 * 3600e3, NOW), 2);
  assert.equal(leadDay(NOW + 10 * 86400e3, NOW), 5);
});

test("weights per variable and lead day, falling back to a shorter lead day", () => {
  const d1 = weightsAt(TABLE, "temperature_2m", 1);
  assert.ok(Math.abs(d1.reduce((s, r) => s + r.weight, 0) - 1) < 1e-3);
  assert.equal(bestModel(TABLE, "temperature_2m", 1), d1.find((r) => r.rank === 1).model);
  assert.deepEqual(weightsAt(TABLE, "temperature_2m", 9), weightsAt(TABLE, "temperature_2m", 5));
  assert.deepEqual(weightsAt(TABLE, "nothing", 1), []);
});

test("combined temperature: weighted, bias-corrected, rescaled over the models present", () => {
  const combined = combine(FORECAST, TABLE, "temperature_2m", NOW);
  const i = FORECAST.times.indexOf(Date.parse("2026-10-12T12:00Z"));
  let sum = 0;
  let total = 0;
  for (const r of weightsAt(TABLE, "temperature_2m", 1)) {
    const v = FORECAST.values.temperature_2m[r.model]?.[i];
    if (v == null) continue;
    sum += r.weight * (v - r.correction);
    total += r.weight;
  }
  assert.ok(Math.abs(combined[i] - sum / total) < 1e-9);
  const values = Object.values(FORECAST.values.temperature_2m).map((s) => s[i]);
  assert.ok(combined[i] >= Math.min(...values) - 1 && combined[i] <= Math.max(...values) + 1);
  // the last hour still has the global models
  assert.equal(typeof combined.at(-1), "number");
});

test("combined precipitation and wind are never negative; too few models give null", () => {
  for (const variable of ["precipitation", "wind_speed_10m"]) {
    assert.ok(combine(FORECAST, TABLE, variable, NOW).every((v) => v == null || v >= 0));
  }
  const one = { times: [NOW], values: { temperature_2m: { a: [10] } } };
  const table = new Map([["temperature_2m|1", [{ model: "a", weight: 1, correction: 0 }]]]);
  assert.deepEqual(combine(one, table, "temperature_2m", NOW), [null]);
  assert.deepEqual(combine(one, table, "temperature_2m", NOW, 1), [10]);
  const biased = new Map([["wind_speed_10m|1", [{ model: "a", weight: 1, correction: 2 }]]]);
  const calm = { times: [NOW], values: { wind_speed_10m: { a: [1] } } };
  assert.deepEqual(combine(calm, biased, "wind_speed_10m", NOW, 1), [0]);
});

test("daily summary in Prague time", () => {
  assert.equal(localDay(Date.parse("2026-10-12T22:30Z"), "Europe/Prague"), "2026-10-13");
  const series = Object.fromEntries(
    ["temperature_2m", "precipitation", "wind_speed_10m"].map((v) => [v, combine(FORECAST, TABLE, v, NOW)]),
  );
  const days = dailySummary(FORECAST.times, series);
  // UTC midnight is 02:00 in Prague: the first local day has only 22 hours, the last too
  assert.equal(days[0].day, "2026-10-12");
  assert.ok(days.length >= 5);
  for (const d of days) {
    assert.ok(d.tmin <= d.tmax);
    assert.ok(d.precipitation >= 0 && d.wind >= 0);
  }
});
