import assert from "node:assert/strict";
import test from "node:test";
import { parseSources, aiMapView, aiPeriods, parseAi, parseSky, skyRow, withAi, AI_MODEL } from "./ai-model.js";

const NOW = Date.parse("2026-10-20T12:00:00Z");
const hours = (n) => Array.from({ length: n }, (_, i) => new Date(Date.parse("2026-10-20T00:00:00Z") + i * 3600e3).toISOString());
const doc = (extra = {}) => ({
  issued: "2026-10-20T06:00:00Z",
  okresy: {
    A: { time: hours(48), temperature_2m: { ai: hours(48).map((_, i) => i) }, wind_speed_10m: { ai: hours(48).map(() => 2) } },
    B: { time: hours(48) },
    C: { time: hours(48), temperature_2m: { ai: [1, 2] } },
  },
  ...extra,
});

test("parseAi keeps only okresy with a temperature series", () => {
  const ai = parseAi(doc(), NOW);
  assert.deepEqual(Object.keys(ai.okresy), ["A"]);
});

test("parseAi: missing, malformed and stale files give null", () => {
  assert.equal(parseAi(null, NOW), null);
  assert.equal(parseAi({ okresy: {} }, NOW), null);
  assert.equal(parseAi(doc({ issued: "2026-10-18T06:00:00Z" }), NOW), null);
  assert.equal(parseAi(doc({ issued: "2026-10-25T06:00:00Z" }), NOW), null);
});

test("withAi aligns the series to the model times, null outside", () => {
  const ai = parseAi(doc(), NOW);
  const times = hours(72).map(Date.parse);
  const parsed = withAi({ times, models: { x: {} }, combined: {} }, ai, "A");
  const t = parsed.models[AI_MODEL].temperature_2m;
  assert.equal(t[5], 5);
  assert.equal(t[60], null);
  assert.equal(withAi({ times, models: {} }, ai, "B").models[AI_MODEL], undefined);
});

test("aiMapView: rows for covered periods, beyond for the rest and for okresy without AI", () => {
  const ai = parseAi(doc(), NOW);
  const outlook = {
    okresy: [{ code: "A" }, { code: "B" }],
    days: ["2026-10-20", "2026-10-22"],
    rows: new Map(),
  };
  const view = aiMapView(ai, outlook);
  assert.equal(view.single, true);
  assert.equal(view.rows.get("A|2026-10-20|day").beyond, undefined);
  assert.equal(view.rows.get("A|2026-10-22|day").beyond, true);
  assert.equal(view.rows.get("B|2026-10-20|day").beyond, true);
  assert.equal(view.rows.get("A|2026-10-20|day").precipitation, null);
});

test("aiMapView: an okres without AI data shows the blend's row, not a gap", () => {
  const ai = parseAi(doc(), NOW);
  const rows = new Map([["B|2026-10-20|day", { tmin: 1, tmax: 9, precipitation: 3 }]]);
  const view = aiMapView(ai, { okresy: [{ code: "B" }], days: ["2026-10-20"], rows });
  const row = view.rows.get("B|2026-10-20|day");
  assert.equal(row.tmax, 9);
  assert.equal(row.single, true);
  assert.equal(row.beyond, undefined);
});

test("withAi fills rain, cloud and sunshine from the blend on the AI's hours", () => {
  const ai = parseAi(doc(), NOW);
  const times = hours(72).map(Date.parse);
  const blend = times.map(() => 0.5);
  const parsed = withAi({ times, models: {}, combined: { precipitation: blend, cloud_cover: blend } }, ai, "A");
  assert.equal(parsed.models[AI_MODEL].precipitation[5], 0.5);
  assert.equal(parsed.models[AI_MODEL].precipitation[60], null);
  assert.equal(parsed.models[AI_MODEL].sunshine_duration, undefined);
});

test("aiMapView takes rain, cloud, sunshine and symbol from the blend's outlook row", () => {
  const ai = parseAi(doc(), NOW);
  const rows = new Map([["A|2026-10-20|day", { precipitation: 2, cloud: 80, sunshine: 1, symbol: "rain", tmax: 99 }]]);
  const view = aiMapView(ai, { okresy: [{ code: "A" }], days: ["2026-10-20"], rows });
  const row = view.rows.get("A|2026-10-20|day");
  assert.equal(row.precipitation, 2);
  assert.equal(row.cloud, 80);
  assert.equal(row.symbol, "rain");
  assert.notEqual(row.tmax, 99);
});

const skyDoc = () => ({
  issued: "2026-10-20T06:00:00Z",
  okresy: { A: { rows: [{ day: "2026-10-20", part: "day", cloud: 20, sunshine: 6.5, gust: 9.1 }, { day: "2026-10-20", part: "night", cloud: null, sunshine: 0, gust: 3 }] } },
});

test("parseSky: rows by okres and part; stale or malformed gives null", () => {
  const sky = parseSky(skyDoc(), NOW);
  assert.deepEqual(sky.get("A").get("2026-10-20|day"), { cloud: 20, sunshine: 6.5, gust: 9.1 });
  assert.equal(parseSky(skyDoc(), NOW + 80 * 3600e3), null);
  assert.equal(parseSky({ okresy: {} }, NOW), null);
});

test("skyRow: the AI's cloud, sunshine and gust win where present, the symbol follows the cloud", () => {
  const ai = { sky: parseSky(skyDoc(), NOW) };
  const row = { tmin: 5, tmax: 12, precipitation: 0, cloud: 90, sunshine: 1, gust: null, symbol: "cloudy" };
  const next = skyRow(row, ai, "A", "2026-10-20|day");
  assert.deepEqual([next.cloud, next.sunshine, next.gust, next.symbol], [20, 6.5, 9.1, "clear"]);
  assert.equal(next.gust_over_threshold, false);
  // night: no cloud from the AI, the blend's stays
  assert.equal(skyRow(row, ai, "A", "2026-10-20|night").cloud, 90);
  // an okres or part the AI has not: untouched
  assert.equal(skyRow(row, ai, "B", "2026-10-20|day"), row);
  assert.equal(aiPeriods(new Map([["2026-10-20|day", row]]), ai, "A").get("2026-10-20|day").cloud, 20);
});

test("parseSources groups the columns into layers and ignores a missing flag", () => {
  const flags = parseSources({ sources: { tmin: "ai", tmax: "ai", wind: "ai", cloud: "ai", sunshine: "ai", gust: "ai", gust_over_threshold: "ai", precipitation: "blend", rain_probability: "blend", symbol: "ai" } });
  assert.deepEqual(flags, { ai: ["temperature", "wind", "cloud", "sunshine", "gust"], blend: ["precipitation"] });
  assert.equal(parseSources({}), null);
  assert.equal(parseSources(null), null);
});
