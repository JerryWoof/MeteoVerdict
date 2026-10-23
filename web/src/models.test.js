import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { COMBINED, VARIABLES, modelOptions, weightTable } from "./forecast.js";
import {
  asForecast, localPeriod, modelHorizon, modelPeriods, modelSymbol, parseModels,
} from "./models.js";

// real: forecast/models/CZ0201.json from the saved Open-Meteo answer of 12 Oct 2026
const DOC = JSON.parse(readFileSync(new URL("./fixtures/models-CZ0201.json", import.meta.url)));
const WEIGHTS = JSON.parse(readFileSync(new URL("./fixtures/ranking-CZ0201.json", import.meta.url)));
const PARSED = parseModels(DOC);
const HOUR = 3600 * 1000;

test("the per-model file: every series as long as the hours, models ending early padded", () => {
  assert.equal(PARSED.times.length, 144);
  assert.equal(PARSED.times[0], Date.parse("2026-10-12T00:00Z"));
  assert.equal(PARSED.generated, "2026-10-12T08:25+00:00");
  for (const series of Object.values(PARSED.models)) {
    for (const values of Object.values(series)) assert.equal(values.length, 144);
  }
  assert.equal(PARSED.combined.temperature_2m.length, 144);
  // ICON-D2 runs 48 h: its file series is shorter, padded here
  assert.ok(DOC.models.dwd_icon_d2.temperature_2m.length < 144);
  assert.equal(PARSED.models.dwd_icon_d2.temperature_2m.at(-1), null);
  assert.equal(parseModels(null), null);
  assert.equal(parseModels({ time: [] }), null);
});

test("as the forecast pages want it: variable → model → values", () => {
  const forecast = asForecast(PARSED, VARIABLES);
  assert.deepEqual(Object.keys(forecast.values), VARIABLES);
  assert.deepEqual(Object.keys(forecast.values.temperature_2m).sort(), Object.keys(DOC.models).sort());
  assert.equal(forecast.values.precipitation.ecmwf_ifs025[13], DOC.models.ecmwf_ifs025.precipitation[13]);
});

test("Prague parts of day, in summer and winter time", () => {
  assert.deepEqual(localPeriod(Date.parse("2026-10-12T04:00Z")), { day: "2026-10-12", part: "morning" });
  assert.deepEqual(localPeriod(Date.parse("2026-10-12T22:00Z")), { day: "2026-10-13", part: "night" });
  assert.deepEqual(localPeriod(Date.parse("2026-12-12T05:00Z")), { day: "2026-12-12", part: "morning" });
  assert.deepEqual(localPeriod(Date.parse("2026-12-12T04:59Z")), { day: "2026-12-12", part: "night" });
});

// a synthetic model on 3 days of hours from 2026-12-12 00 UTC (01:00 in Prague)
function synthetic(hours, values) {
  const start = Date.parse("2026-12-12T00:00Z");
  const times = Array.from({ length: hours }, (_, i) => start + i * HOUR);
  return parseModels({
    generated: "2026-12-12T05:00+00:00",
    time: times.map((t) => new Date(t).toISOString().replace(":00.000Z", "Z")),
    models: { m: values(times) },
  });
}

test("a model's parts and days: tmin/tmax, rain total of the hour before, highest wind", () => {
  const parsed = synthetic(72, (times) => ({
    temperature_2m: times.map((_, i) => i),
    precipitation: times.map(() => 0.1),
    wind_speed_10m: times.map((_, i) => (i === 8 ? 9 : 2)),
    cloud_cover: times.map((t) => (localPeriod(t).part === "night" ? 100 : 10)),
    sunshine_duration: times.map(() => 1800),
  }));
  const rows = modelPeriods(parsed, "m");
  // morning of 12 Dec: 06-12 Prague = 05-11 UTC, hours 5..10
  const morning = rows.get("2026-12-12|morning");
  assert.equal(morning.tmin, 5);
  assert.equal(morning.tmax, 10);
  assert.equal(morning.wind, 9);
  assert.equal(morning.rain_probability, null);
  // rain: the hours ending 06:00..11:00 UTC (6 × 0.1); sunshine likewise: 3 h
  assert.ok(Math.abs(morning.precipitation - 0.6) < 1e-9);
  assert.equal(morning.sunshine, 3);
  assert.equal(morning.cloud, 10);
  assert.equal(morning.symbol, "rain"); // 0.6 mm at 5-10 °C
  // the first night has only 01-06 Prague (5 hours): enough for a part (>= 4)
  assert.equal(rows.get("2026-12-12|night").tmin, 0);
  // a whole day: 23 hours on the first day (>= 18); its cloud from 6-18 only
  assert.equal(rows.get("2026-12-12|day").cloud, 10);
  assert.equal(rows.get("2026-12-12|day").tmax, 22);
  // the last day has 1 hour: no day, no evening
  assert.equal(rows.get("2026-12-15|day"), undefined);
});

test("horizon: no part or day the model does not cover whole (shown as –)", () => {
  // 72 hours in the file, the model's temperature and rain only the first 40
  const parsed = synthetic(72, (times) => ({
    temperature_2m: times.map((_, i) => (i < 40 ? 5 : null)).slice(0, 40),
    precipitation: times.map((_, i) => (i < 40 ? 0 : null)).slice(0, 40),
    cloud_cover: times.map(() => 50).slice(0, 40),
  }));
  const rows = modelPeriods(parsed, "m");
  // hour 39 = 13 Dec 15:00 UTC = 16:00 Prague: the afternoon of 13 Dec is cut
  assert.equal(modelHorizon(parsed, "m"), parsed.times[39]);
  assert.ok(rows.get("2026-12-13|morning"));
  assert.equal(rows.get("2026-12-13|afternoon"), undefined);
  assert.equal(rows.get("2026-12-13|evening"), undefined);
  assert.equal(rows.get("2026-12-13|day"), undefined);
  assert.equal(rows.get("2026-12-14|day"), undefined);
  assert.ok(rows.get("2026-12-12|day"));
  assert.equal(rows.get("2026-12-12|day").symbol, "partly");
  assert.equal(modelPeriods(parsed, "nothing").size, 0);
});

test("a model ending one hour short of a day: its parts shown, the whole day –", () => {
  // the model's last hour 13 Dec 22:00 UTC = 23:00 Prague: every hour of that evening,
  // but no rain for 23-24
  const parsed = synthetic(72, (times) => ({
    temperature_2m: times.map(() => 5).slice(0, 47),
    precipitation: times.map(() => 0.1).slice(0, 47),
    cloud_cover: times.map(() => 50).slice(0, 47),
  }));
  const rows = modelPeriods(parsed, "m");
  assert.equal(modelHorizon(parsed, "m"), Date.parse("2026-12-13T22:00Z"));
  for (const part of ["night", "morning", "afternoon"]) assert.ok(rows.get(`2026-12-13|${part}`), part);
  const evening = rows.get("2026-12-13|evening");
  assert.ok(evening);
  // the rain of the five hours it has
  assert.ok(Math.abs(evening.precipitation - 0.5) < 1e-9);
  assert.equal(rows.get("2026-12-13|day"), undefined);
  // two hours short: the evening is not covered (its 23:00 is missing)
  const shorter = modelPeriods(synthetic(72, (times) => ({
    temperature_2m: times.map(() => 5).slice(0, 46),
    precipitation: times.map(() => 0.1).slice(0, 46),
  })), "m");
  assert.equal(shorter.get("2026-12-13|evening"), undefined);
  assert.ok(shorter.get("2026-12-13|afternoon"));
  // a gap inside a part (not at the model's end) still leaves it out
  const gap = modelPeriods(synthetic(72, (times) => ({
    temperature_2m: times.map(() => 5),
    precipitation: times.map((_, i) => (i === 43 ? null : 0.1)),
  })), "m");
  assert.equal(gap.get("2026-12-13|evening"), undefined);
  assert.ok(gap.get("2026-12-14|night"));
});

test("a real short model (ICON-D2, 48 h) ends with its horizon, a global one runs on", () => {
  const short = modelPeriods(PARSED, "dwd_icon_d2");
  const long = modelPeriods(PARSED, "ecmwf_ifs025");
  assert.ok(short.get("2026-10-13|day"));
  assert.equal(short.get("2026-10-14|day"), undefined);
  assert.ok(long.get("2026-10-16|day"));
  // raw: the day's highs are the model's own hourly maximum
  const own = DOC.models.ecmwf_ifs025.temperature_2m;
  const day = PARSED.times
    .map((t, i) => [localPeriod(t).day, own[i]])
    .filter(([d]) => d === "2026-10-13")
    .map(([, v]) => v);
  assert.equal(long.get("2026-10-13|day").tmax, Math.max(...day));
});

test("one model's symbol: rain by its own total, sky by its cloud, never showers", () => {
  assert.equal(modelSymbol(90, 0.3, 10), "rain");
  assert.equal(modelSymbol(90, 0.29, 10), "cloudy");
  assert.equal(modelSymbol(20, 1, 1.5), "sleet");
  assert.equal(modelSymbol(20, 1, 0.5), "snow");
  assert.equal(modelSymbol(29, 0, 10), "clear");
  assert.equal(modelSymbol(64, null, 10), "partly");
  assert.equal(modelSymbol(null, 0, 10), null);
});

test("the picker of a real okres: combination, then models by mean rank, all with a file", () => {
  const available = new Set(Object.keys(PARSED.models));
  const options = modelOptions(weightTable(WEIGHTS), {}, available);
  assert.equal(options[0].model, COMBINED);
  assert.deepEqual(options.slice(1).map((o) => o.model).sort(), [...available].sort());
  const scored = options.filter((o) => o.scored);
  for (let i = 1; i < scored.length; i += 1) assert.ok(scored[i - 1].rank <= scored[i].rank);
  assert.deepEqual(scored.map((o) => o.position), scored.map((_, i) => i + 1));
});
