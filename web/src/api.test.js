import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { FLAGS, HOURLY, NOTICE, SITE, aiOkresDoc, indexDoc, obceDocs, obecCsvLines, obceIndexDoc, obecIds, okresCsv, okresDoc, okresModels, slug } from "./api.js";
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
  assert.equal(lines[0], "time_utc,temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration,temperature_2m_lo,temperature_2m_hi");
  assert.equal(lines.length, 145);
  const first = lines[1].split(",");
  assert.equal(first[0], HOURLY_DOC.time[0]);
  assert.equal(Number(first[1]), HOURLY_DOC.okresy.CZ0201.temperature_2m[0]);
  const empty = okresDoc({ okres: { code: "X", name: "X" }, outlook: OUTLOOK, hourly: null, weightsDoc: null, scores: {}, meta: META });
  assert.equal(okresCsv(empty), "time_utc,temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration\n");
});

test("the CSV has no threshold flags, so it stays plain (no notice line)", () => {
  const header = okresCsv(DOC).split("\n")[0].split(",");
  assert.deepEqual(header, ["time_utc", ...HOURLY]);
  for (const flag of FLAGS) assert.ok(!header.includes(flag), `${flag} in the CSV needs the notice`);
  // the JSON files and the index carry it, for every flag
  for (const flag of FLAGS.filter((f) => f !== "gust_warning")) assert.match(NOTICE, new RegExp(flag));
  assert.equal(indexDoc([BENESOV], META, null).notice, NOTICE);
});

test("index: every okres with the addresses of its files", () => {
  const index = indexDoc([BENESOV], META, "2026-10-12T10:49+00:00");
  assert.equal(index.okresy[0].json, `${SITE}/api/v1/okresy/CZ0201.json`);
  assert.equal(index.okresy[0].csv, `${SITE}/api/v1/okresy/CZ0201.csv`);
  assert.equal(index.files.okres_json, `${SITE}/api/v1/okresy/{code}.json`);
  assert.equal(index.generated, "2026-10-12T10:49+00:00");
});

// ---- AI okres files ----
const AI_TIMES = HOURLY_DOC.time.slice(10, 60);
const AI_FORECAST = {
  issued: "2026-10-20T15:25:00+00:00",
  okresy: {
    CZ0201: {
      time: AI_TIMES,
      temperature_2m: { ai: AI_TIMES.map((_, i) => (i === 3 ? null : 20 + i)), combined: [] },
      wind_speed_10m: { ai: AI_TIMES.map((_, i) => 7 + i / 10) },
    },
  },
};
const AI_OUTLOOK = {
  sources: { tmin: "ai", tmax: "ai", wind: "ai", precipitation: "ai", symbol: "ai", sunrise: "astronomy" },
  columns: ["okres", "day", "part", "tmin", "tmax", "wind", "precipitation", "symbol", "sunrise", "ai"],
  rows: [["CZ0201", OUTLOOK.rows[0][OUTLOOK.columns.indexOf("day")], "night", -1.5, 3.5, null, 99, "rain", "01:23", ["frost"]]],
};
const AI_DOC = aiOkresDoc({ okres: BENESOV, outlook: OUTLOOK, hourly: HOURLY_DOC, aiForecast: AI_FORECAST, aiOutlook: AI_OUTLOOK, meta: META });

test("an AI okres file: AI temperature and wind on the blend's axis, the rest combined", () => {
  assert.equal(AI_DOC.forecast.model, "ai");
  assert.equal(AI_DOC.forecast.ai_issued, "2026-10-20T15:25:00+00:00");
  assert.ok(!("models" in AI_DOC) && !("deprecated" in AI_DOC));
  assert.match(AI_DOC.licence, /CC BY-SA 4\.0/);
  const h = AI_DOC.forecast.hourly;
  assert.deepEqual(h.time, HOURLY_DOC.time);
  assert.equal(h.temperature_2m[10], 20);
  assert.equal(h.temperature_2m[12], 22);
  // the AI has no value for hour 13: the blend's stays, with its range
  assert.equal(h.temperature_2m[13], HOURLY_DOC.okresy.CZ0201.temperature_2m[13]);
  const B = HOURLY_DOC.okresy.CZ0201;
  assert.equal(h.temperature_2m_lo[10], Number((20 - (B.temperature_2m[10] - B.temperature_2m_lo[10])).toFixed(1)), "the blend's width around the AI temperature");
  assert.equal(h.temperature_2m_hi[10], Number((20 + (B.temperature_2m_hi[10] - B.temperature_2m[10])).toFixed(1)));
  assert.equal(h.temperature_2m_lo[13], HOURLY_DOC.okresy.CZ0201.temperature_2m_lo[13]);
  assert.equal(h.temperature_2m_lo[0], HOURLY_DOC.okresy.CZ0201.temperature_2m_lo[0]);
  assert.equal(h.wind_speed_10m[10], 7);
  assert.equal(AI_DOC.forecast.sources.temperature_2m, "ai");
  assert.equal(AI_DOC.forecast.sources.precipitation, "ai", "the part field; the hourly series is the blend's");
  assert.equal(AI_DOC.forecast.sources.cloud_cover, "ai");
  assert.equal(AI_DOC.forecast.sources.temperature_2m_lo, "blend");
  assert.equal(AI_DOC.forecast.sources.tmin, "ai");
  assert.equal(AI_DOC.forecast.sources.symbol, "ai");
  assert.equal(AI_DOC.forecast.sources.frost, "ai");
  assert.equal(AI_DOC.forecast.sources.sunrise, "astronomy");
  assert.equal(AI_DOC.forecast.sources.cloud, "blend");
  // the blend's own file is not changed
  assert.deepEqual(DOC.forecast.hourly.temperature_2m, HOURLY_DOC.okresy.CZ0201.temperature_2m);
});

test("an AI okres file: parts take every field the AI outlook has a value for", () => {
  const [night, morning] = AI_DOC.forecast.parts;
  assert.equal(night.tmin, -1.5);
  assert.equal(night.tmax, 3.5);
  assert.equal(night.wind, DOC.forecast.parts[0].wind, "null in the AI outlook: the blend's value");
  assert.equal(night.precipitation, 99);
  assert.equal(night.symbol, "rain");
  assert.equal(night.sunrise, DOC.forecast.parts[0].sunrise, "astronomy stays the combined file's");
  assert.equal(night.cloud, DOC.forecast.parts[0].cloud, "a field the AI row lacks keeps the blend's");
  assert.deepEqual(morning, (({ gust_warning, ...rest }) => rest)(DOC.forecast.parts[1]));
  assert.ok(!("gust_warning" in night));
  assert.equal(aiOkresDoc({ okres: { code: "CZ9999" }, outlook: OUTLOOK, hourly: HOURLY_DOC, aiForecast: AI_FORECAST, aiOutlook: AI_OUTLOOK, meta: META }), null);
});

test("an AI okres file: hourly precipitation, cloud and sunshine fitted to the AI's value of each part of day", () => {
  const day = "2026-10-12"; // CEST: the morning is 04:00Z to 10:00Z
  const time = Array.from({ length: 24 }, (_, i) => `${day}T${String(i).padStart(2, "0")}:00Z`);
  const hourly = {
    time,
    generated: "x",
    variables: {},
    okresy: { CZ0201: {
      temperature_2m: time.map(() => 10), wind_speed_10m: time.map(() => 2),
      precipitation: time.map((_, i) => (i >= 5 && i <= 10 ? [0, 1, 1, 2, 0, 0][i - 5] : 0)),
      cloud_cover: time.map(() => 50), sunshine_duration: time.map((_, i) => (i >= 5 && i <= 10 ? 1800 : 0)),
      temperature_2m_lo: time.map(() => 8), temperature_2m_hi: time.map(() => 12),
    } },
  };
  const aiOutlook = { columns: ["okres", "day", "part", "tmin", "tmax", "wind", "precipitation", "cloud", "sunshine"], rows: [["CZ0201", day, "morning", 8, 12, 2, 8, 80, 3]] };
  const outlook = { generated: "x", time_zone: "Europe/Prague", columns: ["okres", "day", "part", "tmin", "tmax", "precipitation", "wind", "cloud", "sunshine"], rows: [["CZ0201", day, "morning", 8, 12, 4, 2, 50, 3]] };
  const aiForecast = { issued: "x", okresy: { CZ0201: { time, temperature_2m: { ai: time.map(() => 11) }, wind_speed_10m: { ai: time.map(() => 3) } } } };
  const { forecast: f } = aiOkresDoc({ okres: BENESOV, outlook, hourly, aiForecast, aiOutlook, meta: META });
  const sum = (a, from, to) => a.slice(from, to).reduce((x, y) => x + y, 0);
  // hours ending at 05:00Z..10:00Z are the hours inside the local morning (06:00-12:00)
  assert.equal(Number(sum(f.hourly.precipitation, 5, 11).toFixed(2)), 8, "adds up to the AI's mm");
  assert.equal(f.hourly.precipitation[8], 4, "keeps the shape (2 of 4 mm → 4 of 8)");
  assert.equal(sum(f.hourly.sunshine_duration, 5, 11), 3 * 3600, "adds up to the AI's hours");
  assert.equal(f.hourly.cloud_cover[4], 80, "mean shifted to the AI's 80 %");
  assert.equal(f.hourly.precipitation[20], 0, "a part the AI has no row for keeps the blend's hours");
});

// ---- obce ----
test("slug: ASCII, lowercase, dashes; duplicates numbered by population", () => {
  assert.equal(slug("Bílá Třemešná"), "bila-tremesna");
  assert.equal(slug("  Nové Město n. M. "), "nove-mesto-n-m");
  assert.equal(slug("???"), "obec");
  const ids = obecIds([{ name: "Lhota", population: 10 }, { name: "Lhota", population: 500 }, { name: "Lhota", population: 20 }, { name: "Lhota 2", population: 1 }]);
  assert.deepEqual(ids, ["lhota-3", "lhota", "lhota-2", "lhota-2-2"]);
});

/** An obec file made of the okres's own series (+offset), only every `step` hours. */
function obceOf(offset, step, extra = {}) {
  const idx = HOURLY_DOC.time.map((t, i) => i).filter((i) => i % step === 0);
  const s = HOURLY_DOC.okresy.CZ0201;
  const times = idx.map((i) => HOURLY_DOC.time[i].replace("Z", "+00:00"));
  const pick = (a, f = (x) => x) => idx.map((i) => (a[i] == null ? null : f(a[i])));
  return {
    generated: "2026-10-20T20:12+00:00",
    times,
    places: [{ name: "Ves", lat: 49.5, lon: 14.5, elevation: 400, population: 100,
      temperature_2m: pick(s.temperature_2m, (x) => x + offset), precipitation: pick(s.precipitation), wind_speed_10m: pick(s.wind_speed_10m, (x) => x + offset / 2), ...extra }],
  };
}

test("an obec identical to its okres reproduces the okres's hours and parts", () => {
  const [{ id, doc }] = obceDocs({ okresDoc: DOC, obceFile: obceOf(0, 1), meta: META });
  assert.equal(id, "ves");
  assert.equal(doc.test, undefined);
  assert.equal(doc.obec.okres, "CZ0201");
  assert.match(doc.attribution, /ČHMÚ/);
  assert.match(doc.attribution, /ČÚZK/);
  assert.equal(doc.hourly.time, undefined);
  assert.equal(doc.hourly.start, HOURLY_DOC.time[0]);
  assert.equal(doc.hourly.step_hours, 1);
  assert.equal(doc.hourly.hours, HOURLY_DOC.time.length);
  assert.equal(doc.hourly.temperature_2m.length, HOURLY_DOC.time.length);
  // the okres axis really is hourly and contiguous
  HOURLY_DOC.time.forEach((t, i) => assert.equal(Date.parse(t), Date.parse(HOURLY_DOC.time[0]) + i * 3600e3));
  assert.deepEqual(doc.hourly.temperature_2m, DOC.forecast.hourly.temperature_2m.map((x) => (x == null ? null : Number(x.toFixed(1)))));
  assert.equal(doc.parts.length, DOC.forecast.parts.length);
  DOC.forecast.parts.forEach((p, i) => {
    const o = doc.parts[i];
    assert.equal(`${o.day}|${o.part}`, `${p.day}|${p.part}`);
    // the fixtures' parts and hours are from different runs (live data matches to 0.05)
    for (const k of ["tmin", "tmax", "wind"]) assert.ok(Math.abs((o[k] ?? 0) - (p[k] ?? 0)) < 0.6, `${p.day} ${p.part} ${k}`);
    assert.ok(Math.abs((o.precipitation ?? 0) - (p.precipitation ?? 0)) < 1);
  });
});

test("obec hours: own value, straight line across a gap of 3 h or less, else okres plus offset; no nulls where the okres has a value", () => {
  const [{ doc }] = obceDocs({ okresDoc: DOC, obceFile: obceOf(2, 3), meta: META });
  const okres = DOC.forecast.hourly;
  assert.equal(doc.hourly.hours, okres.time.length);
  okres.time.forEach((_, i) => {
    assert.equal(doc.hourly.temperature_2m[i] == null, okres.temperature_2m[i] == null, `hour ${i}`);
    assert.equal(doc.hourly.wind_speed_10m[i] == null, okres.wind_speed_10m[i] == null);
  });
  const i = okres.time.findIndex((t, k) => k % 3 === 0 && okres.temperature_2m[k] != null && okres.temperature_2m[k + 3] != null);
  const a = okres.temperature_2m[i] + 2, b = okres.temperature_2m[i + 3] + 2;
  assert.equal(doc.hourly.temperature_2m[i + 1], Number((a + (b - a) / 3).toFixed(1)));
  // precipitation: the okres's hourly value where the obec has none
  assert.deepEqual(doc.hourly.precipitation.slice(0, 5), okres.precipitation.slice(0, 5).map((x) => (x == null ? null : Number(x.toFixed(2)))));
  // two samples 6 h apart: offset instead of interpolation (+2 at every sample)
  const sparse = obceOf(2, 6);
  const [{ doc: far }] = obceDocs({ okresDoc: DOC, obceFile: sparse, meta: META });
  const j = okres.time.findIndex((t, k) => k % 6 === 1 && okres.temperature_2m[k] != null);
  assert.equal(far.hourly.temperature_2m[j], Number((okres.temperature_2m[j] + 2).toFixed(1)));
});

test("obec files carry the okres's own values for what the obec has none of (cloud, sunshine, symbol, rain, gusts)", () => {
  const [{ doc }] = obceDocs({ okresDoc: DOC, obceFile: obceOf(0, 1), meta: META });
  assert.deepEqual(doc.hourly.cloud_cover, DOC.forecast.hourly.cloud_cover);
  assert.deepEqual(doc.hourly.sunshine_duration, DOC.forecast.hourly.sunshine_duration);
  const row = DOC.forecast.parts[0];
  for (const k of ["rain_probability", "cloud", "sunshine", "symbol", "sunrise", "sunset", "heavy_rain_probability", "gust"]) assert.equal(doc.parts[0][k] ?? null, row[k] ?? null, k);
  assert.ok(doc.sources.okres.includes("cloud") && doc.sources.obec);
});

test("obec frost fields follow the okres's night minimum plus the obec's difference", () => {
  const columns = [...OUTLOOK.columns, "night_min", "ground_min"];
  const rows = OUTLOOK.rows.map((r) => [...r, 0.4, -1.2]);
  const frosty = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, weightsDoc: WEIGHTS, scores: SCORES, meta: META });
  const [{ doc }] = obceDocs({ okresDoc: frosty, obceFile: obceOf(-1, 1), meta: META });
  const p = doc.parts[0];
  assert.equal(p.night_min, -0.6);
  assert.equal(p.ground_min, -2.2);
  assert.equal(p.frost, true);
  assert.equal(p.ground_frost, true);
  assert.ok(!("night_min" in obceDocs({ okresDoc: DOC, obceFile: obceOf(0, 1), meta: META })[0].doc.parts[0]));
});

test("obce index and the file patterns in index.json", () => {
  const idx = obceIndexDoc([["CZ0201", "ves", "Ves", 49.5, 14.5]], "2026-10-20T20:12+00:00");
  assert.equal(idx.url, `${SITE}/api/v1/obce/{okres}/{id}.json`);
  assert.deepEqual(idx.obce[0], ["CZ0201", "ves", "Ves", 49.5, 14.5]);
  const files = indexDoc([BENESOV], META, null).files;
  assert.equal(files.ai_okres_json, `${SITE}/api/v1/ai/okresy/{code}.json`);
  assert.equal(files.ai_okres_csv, `${SITE}/api/v1/ai/okresy/{code}.csv`);
  assert.equal(files.obec_json, `${SITE}/api/v1/obce/{okres}/{id}.json`);
  assert.equal(files.ai_obec_json, `${SITE}/api/v1/ai/obce/{okres}/{id}.json`);
});

test("obec CSV preview: the okres CSV's columns the obec file has, on its start + i hours axis", () => {
  const doc = { hourly: { start: "2026-10-21T22:00Z", step_hours: 1, hours: 3, temperature_2m: [5, 4.5, null], precipitation: [0, 0.2, 0], wind_speed_10m: [1, 2, 3], cloud_cover: [50, 60, 70] } };
  assert.deepEqual(obecCsvLines(doc, 2), [
    "time_utc,temperature_2m,precipitation,wind_speed_10m,cloud_cover",
    "2026-10-21T22:00Z,5,0,1,50",
    "2026-10-21T23:00Z,4.5,0.2,2,60",
  ]);
  assert.deepEqual(obecCsvLines(null), []);
});
