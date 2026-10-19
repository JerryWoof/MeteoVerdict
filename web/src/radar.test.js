import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DBZ_SCALE, GRID, MM_SCALE, boundsOf, clock, closestStep, dayFolder, frameUrl, imageCoordinates,
  latestAtOrBefore, legendNumber, localDay, minutesBetween, parseStamp, parseView, rainRate,
  sourceUrl, timeline, toStamp, viewHash,
} from "./radar.js";

test("stamps are UTC and round-trip", () => {
  const ms = parseStamp("202610151035");
  assert.equal(new Date(ms).toISOString(), "2026-10-15T10:35:00.000Z");
  assert.equal(toStamp(ms), "202610151035");
  assert.equal(parseStamp("2026-10-15"), null);
  assert.equal(parseStamp(undefined), null);
});

test("image corners and bounds from the index", () => {
  assert.deepEqual(imageCoordinates()[0], [GRID.west, GRID.north]);
  assert.deepEqual(imageCoordinates()[2], [GRID.east, GRID.south]);
  assert.deepEqual(boundsOf({ bounds: [[1, 2], [3, 4]] }), { west: 1, south: 2, east: 3, north: 4 });
  assert.deepEqual(boundsOf({}), GRID);
  // Czechia (about 12.09-18.86 E, 48.55-51.06 N) lies inside the grid
  assert.ok(GRID.west < 12.09 && GRID.east > 18.86 && GRID.south < 48.55 && GRID.north > 51.06);
});

test("frame and folder URLs", () => {
  assert.equal(dayFolder("2026-10-14"), "20261014");
  assert.equal(frameUrl("radar/live/", "maxz", "202610151035"), "radar/live/maxz/202610151035.png");
  assert.equal(sourceUrl("live", "https://raw.example/radar-live/"), "https://raw.example/radar-live/");
  assert.equal(sourceUrl("2026-10-14", "x"), "radar/days/20261014/");
});

test("rain frame valid at a time", () => {
  const stamps = ["202610151000", "202610151010", "202610151020"];
  assert.equal(latestAtOrBefore(stamps, parseStamp("202610151015")), "202610151010");
  assert.equal(latestAtOrBefore(stamps, parseStamp("202610150955")), null);
  assert.equal(latestAtOrBefore(stamps, parseStamp("202610151200")), null); // too old
  assert.equal(latestAtOrBefore(stamps, parseStamp("202610151200"), 120), "202610151020");
});

const INDEX = {
  maxz: ["202610150930", "202610151025", "202610151030", "202610151035"],
  merge1h: ["202610151010", "202610151020", "202610151030"],
  nowcast: {
    base: "202610151035",
    frames: [
      { time: "202610151035", lead: 0 },
      { time: "202610151045", lead: 10 },
      { time: "202610151055", lead: 20 },
    ],
  },
};

test("timeline: observed frames, then the nowcast after them", () => {
  const steps = timeline(INDEX);
  assert.deepEqual(steps.map((s) => s.radar), [...INDEX.maxz, "202610151045", "202610151055"]);
  assert.deepEqual(steps.map((s) => s.forecast), [false, false, false, false, true, true]);
  assert.equal(steps[4].lead, 10);
  assert.deepEqual(steps.map((s) => s.rain), [null, "202610151020", "202610151030", "202610151030", "202610151030", "202610151030"]);
  // the last hour only
  assert.deepEqual(timeline(INDEX, { hours: 1 }).map((s) => s.radar).slice(0, 2), ["202610151025", "202610151030"]);
  assert.deepEqual(timeline({}), []);
});

test("closest step: now by default, else the nearest time", () => {
  const steps = timeline(INDEX);
  assert.equal(closestStep(steps, null), 3);
  assert.equal(closestStep(steps, parseStamp("202610151027")), 1);
  assert.equal(closestStep(steps, parseStamp("202610152000")), 5);
  assert.equal(closestStep([], null), -1);
  assert.equal(closestStep([{ time: 1, forecast: true }], null), 0);
});

test("clock and day in Prague time", () => {
  assert.equal(clock(parseStamp("202610151035")), "12:35"); // CEST
  assert.equal(clock(parseStamp("202612151035")), "11:35"); // CET
  assert.equal(localDay(parseStamp("202610142230")), "2026-10-15");
  assert.equal(minutesBetween(parseStamp("202610151035"), parseStamp("202610151049")), 14);
  assert.equal(minutesBetween(parseStamp("202610151035"), parseStamp("202610151034")), 0);
});

test("colour scales and legend numbers", () => {
  assert.equal(DBZ_SCALE.length, 15);
  assert.equal(MM_SCALE.length, 15);
  assert.ok(DBZ_SCALE.every(([v], i) => i === 0 || v > DBZ_SCALE[i - 1][0]));
  assert.ok(MM_SCALE.every(([v], i) => i === 0 || v > MM_SCALE[i - 1][0]));
  // ČHMÚ's scale: 20 dBZ ≈ 1 mm/h, 40 dBZ ≈ 10 mm/h (rounded on the scale)
  assert.ok(Math.abs(rainRate(20) - 0.65) < 0.01);
  assert.ok(Math.abs(rainRate(40) - 11.5) < 0.1);
  assert.equal(legendNumber(0.1), "0.1");
  assert.equal(legendNumber(0.6), "0.6");
  assert.equal(legendNumber(15), "15");
});

test("view state in the URL", () => {
  assert.deepEqual(parseView(""), { day: "live", hours: 24, layers: ["radar"], time: null, filter: null });
  const view = { day: "2026-10-14", hours: 24, layers: ["radar", "rain"], time: "202610141200", filter: null };
  assert.equal(viewHash(view), "#2026-10-14/24/radar+rain/202610141200");
  assert.deepEqual(parseView(viewHash(view)), view);
  assert.deepEqual(parseView("#live/5/rain+x"), { day: "live", hours: 24, layers: ["rain"], time: null, filter: null });
  assert.deepEqual(parseView("#live/6/").layers, []);
  // new layers and the "show from" setting; old links keep working
  const shown = { day: "live", hours: 3, layers: ["radar", "sat", "cells"], time: null, filter: "moderate" };
  assert.equal(viewHash(shown), "#live/3/radar+sat+cells/now/moderate");
  assert.deepEqual(parseView(viewHash(shown)), shown);
  assert.equal(viewHash({ ...shown, filter: "all" }), "#live/3/radar+sat+cells");
  assert.deepEqual(parseView("#live/3/radar/now/bogus").filter, null);
  // one satellite product at a time
  assert.deepEqual(parseView("#live/3/sat+wv+echotop").layers, ["sat", "echotop"]);
});

test("timeline: an old nowcast is left out, the animation ends at now", () => {
  // the newest image is 10:35; a nowcast from 10:15 (20 min) is still shown, one from 10:10 not
  const at = (base) => ({ ...INDEX, nowcast: { base, frames: [{ time: "202610151045", lead: 10 }] } });
  assert.equal(timeline(at("202610151015")).at(-1).radar, "202610151045");
  assert.equal(timeline(at("202610151010")).at(-1).radar, "202610151035");
  assert.ok(timeline(at("202610151010")).every((s) => !s.forecast));
  // no nowcast at all
  assert.equal(timeline({ maxz: INDEX.maxz }).at(-1).radar, "202610151035");
});
