import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { FLAGS, HOURLY, NOTICE, SITE, aiOkresDoc, docPreview, hourlyPreview, indexDoc, obceDocs, obceIndexDoc, obecIds, okresDoc, slug } from "./api.js";
import { records } from "./data.js";

const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));
const OUTLOOK = load("outlook.json");
const HOURLY_DOC = load("outlook-hourly.json");
const META = load("meta.json");
const SCORES = {
  temperature_2m: records(load("scores-90d-okres-temperature_2m.json")),
  precipitation_24h: records(load("scores-90d-okres-precipitation_24h.json")),
};
const BENESOV = { code: "CZ0201", name: "Benešov", lat: 49.717, lon: 14.7767 };
const DOC = okresDoc({ okres: BENESOV, outlook: OUTLOOK, hourly: HOURLY_DOC, scores: SCORES, meta: META });

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
  const doc = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, scores: SCORES, meta: META });
  const night = doc.forecast.parts[0];
  assert.equal(night.night_min, -0.4);
  assert.equal(night.coldest_site, "Valley");
  assert.equal(night.frost, true);
  assert.equal(night.ground_frost, true);
});

test("the gust fields of an outlook row are passed through", () => {
  const columns = [...OUTLOOK.columns, "gust", "gust_over_threshold", "gust_warning"];
  const rows = OUTLOOK.rows.map((r) => [...r, 14.2, true, true]);
  const doc = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, scores: SCORES, meta: META });
  assert.equal(doc.forecast.parts[0].gust, 14.2);
  assert.equal(doc.forecast.parts[0].gust_over_threshold, true);
  assert.equal(doc.forecast.parts[0].gust_warning, true);
});

test("an outlook row with only the old gust_warning fills both fields", () => {
  const columns = [...OUTLOOK.columns, "gust", "gust_warning"];
  const rows = OUTLOOK.rows.map((r) => [...r, 14.2, true]);
  const doc = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, scores: SCORES, meta: META });
  assert.equal(doc.forecast.parts[0].gust_over_threshold, true);
  assert.equal(doc.forecast.parts[0].gust_warning, true);
});

test("the files say the flags are thresholds, not ČHMÚ warnings", () => {
  assert.match(DOC.notice, /not official ČHMÚ warnings/);
  assert.match(DOC.notice, /chmi\.cz/);
  assert.match(DOC.deprecated.gust_warning, /gust_over_threshold/);
});

test("the okres file has no ranking of the models", () => {
  assert.ok(!("models" in DOC), "the ranking of the models is not part of the okres file");
  assert.ok(!JSON.stringify(DOC).includes("mos_weight"));
});

test("every JSON file and the index carry the notice for every threshold flag", () => {
  for (const flag of FLAGS.filter((f) => f !== "gust_warning")) assert.match(NOTICE, new RegExp(flag));
  assert.equal(indexDoc([BENESOV], META, null).notice, NOTICE);
  assert.equal(DOC.notice, NOTICE);
});

test("index: every okres with the addresses of its files", () => {
  const index = indexDoc([BENESOV], META, "2026-10-12T10:49+00:00");
  assert.equal(index.okresy[0].json, `${SITE}/api/v1/okresy/CZ0201.json`);
  assert.ok(!("csv" in index.okresy[0]), "JSON only");
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

test("an AI okres file: the AI's own hourly rain, cloud, sunshine and range when its file has them", () => {
  const day = "2026-10-12"; // CEST: the morning is 04:00Z to 10:00Z
  const time = Array.from({ length: 24 }, (_, i) => `${day}T${String(i).padStart(2, "0")}:00Z`);
  const hourly = {
    time,
    generated: "x",
    variables: {},
    okresy: { CZ0201: {
      temperature_2m: time.map(() => 10), wind_speed_10m: time.map(() => 2),
      precipitation: time.map(() => 0.5), cloud_cover: time.map(() => 50), sunshine_duration: time.map(() => 0),
      temperature_2m_lo: time.map(() => 8), temperature_2m_hi: time.map(() => 12),
    } },
  };
  const aiOutlook = { columns: ["okres", "day", "part", "precipitation", "cloud", "sunshine"], rows: [["CZ0201", day, "morning", 3, 80, 2]] };
  const outlook = { generated: "x", time_zone: "Europe/Prague", columns: ["okres", "day", "part", "precipitation", "cloud", "sunshine"], rows: [["CZ0201", day, "morning", 4, 50, 3]] };
  // the AI's own hours cover 04:00Z-11:00Z only (the morning), already consistent with its part
  const own = (f) => time.map((_, i) => (i >= 4 && i <= 11 ? f(i) : null));
  const aiForecast = { issued: "x", hourly: { version: "hourly-1" }, okresy: { CZ0201: {
    time,
    temperature_2m: { ai: own(() => 11) }, wind_speed_10m: { ai: own(() => 3) },
    precipitation: { ai: own((i) => (i === 7 ? 3 : 0)) },
    cloud_cover: { ai: own(() => 80) },
    sunshine_duration: { ai: own((i) => (i >= 5 && i <= 10 ? 1200 : 0)) },
    temperature_2m_lo: { ai: own(() => 10) }, temperature_2m_hi: { ai: own(() => 13) },
  } } };
  const { forecast: f } = aiOkresDoc({ okres: BENESOV, outlook, hourly, aiForecast, aiOutlook, meta: META });
  assert.equal(f.hourly.precipitation[7], 3, "the AI's own hour, not refitted");
  assert.equal(f.hourly.precipitation[6], 0);
  assert.equal(f.hourly.cloud_cover[5], 80);
  assert.equal(f.hourly.sunshine_duration[6], 1200);
  assert.equal(f.hourly.temperature_2m_lo[6], 10, "the AI's own range");
  assert.equal(f.hourly.temperature_2m_hi[6], 13);
  assert.equal(f.hourly.temperature_2m_lo[20], 8, "no AI hour: the blend's");
  assert.equal(f.hourly.precipitation[20], 0.5, "a part the AI has no row for keeps the blend's hours");
  assert.equal(f.sources.temperature_2m_lo, "ai");
  assert.equal(f.sources.cloud_cover, "ai");
  assert.match(f.method, /own hourly values/);
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
  const frosty = okresDoc({ okres: BENESOV, outlook: { ...OUTLOOK, columns, rows }, hourly: HOURLY_DOC, scores: SCORES, meta: META });
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
  assert.ok(!Object.keys(files).some((k) => k.includes("csv")), "JSON only");
  assert.equal(files.obec_json, `${SITE}/api/v1/obce/{okres}/{id}.json`);
  assert.equal(files.ai_obec_json, `${SITE}/api/v1/ai/obce/{okres}/{id}.json`);
});

test("the Data page's preview: the first hours of an okres or obec file as JSON lines", () => {
  const doc = { hourly: { start: "2026-10-21T22:00Z", step_hours: 1, hours: 3, temperature_2m: [5, 4.5, null], precipitation: [0, 0.2, 0], wind_speed_10m: [1, 2, 3], cloud_cover: [50, 60, 70] } };
  assert.equal(hourlyPreview(doc, 2), [
    '"hourly": {',
    '  "time": ["2026-10-21T22:00Z","2026-10-21T23:00Z"],',
    '  "temperature_2m": [5,4.5],',
    '  "precipitation": [0,0.2],',
    '  "wind_speed_10m": [1,2],',
    '  "cloud_cover": [50,60],',
    "  …",
    "}",
  ].join("\n"));
  const okres = hourlyPreview(DOC, 3).split("\n");
  assert.equal(okres[1], `  "time": ${JSON.stringify(HOURLY_DOC.time.slice(0, 3))},`);
  assert.equal(hourlyPreview(null), "");
});

test("the further hourly variables of the combination come from forecast/models, the AI's from its file", async () => {
  const { extraFromModels, aiOkresDoc, EXTRA_UNITS } = await import("./api.js");
  const times = ["2026-10-23T00:00Z", "2026-10-23T01:00Z"];
  const models = {
    time: ["2026-10-23T00:00+00:00", "2026-10-23T01:00+00:00"],
    combined: { relative_humidity_2m: [71.4, 80.2], wind_gusts_10m: [4.26, null] },
    reference: { visibility: [20000, 12500], snow_depth: [0, 0.02], cape: [5, 6] },
  };
  const { series, sources } = extraFromModels(models, times);
  assert.deepEqual(series.relative_humidity_2m, [71, 80]);
  assert.deepEqual(series.wind_gusts_10m, [4.3, null]);
  assert.deepEqual(series.visibility, [20, 12.5]); // m → km
  assert.deepEqual(series.snow_depth, [0, 2]); // m → cm
  assert.equal(sources.relative_humidity_2m, "blend");
  assert.equal(sources.visibility, "reference");
  assert.equal(series.cape, undefined); // the combination has no CAPE
  assert.equal(EXTRA_UNITS.visibility, "km (up to 20)");
  const okres = { code: "CZ0100", name: "Praha", lat: 50, lon: 14 };
  const hourly = { generated: "x", time: times, variables: {}, okresy: { CZ0100: { temperature_2m: [1, 2], wind_speed_10m: [1, 1] } } };
  const aiForecast = {
    issued: "2026-10-23T06:30:00+00:00",
    extra: { sources: { dew_point_2m: "ai", cape: "reference" } },
    okresy: { CZ0100: { time: times, temperature_2m: { ai: [1, 2] }, dew_point_2m: { ai: [0.04, 1.26], reference: [9, 9] }, cape: { ai: [null, null], reference: [3, 4] } } },
  };
  const doc = aiOkresDoc({ okres, outlook: { rows: [], columns: [] }, hourly, aiForecast, aiOutlook: null, meta: null });
  assert.deepEqual(doc.forecast.hourly.dew_point_2m, [0, 1.3]);
  assert.deepEqual(doc.forecast.hourly.cape, [3, 4]);
  assert.equal(doc.forecast.sources.dew_point_2m, "ai");
  assert.equal(doc.forecast.sources.cape, "reference");
});

test("the Data page's example shows every property of the file with the long arrays cut", () => {
  const doc = { api: "v1", okres: { code: "CZ0100" }, hourly: { time: ["a", "b", "c", "d"], t: [1, null, 3, 4, 5] }, parts: [{ day: "x", tmin: null }, { day: "y", tmin: 1 }], empty: [], none: null };
  assert.equal(docPreview(doc, 2), [
    "{",
    '  "api": "v1",',
    '  "okres": {',
    '    "code": "CZ0100"',
    "  },",
    '  "hourly": {',
    '    "time": ["a","b",…],',
    '    "t": [1,null,…]',
    "  },",
    '  "parts": [',
    "    {",
    '      "day": "y",',
    '      "tmin": 1',
    "    },",
    "    …",
    "  ],",
    '  "empty": [],',
    '  "none": null',
    "}",
  ].join("\n"));
  assert.equal(docPreview(null), "");
});
