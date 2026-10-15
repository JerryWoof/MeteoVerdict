import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bracket, cellFeatures, compass, destination, hourTicks, lonLatToPixel, nowcastSentence,
  relativeTime, sample, satelliteProduct, sunElevation,
} from "./radar-extras.js";
import { ALOFT, dbzLevel } from "./radar-palette.js";
import { GRID, parseStamp } from "./radar.js";
import cells from "./fixtures/radar-cells.json" with { type: "json" };

test("a place → its grid cell (Web Mercator)", () => {
  assert.deepEqual(lonLatToPixel(GRID.west + 1e-9, GRID.north - 1e-9, GRID, 598, 378), { col: 0, row: 0 });
  assert.deepEqual(lonLatToPixel(GRID.east - 1e-9, GRID.south + 1e-9, GRID, 598, 378), { col: 597, row: 377 });
  // Prague: the middle latitude of the grid in Mercator is not the middle in degrees
  const prague = lonLatToPixel(14.42, 50.08, GRID, 598, 378);
  assert.equal(prague.col, 225);
  assert.equal(prague.row, 155); // 152.7 if the rows were even in degrees
  assert.equal(lonLatToPixel(10, 50, GRID, 598, 378), null);
});

const T = parseStamp("202610151200");
const min = (m) => T + m * 60000;
const series = (codes, forecastFrom = 0) => codes.map(([m, code]) => sample(min(m), code, m > forecastFrom));

test("nowcast sentence", () => {
  const moderate = dbzLevel(30);
  const light = dbzLevel(22);
  const heavy = dbzLevel(45);
  // dry now, moderate rain from +20
  assert.deepEqual(nowcastSentence(series([[-10, 0], [0, 0], [10, 0], [20, light], [30, moderate]]), T), { key: "expected", cat: "moderate", min: 20 });
  // nothing at all in the nowcast
  assert.deepEqual(nowcastSentence(series([[0, 0], [10, 0], [60, 0]]), T), { key: "dry" });
  assert.deepEqual(nowcastSentence(series([[0, 0]]), T), { key: "dryNoForecast" });
  // raining now, stopping at +30, heavier at +10
  const now = nowcastSentence(series([[0, moderate], [10, heavy], [20, light], [30, 0]]), T);
  assert.equal(now.key, "now");
  assert.equal(now.cat, "moderate");
  assert.equal(now.peak, "heavy");
  assert.equal(now.then, "stops");
  assert.equal(now.min, 30);
  assert.ok(now.rate > 2 && now.rate < 6);
  assert.equal(nowcastSentence(series([[0, light], [60, light]]), T).then, "continues");
  // only echo aloft (virga): not rain at the ground
  assert.deepEqual(nowcastSentence(series([[0, light | ALOFT], [10, 0]]), T), { key: "aloft", forecast: true });
  // minutes rounded to 5, at least 5
  assert.equal(nowcastSentence(series([[0, 0], [2, light]]), T).min, 5);
});

test("satellite: visible by day, night microphysics at night, water vapour on request", () => {
  const all = ["vis-ir", "night-M", "wv062"];
  // 15 Oct: sunrise in Prague about 07:15 CEST (05:15 UTC), sunset 18:20 CEST (16:20 UTC)
  assert.ok(sunElevation(Date.UTC(2026, 9, 15, 11, 0), 49.8, 15.5) > 25);
  assert.ok(sunElevation(Date.UTC(2026, 9, 15, 22, 0), 49.8, 15.5) < -20);
  assert.equal(satelliteProduct("clouds", Date.UTC(2026, 9, 15, 11, 0), all), "vis-ir");
  assert.equal(satelliteProduct("clouds", Date.UTC(2026, 9, 15, 20, 0), all), "night-M");
  assert.equal(satelliteProduct("clouds", Date.UTC(2026, 9, 15, 5, 0), all), "night-M"); // twilight
  assert.equal(satelliteProduct("clouds", Date.UTC(2026, 9, 15, 20, 0), ["vis-ir"]), "vis-ir");
  assert.equal(satelliteProduct("wv", Date.UTC(2026, 9, 15, 11, 0), all), "wv062");
  assert.equal(satelliteProduct("wv", 0, ["vis-ir"]), null);
  assert.equal(satelliteProduct("off", 0, all), null);
  assert.equal(satelliteProduct("clouds", 0, []), null);
  assert.equal(satelliteProduct("clouds", 0, undefined), null);
  // index.json's satellite object: a product without frames (vis-ir at night) does not count
  const sat = { "vis-ir": { frames: [] }, "night-M": { frames: ["202610152030"] } };
  assert.equal(satelliteProduct("clouds", Date.UTC(2026, 9, 15, 11, 0), sat), "night-M");
});

test("satellite frames around a time", () => {
  const stamps = ["202610151200", "202610151215", "202610151230"];
  assert.deepEqual(bracket(stamps, min(5)), { a: "202610151200", b: "202610151215", tau: 1 / 3 });
  assert.deepEqual(bracket(stamps, min(30)), { a: "202610151230", b: null, tau: 0 });
  assert.deepEqual(bracket(stamps, min(-10)), { a: "202610151200", b: null, tau: 0 });
  assert.equal(bracket(stamps, min(120)), null);
  assert.equal(bracket(undefined, min(0)), null);
});

test("storm cells: points, arrows and tracks", () => {
  const geo = cellFeatures(cells);
  const points = geo.features.filter((f) => f.properties.kind === "cell");
  assert.equal(points.length, cells.length);
  assert.ok(geo.features.some((f) => f.properties.kind === "arrow"));
  assert.ok(geo.features.some((f) => f.properties.kind === "track"));
  assert.equal(points.some((f) => f.properties.hail), cells.some((c) => c.hail));
  // moving east at 60 km/h: 10 minutes later 10 km further east
  const [moved] = cellFeatures([{ id: 1, lon: 15, lat: 50, speed_kmh: 60, dir_deg: 90 }], 10).features;
  const [lon, lat] = moved.geometry.coordinates;
  assert.ok(Math.abs(lat - 50) < 1e-9);
  assert.ok(Math.abs((lon - 15) * 111.32 * Math.cos((50 * Math.PI) / 180) - 10) < 1e-6);
  // slow cells have no arrow, broken ones are skipped
  assert.equal(cellFeatures([{ lon: 15, lat: 50, speed_kmh: 1 }, { lon: null, lat: 50 }]).features.length, 1);
  assert.deepEqual(cellFeatures(null).features, []);
  const north = destination(15, 50, 111.32, 0);
  assert.ok(Math.abs(north[1] - 51) < 1e-9);
  assert.equal(compass(0), "N");
  assert.equal(compass(100), "E");
  assert.equal(compass(225), "SW");
  assert.equal(compass(350), "N");
  assert.equal(compass(-90), "W");
});

test("relative times and hour ticks", () => {
  assert.deepEqual(relativeTime(min(-88), T), { key: "minAgo", n: 88 });
  assert.deepEqual(relativeTime(min(30), T), { key: "minIn", n: 30 });
  assert.deepEqual(relativeTime(min(0.3), T), { key: "now" });
  assert.deepEqual(relativeTime(min(-180), T), { key: "hAgo", n: 3 });
  assert.deepEqual(relativeTime(min(-3 * 1440), T), { key: "daysAgo", n: 3 });
  // 3 hours from 09:35 UTC (11:35 Prague): labels at every Prague full hour
  const ticks = hourTicks(parseStamp("202610150935"), parseStamp("202610151235"));
  assert.deepEqual(ticks.map((x) => x.hour), [12, 13, 14]);
  assert.equal(ticks[0].ms, parseStamp("202610151000"));
  // a whole day: every 6 hours at most 7 labels
  const day = hourTicks(parseStamp("202610142200"), parseStamp("202610152155"));
  assert.ok(day.length <= 7);
  assert.ok(day.every((x) => x.hour % 6 === 0 || x.hour % 3 === 0 || x.hour % 4 === 0));
  assert.deepEqual(hourTicks(5, 5), []);
});
