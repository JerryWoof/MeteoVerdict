import assert from "node:assert/strict";
import test from "node:test";
import { aiMapView, parseAi, withAi, AI_MODEL } from "./ai-model.js";

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
