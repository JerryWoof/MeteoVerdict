import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  COMBINED, modelDays, modelEnd, modelOptions,
  bestModel, bestPerLeadDay, winnersByLeadDay, dailySummary, leadDay, localDay, localTime,
  nightBands, parseForecast, weightTable, weightedModels, weightsAt,
} from "./forecast.js";
import { parseOutlook, sunFor } from "./tv.js";

// real samples: the Open-Meteo Forecast API at Benešov's point (12 Oct 2026) and the
// weights `mvd aggregate` wrote for okres Benešov from the published September scores
const API = JSON.parse(readFileSync(new URL("./fixtures/open-meteo-forecast-CZ0201.json", import.meta.url)));
const WEIGHTS = JSON.parse(readFileSync(new URL("./fixtures/ranking-CZ0201.json", import.meta.url)));
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

test("the ranking per variable and lead day, falling back to a shorter lead day", () => {
  const d1 = weightsAt(TABLE, "temperature_2m", 1);
  assert.ok(d1.length > 3 && d1.every((r) => !("weight" in r)));
  assert.equal(bestModel(TABLE, "temperature_2m", 1), d1.find((r) => r.rank === 1).model);
  assert.deepEqual(weightsAt(TABLE, "temperature_2m", 9), weightsAt(TABLE, "temperature_2m", 5));
  assert.deepEqual(weightsAt(TABLE, "nothing", 1), []);
});

test("daily summary in Prague time", () => {
  assert.equal(localDay(Date.parse("2026-10-12T22:30Z"), "Europe/Prague"), "2026-10-13");
  // the models' mean stands in for the combination: only the summary is tested
  const series = Object.fromEntries(
    ["temperature_2m", "precipitation", "wind_speed_10m"].map((v) => {
      const columns = Object.values(FORECAST.values[v]);
      return [v, FORECAST.times.map((_, i) => {
        const have = columns.map((c) => c[i]).filter((x) => x != null);
        return have.length >= 2 ? have.reduce((a, b) => a + b, 0) / have.length : null;
      })];
    }),
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
