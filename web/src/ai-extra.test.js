import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { extraDisplay, dayWindDirection } from "./ai-extra.js";
import { extraSeries, parseAi, parseExtra } from "./ai-model.js";

const NOW = Date.parse("2026-10-12T12:00:00Z");
const fixture = () => JSON.parse(readFileSync(new URL("./fixtures/ai-forecast-extra.json", import.meta.url), "utf8"));

test("parseExtra reads the block, null without it", () => {
  assert.equal(parseExtra({ okresy: {} }), null);
  assert.equal(parseExtra({ extra: "x" }), null);
  const extra = parseExtra(fixture());
  assert.equal(extra.sources.pressure_msl, "reference");
  assert.equal(extra.status.cape, "reference");
});

test("extraSeries: the ai series where sources says ai, else the reference; labels by status", () => {
  const ai = parseAi(fixture(), NOW);
  const series = extraSeries(ai, "CZ0201");
  const by = Object.fromEntries(series.map((s) => [s.variable, s]));
  assert.equal(by.relative_humidity_2m.source, "ai");
  assert.equal(by.relative_humidity_2m.status, "unverified");
  assert.equal(by.relative_humidity_2m.values[120], null, "AI is null beyond D+4");
  assert.equal(by.pressure_msl.source, "reference");
  assert.equal(by.pressure_msl.status, "reference");
  assert.ok(by.pressure_msl.values[120] != null);
  assert.equal(by.cape.status, "reference", "CAPE is always the reference");
  assert.equal(by.cape.unit, "J/kg");
});

test("an older file without extra shows nothing new", () => {
  const old = fixture();
  delete old.extra;
  for (const o of Object.values(old.okresy)) {
    for (const k of Object.keys(o)) if (!["time", "temperature_2m", "wind_speed_10m"].includes(k)) delete o[k];
  }
  const ai = parseAi(old, NOW);
  assert.equal(ai.extra, null);
  assert.deepEqual(extraSeries(ai, "CZ0201"), []);
});

test("extraDisplay: fog as %, snow only when above zero", () => {
  const ai = parseAi(fixture(), NOW);
  const shown = extraDisplay(extraSeries(ai, "CZ0201"));
  const names = shown.map((s) => s.variable);
  assert.ok(!names.includes("snowfall") && !names.includes("snow_depth") && !names.includes("snow_depth_water_equivalent"));
  const fog = shown.find((s) => s.variable === "fog_probability");
  assert.equal(fog.unit, "%");
  assert.equal(Math.max(...fog.series.filter((v) => v != null)), 60);
  const snowy = fixture();
  snowy.okresy.CZ0201.snowfall.ai[10] = 0.4;
  const names2 = extraDisplay(extraSeries(parseAi(snowy, NOW), "CZ0201")).map((s) => s.variable);
  assert.ok(names2.includes("snowfall"));
});

test("dayWindDirection: the speed-weighted mean of the day, null in calm or without data", () => {
  const ai = parseAi(fixture(), NOW);
  const shown = extraDisplay(extraSeries(ai, "CZ0201"));
  const own = ai.okresy.CZ0201;
  const d = dayWindDirection(shown, own, "2026-10-12");
  assert.ok(d > 190 && d < 240, `got ${d}`);
  assert.equal(dayWindDirection(shown, own, "2030-01-01"), null);
  assert.equal(dayWindDirection([], own, "2026-10-12"), null);
  // west and east cancel only in the vector mean; 350 and 10 average to north
  const fake = { times: [Date.parse("2026-10-12T10:00:00Z"), Date.parse("2026-10-12T11:00:00Z")], wind_speed_10m: [2, 2] };
  const n = dayWindDirection([{ variable: "wind_direction_10m", series: [350, 10] }], fake, "2026-10-12");
  assert.ok(n < 1 || n > 359);
});
