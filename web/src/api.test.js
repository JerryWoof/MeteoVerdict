import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { HOURLY, SITE, indexDoc, okresCsv, okresDoc, okresModels } from "./api.js";
import { records } from "./data.js";

const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));
const OUTLOOK = load("outlook.json");
const HOURLY_DOC = load("outlook-hourly.json");
const WEIGHTS = load("weights-CZ0201.json");
const META = load("meta.json");
const SCORES = {
  temperature_2m: records(load("scores-90d-okres-temperature_2m.json")),
  precipitation_24h: records(load("scores-90d-okres-precipitation_24h.json")),
};
const BENESOV = { code: "CZ0201", name: "Benešov", lat: 49.717, lon: 14.7767 };
const DOC = okresDoc({ okres: BENESOV, outlook: OUTLOOK, hourly: HOURLY_DOC, weightsDoc: WEIGHTS, scores: SCORES, meta: META });

test("an okres file: forecast by hour and part of day, licence and attribution", () => {
  assert.equal(DOC.okres.code, "CZ0201");
  assert.match(DOC.licence, /CC BY-SA 4\.0/);
  assert.match(DOC.attribution, /Open-Meteo/);
  assert.equal(DOC.forecast.hourly.time.length, 144);
  for (const v of HOURLY) assert.equal(DOC.forecast.hourly[v].length, 144);
  assert.deepEqual(DOC.forecast.hourly.temperature_2m, HOURLY_DOC.okresy.CZ0201.temperature_2m);
  const parts = DOC.forecast.parts;
  assert.equal(parts.length, 6 * 5);
  assert.deepEqual(Object.keys(parts[0]), [
    "day", "part", "tmin", "tmax", "precipitation", "rain_probability", "wind", "cloud", "sunshine", "symbol",
    "sunrise", "sunset", "heavy_rain_probability", "heavy_rain",
    "night_min", "coldest_site", "coldest_min", "frost_probability", "frost", "ground_min", "ground_frost",
    "gust", "gust_over_threshold", "gust_warning",
  ]);
  // the saved outlook predates them: null, not missing
  assert.equal(parts[0].heavy_rain, null);
  assert.equal(parts[0].night_min, null);
  assert.equal(parts[0].gust, null);
});

test("the frost fields of an outlook row are passed through", () => {
  const columns = [...OUTLOOK.columns, "night_min", "coldest_site", "coldest_min", "frost_probability", "frost", "ground_min", "ground_frost"];
  const rows = OUTLOOK.rows.map((r) => [...r, -0.4, "Valley", -2.1, 0.6, true, -4.2, true]);
  const doc = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, weightsDoc: WEIGHTS, scores: SCORES, meta: META });
  const night = doc.forecast.parts[0];
  assert.equal(night.night_min, -0.4);
  assert.equal(night.coldest_site, "Valley");
  assert.equal(night.frost, true);
  assert.equal(night.ground_frost, true);
});

test("the gust fields of an outlook row are passed through", () => {
  const columns = [...OUTLOOK.columns, "gust", "gust_over_threshold", "gust_warning"];
  const rows = OUTLOOK.rows.map((r) => [...r, 14.2, true, true]);
  const doc = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, weightsDoc: WEIGHTS, scores: SCORES, meta: META });
  assert.equal(doc.forecast.parts[0].gust, 14.2);
  assert.equal(doc.forecast.parts[0].gust_over_threshold, true);
  assert.equal(doc.forecast.parts[0].gust_warning, true);
});

test("an outlook row with only the old gust_warning fills both fields", () => {
  const columns = [...OUTLOOK.columns, "gust", "gust_warning"];
  const rows = OUTLOOK.rows.map((r) => [...r, 14.2, true]);
  const doc = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, weightsDoc: WEIGHTS, scores: SCORES, meta: META });
  assert.equal(doc.forecast.parts[0].gust_over_threshold, true);
  assert.equal(doc.forecast.parts[0].gust_warning, true);
});

test("the files say the flags are thresholds, not ČHMÚ warnings", () => {
  assert.match(DOC.notice, /not official ČHMÚ warnings/);
  assert.match(DOC.notice, /chmi\.cz/);
  assert.match(DOC.deprecated.gust_warning, /gust_over_threshold/);
});

test("model ranking per variable and lead day, with the weights of our forecast", () => {
  const t = DOC.models.variables.temperature_2m;
  assert.deepEqual(Object.keys(t.lead_days), ["1", "2", "3", "4", "5"]);
  const d1 = t.lead_days[1];
  assert.equal(d1[0].rank, 1);
  assert.ok(d1.every((r) => r.model !== "blend"));
  assert.ok(d1.every((r) => typeof r.weight === "number"), "temperature weights attached");
  assert.ok(Math.abs(d1.reduce((s, r) => s + r.weight, 0) - 1) < 0.01);
  assert.equal(d1[0].name, META.models[d1[0].model]);
  // 06-06 precipitation is ranked but not part of our combination: no weights
  assert.ok(DOC.models.variables.precipitation_24h.lead_days[1].every((r) => r.weight === null));
  assert.equal(DOC.models.from, META.windows["90d"].from);
  assert.deepEqual(okresModels("CZ9999", SCORES, WEIGHTS, {}), {});
  // score files written before the block bootstrap have no p_best
  assert.ok(d1.every((r) => r.p_best === null && r.small_sample === false));
});

test("the probability of being best and the small-sample flag are passed on", () => {
  const rows = [
    { region: "CZ0201", model: "icon", lead_day: 1, rank: 1, mae: 1.1, p_best: 0.7234, small_sample: true },
    { region: "CZ0201", model: "ifs", lead_day: 1, rank: 2, mae: 1.2, p_best: 0.2766, small_sample: true },
  ];
  const lead = okresModels("CZ0201", { temperature_2m: rows }, null, {}).temperature_2m.lead_days[1];
  assert.deepEqual(lead.map((r) => [r.model, r.p_best, r.small_sample]), [["icon", 0.723, true], ["ifs", 0.277, true]]);
});

test("CSV of the hourly forecast", () => {
  const lines = okresCsv(DOC).trim().split("\n");
  assert.equal(lines[0], "time_utc,temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration");
  assert.equal(lines.length, 145);
  const first = lines[1].split(",");
  assert.equal(first[0], HOURLY_DOC.time[0]);
  assert.equal(Number(first[1]), HOURLY_DOC.okresy.CZ0201.temperature_2m[0]);
  const empty = okresDoc({ okres: { code: "X", name: "X" }, outlook: OUTLOOK, hourly: null, weightsDoc: null, scores: {}, meta: META });
  assert.equal(okresCsv(empty), "time_utc,temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration\n");
});

test("index: every okres with the addresses of its files", () => {
  const index = indexDoc([BENESOV], META, "2026-10-12T10:49+00:00");
  assert.equal(index.okresy[0].json, `${SITE}/api/v1/okresy/CZ0201.json`);
  assert.equal(index.okresy[0].csv, `${SITE}/api/v1/okresy/CZ0201.csv`);
  assert.equal(index.files.okres_json, `${SITE}/api/v1/okresy/{code}.json`);
  assert.equal(index.generated, "2026-10-12T10:49+00:00");
});
