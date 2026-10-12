import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  bestModel, bestPerLeadDay, combine, taper, winnersByLeadDay, dailySummary, forecastUrl, leadDay, localDay, localTime,
  nightBands, parseForecast, weightTable, weightedModels, weightsAt,
} from "./forecast.js";
import { parseOutlook, sunFor } from "./tv.js";

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
    const w = r.weight * taper(FORECAST.values.temperature_2m[r.model])[i];
    sum += w * (v - r.correction);
    total += w;
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

test("a model that ends early fades out over its last three hours", () => {
  assert.deepEqual(taper([1, 2, 3, 4, 5, 6]), [1, 1, 1, 1, 1, 1]);
  assert.deepEqual(taper([1, 2, 3, 4, 5, null, null]), [1, 1, 0.75, 0.5, 0.25, 0, -0.25].map((v) => Math.min(1, v)));
  const d2 = FORECAST.values.temperature_2m.dwd_icon_d2;
  const fade = taper(d2);
  const last = d2.findLastIndex((v) => v != null);
  assert.deepEqual(fade.slice(last - 3, last + 1), [1, 0.75, 0.5, 0.25]);
  // the combined curve has no jump where ICON-D2 ends: neighbouring hours stay close
  const combined = combine(FORECAST, TABLE, "temperature_2m", NOW);
  assert.ok(Math.abs(combined[last + 1] - combined[last]) < 1.5);
});

test("the best model can differ per lead day", () => {
  const winners = winnersByLeadDay(TABLE, "temperature_2m");
  assert.deepEqual(winners.map((w) => w.lead), [1, 2, 3, 4, 5]);
  for (const w of winners) assert.equal(w.model, bestModel(TABLE, "temperature_2m", w.lead));
  const best = bestPerLeadDay(FORECAST, TABLE, "temperature_2m", NOW);
  assert.equal(best.length, FORECAST.times.length);
  // each hour takes the winner of its own lead day, or the next ranked model if it ended
  FORECAST.times.forEach((time, i) => {
    const ranked = weightsAt(TABLE, "temperature_2m", leadDay(time, NOW))
      .filter((r) => r.rank != null)
      .sort((a, b) => a.rank - b.rank);
    const expected = ranked.find((r) => FORECAST.values.temperature_2m[r.model]?.[i] != null);
    assert.equal(best[i].model, expected?.model ?? null);
  });
  const models = new Set(best.map((b) => b.model));
  assert.ok(models.size >= 2, "more than one model wins over six days");
});

test("local wall-clock time to UTC, across the end of summer time", () => {
  assert.equal(localTime("2026-10-12", "07:17"), Date.parse("2026-10-12T05:17Z"));
  assert.equal(localTime("2026-10-24", "18:00"), Date.parse("2026-10-24T16:00Z"));
  // summer time ends at 03:00 on 25 Oct 2026
  assert.equal(localTime("2026-10-25", "07:00"), Date.parse("2026-10-25T06:00Z"));
  assert.equal(localTime("2026-01-05", "23:30"), Date.parse("2026-01-05T22:30Z"));
});

test("nights on the chart from the okres's sunrise and sunset in outlook.json", () => {
  const outlook = parseOutlook(JSON.parse(readFileSync(new URL("./fixtures/outlook.json", import.meta.url))));
  const start = FORECAST.times[0];
  const end = FORECAST.times.at(-1);
  const nights = nightBands((day) => sunFor(outlook, "CZ0201", day), start, end);
  // the chart starts and ends at night: 6 days of outlook give 7 night bands
  assert.equal(nights.length, 7);
  assert.deepEqual(nights[0], { start, end: Date.parse("2026-10-12T05:17Z") });
  assert.deepEqual(nights[1], { start: Date.parse("2026-10-12T16:16Z"), end: Date.parse("2026-10-13T05:19Z") });
  assert.deepEqual(nights[6], { start: Date.parse("2026-10-17T16:06Z"), end });
  for (const n of nights) assert.ok(n.start < n.end && n.start >= start && n.end <= end);
});

test("no sun times (older outlook files): no nights; one known day: its nights estimated", () => {
  const start = Date.parse("2026-10-12T00:00Z");
  const end = Date.parse("2026-10-14T23:00Z");
  assert.deepEqual(nightBands(() => null, start, end), []);
  const one = (day) => (day === "2026-10-13" ? { sunrise: "07:19", sunset: "18:14" } : null);
  assert.deepEqual(nightBands(one, start, end), [
    { start: Date.parse("2026-10-12T16:14Z"), end: Date.parse("2026-10-13T05:19Z") },
    { start: Date.parse("2026-10-13T16:14Z"), end: Date.parse("2026-10-14T05:19Z") },
  ]);
});
