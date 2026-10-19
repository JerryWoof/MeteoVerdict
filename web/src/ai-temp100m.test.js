import assert from "node:assert/strict";
import { test } from "node:test";

import { parseTemp100m, parseTemp100mIndex, temp100mColourise, temp100mGrayAt, temp100mGrayLut, temp100mGrayValue, temp100mMapFor, temp100mLookup, temp100mPixel, temp100mValue, temp100mGradient, temp100mSlot, temp100mSlotText, temp100mDefaultIndex, temp100mFormat, nearestPlaceOf } from "./ai-temp100m.js";

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

test("a time's slot in Prague and its label: weekday, date, part, clock", () => {
  assert.deepEqual(temp100mSlot(Date.parse("2026-10-20T02:00Z")), { day: "2026-10-20", part: "night", clock: "04:00" });
  assert.equal(temp100mSlot(Date.parse("2026-10-20T09:00Z")).part, "morning");
  assert.equal(temp100mSlot(Date.parse("2026-10-20T22:00Z")).day, "2026-10-21");
  assert.equal(temp100mSlotText(Date.parse("2026-10-20T02:00Z"), "cs", "noc"), "út 20. 10. noc 04:00");
  assert.equal(temp100mSlotText(Date.parse("2026-10-20T02:00Z"), "en", "night"), "Tue 20/10 night 04:00");
});

test("default time: the nearest future one, else the last", () => {
  const maps = [1000, 2000, 3000].map((time) => ({ time }));
  assert.equal(temp100mDefaultIndex(maps, 1500), 1);
  assert.equal(temp100mDefaultIndex(maps, 2000), 1);
  assert.equal(temp100mDefaultIndex(maps, 500), 0);
  assert.equal(temp100mDefaultIndex(maps, 9000), 2);
  assert.equal(temp100mDefaultIndex([], 1), -1);
});

test("nearest place with its distance", () => {
  const places = [{ name: "A", lat: 50, lon: 14 }, { name: "B", lat: 49, lon: 16 }];
  const r = nearestPlaceOf(places, 49.01, 16.01);
  assert.equal(r.place.name, "B");
  assert.ok(r.km > 1 && r.km < 2);
  assert.equal(nearestPlaceOf([], 49, 16), null);
});

test("pixel from lng/lat: corners, centre in Mercator spacing, outside", () => {
  const b = [12, 48.5, 19, 51.1];
  assert.deepEqual(temp100mPixel(12, 51.1, b, 700, 500), { x: 0, y: 0 });
  assert.deepEqual(temp100mPixel(19, 48.5, b, 700, 500), { x: 699, y: 499 });
  assert.deepEqual(temp100mPixel(12, 48.5, b, 700, 500), { x: 0, y: 499 });
  assert.deepEqual(temp100mPixel(19, 51.1, b, 700, 500), { x: 699, y: 0 });
  const m = (l) => Math.log(Math.tan(Math.PI / 4 + (l * Math.PI) / 360));
  const midLat = (2 * Math.atan(Math.exp((m(51.1) + m(48.5)) / 2)) - Math.PI / 2) * 180 / Math.PI;
  assert.deepEqual(temp100mPixel(15.5, midLat, b, 700, 500), { x: 350, y: 250 });
  assert.equal(temp100mPixel(11.9, 50, b, 700, 500), null);
  assert.equal(temp100mPixel(15, 52, b, 700, 500), null);
});

test("colour to value round-trips every 0.25 step; transparent is null", () => {
  const doc = { min: 3, max: 9, stops: [
    { value: 3, color: "#313695" }, { value: 3.6, color: "#4575b4" }, { value: 4.2, color: "#74add1" },
    { value: 6, color: "#ffffbf" }, { value: 9, color: "#a50026" }] };
  const lookup = temp100mLookup(doc);
  assert.equal(lookup.length, 25);
  for (const { value, rgb } of lookup) assert.equal(temp100mValue(lookup, ...rgb), value);
  assert.equal(temp100mValue(lookup, 49, 54, 149, 0), null);
  assert.equal(temp100mValue(lookup, 49, 54, 149), 3);
});

test("temperature text: decimal comma in cs", () => {
  assert.equal(temp100mFormat(2.94, "cs"), "2,9 °C");
  assert.equal(temp100mFormat(-3.06, "en"), "-3.1 °C");
});

test("gray to °C with the map's own offset and step; 0 is no data", () => {
  assert.equal(temp100mGrayValue(0, -30, 0.25), null);
  assert.equal(temp100mGrayValue(1, -30, 0.25), -30);
  assert.equal(temp100mGrayValue(129, -30, 0.25), 2);
  assert.equal(temp100mGrayValue(11, -30, 0.5), -25);
});

test("the series index: per-map offset/step fallback, lookup by day and part, nothing without maps", () => {
  const doc = {
    bounds: [12, 48.5, 19, 51.1], offset: -30, step: 0.25, unit: "°C",
    maps: [
      { day: "2026-10-20", part: "night", time: "2026-10-20T02:00Z", file: "a.png" },
      { day: "2026-10-20", part: "morning", time: "2026-10-20T07:00Z", file: "b.png", offset: -20, step: 0.5, bytes: 10 },
      { day: "x", part: "night", time: "bad", file: "c.png" },
    ],
  };
  const index = parseTemp100mIndex(doc, "data/ai/temp100m/index.json");
  assert.equal(index.maps.length, 2);
  assert.deepEqual(temp100mMapFor(index, "2026-10-20", "night"), { day: "2026-10-20", part: "night", time: Date.parse("2026-10-20T02:00Z"), url: "data/ai/temp100m/a.png", offset: -30, step: 0.25 });
  assert.equal(temp100mMapFor(index, "2026-10-20", "morning").step, 0.5);
  assert.equal(temp100mMapFor(index, "2026-10-23", "night"), null);
  assert.equal(parseTemp100mIndex({ ...doc, maps: [] }), null);
  assert.equal(parseTemp100mIndex(null), null);
  // the fallback: no index, the old coloured file still parses
  assert.ok(parseTemp100m(DOC));
});

test("colourising gray pixels with a ramp; gray image lookup at a point", () => {
  const lut = temp100mGrayLut({ offset: -30, step: 0.25 }, (v) => (v > 0 ? "#ff0000" : "#0000ff"));
  const rgba = new Uint8ClampedArray([0, 0, 0, 255, 121, 121, 121, 255, 200, 200, 200, 0, 161, 161, 161, 255]);
  const { out, gray } = temp100mColourise(rgba, lut);
  assert.deepEqual([...gray], [0, 121, 0, 161]);
  assert.deepEqual([...out.slice(0, 4)], [0, 0, 0, 0]);
  assert.deepEqual([...out.slice(4, 8)], [0, 0, 255, 255]);
  assert.deepEqual([...out.slice(12, 16)], [255, 0, 0, 255]);
  const img = { gray, width: 2, height: 2 };
  const b = [12, 48.5, 19, 51.1];
  assert.equal(temp100mGrayAt(img, 12.1, 51.0, b, { offset: -30, step: 0.25 }), null);
  assert.equal(temp100mGrayAt(img, 18.9, 48.6, b, { offset: -30, step: 0.25 }), 10);
});
