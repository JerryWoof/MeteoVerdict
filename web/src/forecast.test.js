import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  COMBINED, modelDays, modelEnd, modelOptions,
  bestModel, bestPerLeadDay, combine, correctionAt, taper, winnersByLeadDay, dailySummary, leadDay, localDay, localTime,
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

test("slot corrections are interpolated by UTC hour (as combine.hourly_correction)", () => {
  const r = { correction: 9, correction_00: 0, correction_06: 2, correction_12: 4, correction_18: 6 };
  const at = (h) => correctionAt(r, Date.parse(`2026-10-12T${String(h).padStart(2, "0")}:00Z`));
  assert.deepEqual([0, 3, 6, 12, 21].map(at), [0, 1, 2, 4, 3]);
  assert.equal(correctionAt({ correction: 9 }, NOW), 9);
});

test("the regression weights are used only when all their models have a value", () => {
  const t0 = Date.parse("2026-10-12T00:00Z");
  const now = t0 - 3600 * 1000;
  const slots = { correction_00: 1, correction_06: 1, correction_12: 1, correction_18: 1 };
  const table = new Map([["temperature_2m|1", [
    { model: "a", weight: 0.5, correction: 1, mos_weight: 1.5, mos_models: 2, ...slots },
    { model: "b", weight: 0.5, correction: 1, mos_weight: -0.5, mos_models: 2, ...slots },
    { model: "c", weight: 0.5, correction: 0, mos_weight: null, mos_models: null },
  ]]]);
  const both = { times: [t0, t0], values: { temperature_2m: { a: [11, 11], b: [13, 13], c: [20, 20] } } };
  // Σ mos_weight · (forecast − correction) = 1.5 · 10 − 0.5 · 12
  assert.deepEqual(combine(both, table, "temperature_2m", now, 1), [9, 9]);
  const missing = { times: [t0], values: { temperature_2m: { a: [11], c: [20] } } };
  // b is missing: the inverse-error weights over a and c
  assert.deepEqual(combine(missing, table, "temperature_2m", now, 1), [15]);
});

// --- which forecast the page shows -----------------------------------------------------

test("selector options: the combination, then scored models by mean rank, then the rest", () => {
  const table = weightTable({
    columns: ["variable", "lead_day", "model", "weight", "rank"],
    rows: [
      ["temperature_2m", 1, "b", 0.5, 1],
      ["temperature_2m", 1, "a", 0.3, 2],
      ["temperature_2m", 1, "c", 0.2, 3],
      ["temperature_2m", 2, "b", 0.2, 3],
      ["temperature_2m", 2, "a", 0.5, 1],
      ["temperature_2m", 2, "c", 0.3, 2],
    ],
  });
  const names = { a: "Alpha", b: "Beta", c: "Gamma", z: "Zulu", y: "Yankee", blend: "Mean of all models" };
  const options = modelOptions(table, names);
  // a and b both have mean rank 1.5: the larger mean weight (a 0.4, b 0.35) first
  assert.deepEqual(options.map((o) => o.model), [COMBINED, "a", "b", "c", "y", "z"]);
  assert.deepEqual(options.map((o) => o.position), [null, 1, 2, 3, null, null]);
  assert.deepEqual(options.map((o) => o.scored), [false, true, true, true, false, false]);
  assert.ok(Math.abs(options[1].weight - 0.4) < 1e-9);
  assert.equal(options[3].rank, 2.5);
});

test("selector options with the real Benešov weights: every weighted model once", () => {
  const options = modelOptions(TABLE, {});
  assert.equal(options[0].model, COMBINED);
  assert.deepEqual(options.slice(1).map((o) => o.model).sort(), [...MODELS].sort());
  for (let i = 2; i < options.length; i += 1) assert.ok(options[i - 1].rank <= options[i].rank);
});

test("a single model's days: raw values, days beyond its horizon empty", () => {
  const times = Array.from({ length: 72 }, (_, i) => Date.parse("2026-10-12T22:00Z") + i * 3600 * 1000);
  const short = times.map((_, i) => (i < 30 ? 10 + (i % 5) : null)); // ends in the second day
  const forecast = {
    times,
    values: {
      temperature_2m: { m: short },
      precipitation: { m: times.map((_, i) => (i < 30 ? 0.5 : null)) },
      wind_speed_10m: { m: times.map((_, i) => (i < 30 ? 3 : null)) },
    },
  };
  const days = modelDays(forecast, "m", ["2026-10-13", "2026-10-14", "2026-10-15"]);
  assert.deepEqual(days[0], { day: "2026-10-13", tmin: 10, tmax: 14, precipitation: 12, wind: 3 });
  for (const d of days.slice(1)) {
    assert.equal(d.beyond, true);
    assert.equal(d.tmin, null);
    assert.equal(d.precipitation, null);
  }
  assert.equal(modelEnd(forecast, "m"), times[29]);
  assert.equal(modelEnd(forecast, "nothing"), null);
  // no correction: with the real answer, exactly the model's own daily summary
  const model = MODELS[0];
  const raw = dailySummary(FORECAST.times, Object.fromEntries(
    ["temperature_2m", "precipitation", "wind_speed_10m"].map((v) => [v, FORECAST.values[v][model] ?? []]),
  ));
  assert.ok(raw.length > 0);
  assert.deepEqual(modelDays(FORECAST, model, raw.map((d) => d.day)), raw);
});

test("selector options limited to the models with a forecast file", () => {
  const table = weightTable({
    columns: ["variable", "lead_day", "model", "weight", "rank"],
    rows: [
      ["temperature_2m", 1, "b", 0.5, 1],
      ["temperature_2m", 1, "a", 0.3, 2],
      ["temperature_2m", 1, "c", 0.2, 3],
    ],
  });
  const names = { a: "Alpha", b: "Beta", c: "Gamma", z: "Zulu" };
  // c has no forecast this run, x has one but no scores here (and no name in meta.json)
  const options = modelOptions(table, names, new Set(["a", "b", "x"]));
  assert.deepEqual(options.map((o) => o.model), [COMBINED, "b", "a", "x"]);
  // positions stay 1, 2, … without a gap
  assert.deepEqual(options.map((o) => o.position), [null, 1, 2, null]);
  assert.deepEqual(options.map((o) => o.scored), [false, true, true, false]);
});
