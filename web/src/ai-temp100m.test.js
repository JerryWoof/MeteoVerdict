import assert from "node:assert/strict";
import { test } from "node:test";

import { temp100mPixel, temp100mFormat, nearestPlaceOf } from "./ai-temp100m.js";

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

test("temperature text: decimal comma in cs", () => {
  assert.equal(temp100mFormat(2.94, "cs"), "2,9 °C");
  assert.equal(temp100mFormat(-3.06, "en"), "-3.1 °C");
});
