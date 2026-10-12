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
  assert.deepEqual(Object.keys(parts[0]), ["day", "part", "tmin", "tmax", "precipitation", "rain_probability", "wind", "cloud", "sunshine", "symbol", "sunrise", "sunset"]);
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
