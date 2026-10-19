import assert from "node:assert/strict";
import { test } from "node:test";

import {
  heatBlend, heatColLon, heatColourLut, heatCompose, heatDayMarks, heatDecodeElev, heatDecodeGray, heatFieldValue, heatGrid, heatIdw,
  heatModel, heatNearestHour, heatNeighbours, heatPixelValue, heatRowLat, heatSeriesAt, heatTimeAt, heatTimeText, heatValueAt, parseHeatIndex,
} from "./ai-heat.js";

const DOC = {
  issued: "2026-10-18T19:11:00+00:00",
  bounds: [12, 49, 14, 51],
  width: 4,
  height: 3,
  lapse: 0.0065,
  cos_lat: 0.5,
  neighbours: 3,
  elev: { file: "elev.png" },
  fields: [0, 1, 2, 3].map((k) => ({ file: `f${k}.png`, offset: k, scale: 0.5, bytes: 10 })),
  okresy: { code: ["A", "B", "C"], lon: [12.5, 13, 13.5], lat: [49.5, 50, 50.5] },
  hours: [
    { time: "2026-10-20T00:00Z", w: 1, coef: [0.1, 0.2, 0.3] },
    { time: "2026-10-20T01:00Z", w: 0.5, coef: [0, 0, 0.1] },
  ],
  sea: [[10, 12, null], [8, 8, 9]],
  a: [[1, 2, 3], [2, 2, 2]],
  b: [[0.5, 0.5, 0.5], [1, 0, 1]],
};

// every pixel inside, elevation 100 m everywhere but the first pixel (outside); gray values 1..
const model = (doc = DOC) => {
  const index = parseHeatIndex(doc);
  const n = index.width * index.height;
  const elev = new Uint16Array(n).fill(100);
  elev[0] = 65535;
  const gray = [0, 1, 2, 3].map((k) => new Uint8Array(n).fill(k + 1));
  return heatModel(index, elev, gray, heatGrid(index, 1));
};

test("the index: corners, files next to it, null values as NaN, and nothing when unusable", () => {
  const i = parseHeatIndex(DOC);
  assert.deepEqual(i.coordinates, [[12, 51], [14, 51], [14, 49], [12, 49]]);
  assert.equal(i.files.elev.url, "data/scores/ai/fc/heat/elev.png");
  assert.equal(i.files.fields[2].url, "data/scores/ai/fc/heat/f2.png");
  assert.ok(Number.isNaN(i.sea[0][2]));
  assert.equal(i.hours[1].time, Date.parse("2026-10-20T01:00Z"));
  for (const bad of [null, {}, { ...DOC, bounds: [12, 49, 14] }, { ...DOC, fields: DOC.fields.slice(1) }, { ...DOC, elev: { file: "../e.png" } },
    { ...DOC, sea: [[1, 2, 3]] }, { ...DOC, hours: [] }, { ...DOC, okresy: { lon: [1], lat: [1, 2] } }]) {
    assert.equal(parseHeatIndex(bad), null);
  }
});

test("decoding: elevation is R·256 + G (alpha 0: outside), grays 0 are no data", () => {
  const rgba = Uint8Array.from([1, 4, 0, 255, 9, 9, 9, 0, 0, 200, 0, 255]);
  assert.deepEqual([...heatDecodeElev(rgba)], [260, 65535, 200]);
  assert.deepEqual([...heatDecodeGray(Uint8Array.from([7, 0, 0, 255, 7, 0, 0, 0]))], [7, 0]);
  assert.equal(heatFieldValue(0, -4, 0.5), null);
  assert.equal(heatFieldValue(1, -4, 0.5), -4);
  assert.equal(heatFieldValue(11, -4, 0.5), 1);
});

test("image rows are Web-Mercator spaced: the top row is just below north, the middle is the mercator midpoint", () => {
  const b = [12, 49, 14, 51];
  const top = heatRowLat(0, b, 1000);
  assert.ok(top < 51 && top > 50.99);
  const mid = heatRowLat(499.5, b, 1000);
  const m = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  assert.ok(Math.abs(m(mid) - (m(51) + m(49)) / 2) < 1e-12);
  // equal Mercator steps are shorter in latitude towards the north: the middle lies north of 50°
  assert.ok(mid > 50 && mid < 50.02);
  assert.equal(heatColLon(1, b, 4), 12.75);
});

test("idw: the nearest points weighted by 1/d², points without a value skipped", () => {
  const pts = { lon: Float64Array.from([0, 1, 5]), lat: Float64Array.from([0, 0, 0]) };
  const nb = heatNeighbours(pts, 1, 2, 0.5, 0);
  assert.deepEqual([...nb.idx].sort(), [0, 1]);
  assert.ok(Math.abs(nb.w[0] - 4) < 1e-9);
  assert.equal(heatIdw([10, 20, 99], nb.idx, nb.w), 15);
  assert.equal(heatIdw([10, NaN, 99], nb.idx, nb.w), 10);
  assert.ok(Number.isNaN(heatIdw([NaN, NaN, 1], nb.idx, nb.w)));
  // at a point the weight is capped (distance at least 1e-4)
  const on = heatNeighbours(pts, 1, 2, 1, 0);
  assert.equal(on.idx[0], 1);
  assert.ok(Math.abs(on.w[0] - 1e8) < 1);
  // lon is scaled by cos(lat)
  const far = heatNeighbours({ lon: Float64Array.from([0, 1]), lat: Float64Array.from([0.6, 0]) }, 0.5, 1, 0, 0);
  // 0.6° north is farther than 1° east scaled by 0.5
  assert.equal(far.idx[0], 1);
});

test("a pixel's value against a hand computation, none outside Czechia", () => {
  const m = model();
  const { index } = m;
  assert.equal(heatPixelValue(m, 0, 0, 0, heatNeighbours(index.points, index.cosLat, 3, 12.125, 50.9)), null);
  // pixel (2, 1): its three neighbours and weights
  const lon = heatColLon(2, index.bounds, 4);
  const lat = heatRowLat(1, index.bounds, 3);
  const nb = heatNeighbours(index.points, index.cosLat, 3, lon, lat);
  const idw = (v) => {
    let s = 0;
    let w = 0;
    for (let j = 0; j < 3; j++) {
      const x = v[nb.idx[j]];
      if (Number.isNaN(x)) continue;
      const d = Math.max(Math.hypot((index.points.lon[nb.idx[j]] - lon) * 0.5, index.points.lat[nb.idx[j]] - lat), 1e-4);
      s += x / (d * d);
      w += 1 / (d * d);
    }
    return s / w;
  };
  // field k has gray k+1, so its value is offset k + k·0.5 = 1.5·k
  const F = 0 + 0.1 * 1.5 + 0.2 * 3 + 0.3 * 4.5;
  const want = idw([10, 12, NaN]) - 0.0065 * 100 + 1 * (idw([1, 2, 3]) * F + idw([0.5, 0.5, 0.5]));
  assert.ok(Math.abs(heatPixelValue(m, 0, 2, 1, nb) - want) < 1e-9);
  const series = heatSeriesAt(m, lon, lat);
  assert.ok(Math.abs(series[0] - want) < 1e-9);
  assert.ok(Number.isFinite(series[1]));
  assert.ok(Number.isNaN(heatSeriesAt(m, 20, 50)[0]));
  // the single value agrees with the series, also between two hours
  assert.ok(Math.abs(heatValueAt(m, lon, lat, 0) - series[0]) < 1e-9);
  assert.ok(Math.abs(heatValueAt(m, lon, lat, 0.5) - (series[0] + series[1]) / 2) < 1e-9);
  assert.equal(heatValueAt(m, 20, 50, 0), null);
});

test("half hours are linear between the two hours, in values and in the picture", () => {
  const m = model();
  const series = Float64Array.from([2, 6, 4]);
  assert.equal(heatBlend(series, 0.5), 4);
  assert.equal(heatBlend(series, 1.5), 5);
  assert.equal(heatBlend(series, 2), 4);
  assert.equal(heatBlend(series, 9), 4);
  // the picture at a half hour has the temperatures between the hours' (checked through a ramp that is the temperature itself)
  const ramp = Uint8ClampedArray.from({ length: 901 * 3 }, (_, i) => (i % 3 === 0 ? Math.min(255, Math.round(i / 3 / 4)) : 0));
  const at = (pos) => heatCompose(m, pos, ramp).data[(1 * 4 + 2) * 4];
  const lon = heatColLon(2, m.index.bounds, 4);
  const lat = heatRowLat(1, m.index.bounds, 3);
  const [t0, t1] = heatSeriesAt(m, lon, lat);
  const red = (t) => Math.min(255, Math.round(Math.round((t + 40) / 0.1) / 4));
  assert.equal(at(0), red(t0));
  assert.equal(at(1), red(t1));
  assert.ok(Math.abs(at(0.5) - red((t0 + t1) / 2)) <= 1);
  assert.equal(heatColourLut(() => "#102030").length, 901 * 3);
});

test("the picture: pixels outside are transparent, the others coloured by the lookup, a shrunk picture samples every nth pixel", () => {
  const m = model();
  const lut = heatColourLut((v) => (v < 0 ? "#0000ff" : "#ff0000"));
  const full = heatCompose(m, 0, lut);
  assert.equal(full.width, 4);
  assert.equal(full.height, 3);
  assert.equal(full.data[3], 0);
  assert.equal(full.data[7], 255);
  const t = heatSeriesAt(m, heatColLon(1, m.index.bounds, 4), heatRowLat(0, m.index.bounds, 3))[0];
  assert.equal(full.data[4], t < 0 ? 0 : 255);
  const half = heatCompose(m, 0, lut, 2);
  assert.equal(half.width, 2);
  assert.equal(half.height, 2);
  assert.equal(half.data[3], 0);
  assert.equal(half.data[7], 255);
});

test("the coarse grid gives nearly the exact values", () => {
  const exact = model();
  const coarse = heatModel(exact.index, exact.elev, exact.gray, heatGrid(exact.index, 2));
  const lut = heatColourLut((v) => `#${Math.round(Math.min(255, Math.max(0, (v + 40) * 2))).toString(16).padStart(2, "0")}0000`);
  const a = heatCompose(exact, 0.5, lut).data;
  const b = heatCompose(coarse, 0.5, lut).data;
  for (let i = 0; i < a.length; i += 4) assert.ok(Math.abs(a[i] - b[i]) <= 40);
});

test("the time: nearest hour, label in Prague, midnights", () => {
  const { hours } = parseHeatIndex(DOC);
  const now = Date.parse("2026-10-20T00:40Z");
  assert.equal(heatNearestHour(hours, now), 1);
  assert.equal(heatNearestHour(hours, Date.parse("2026-01-01T00:00Z")), 0);
  assert.equal(heatTimeAt(hours, 0.5), Date.parse("2026-10-20T00:30Z"));
  assert.equal(heatTimeAt(hours, 5), hours[1].time);
  assert.equal(heatTimeText(Date.parse("2026-10-20T12:30Z"), "en"), "Tue 20/10 14:30");
  assert.equal(heatTimeText(Date.parse("2026-10-20T12:30Z"), "cs"), "út 20. 10. 14:30");
  const day = Array.from({ length: 30 }, (_, i) => ({ time: Date.parse("2026-10-20T00:00Z") + i * 3600e3 }));
  // Prague midnight is 22:00Z the day before (CEST)
  assert.deepEqual(heatDayMarks(day, "en"), [{ pos: 22, label: "Wed" }]);
});
