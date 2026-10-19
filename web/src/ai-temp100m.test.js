import assert from "node:assert/strict";
import { test } from "node:test";

import { parseTemp100m, temp100mGradient, temp100mTimeText, temp100mWhen } from "./ai-temp100m.js";

const DOC = {
  bounds: [12.0, 48.5, 19.0, 51.1],
  time: "2026-10-20T00:00Z",
  png: "temp100m.png",
  legend: { min: -4, max: 12, unit: "°C", step: 0.5 },
  colormap: [{ value: 12, color: "#a50026" }, { value: -4, color: "#313695" }, { value: 4, color: "#ffffbf" }],
};

test("the 100 m file: image corners, legend, and nothing without a usable file", () => {
  const p = parseTemp100m(DOC);
  assert.equal(p.url, "data/scores/ai/fc/temp100m.png");
  assert.deepEqual(p.coordinates, [[12, 51.1], [19, 51.1], [19, 48.5], [12, 48.5]]);
  assert.equal(p.time, Date.parse("2026-10-20T00:00Z"));
  assert.deepEqual(p.stops.map((s) => s.value), [-4, 4, 12]);
  assert.equal(temp100mGradient(p), "linear-gradient(to right, #313695 0%, #ffffbf 50%, #a50026 100%)");
  for (const bad of [null, {}, { ...DOC, bounds: [12, 48.5, 19] }, { ...DOC, time: "x" }, { ...DOC, png: "../x.png" },
    { ...DOC, colormap: [{ value: 0, color: "#000000" }] }]) {
    assert.equal(parseTemp100m(bad), null);
  }
});

test("the 100 m time in Prague: tonight, today, tomorrow, another day", () => {
  const now = Date.parse("2026-10-19T08:00Z"); // 10:00 in Prague
  assert.deepEqual(temp100mWhen(Date.parse("2026-10-20T00:00Z"), now), { key: "tonight", day: "2026-10-20", clock: "02:00" });
  assert.equal(temp100mWhen(Date.parse("2026-10-19T19:00Z"), now).key, "tonight");
  // after midnight, the same night
  assert.equal(temp100mWhen(Date.parse("2026-10-20T00:00Z"), Date.parse("2026-10-19T22:30Z")).key, "tonight");
  assert.equal(temp100mWhen(Date.parse("2026-10-19T12:00Z"), now).key, "today");
  assert.equal(temp100mWhen(Date.parse("2026-10-20T12:00Z"), now).key, "tomorrow");
  assert.equal(temp100mWhen(Date.parse("2026-10-21T00:00Z"), now).key, null);
  const t = (key, params) => `${key} ${params.time}`;
  assert.equal(temp100mTimeText(Date.parse("2026-10-20T12:00Z"), now, "en", t), "ai.temp100m.tomorrow 14:00");
  assert.equal(temp100mTimeText(Date.parse("2026-10-21T12:00Z"), now, "en", t), "Wed, 10/21 14:00");
});
