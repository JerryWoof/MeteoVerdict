import assert from "node:assert/strict";
import { test } from "node:test";

import {
  KINDS_HASH, dayTabs, defaultDay, hasLabel, labelPriority, labelSize, landingHash, kindsStation, okresRows, pageMode,
  parseLanding, pickLabels, stationHref,
} from "./measured.js";
import { parseObservedDay, parseObservedIndex } from "./observed.js";
import { measuredRedirect } from "./tv.js";

const INDEX = parseObservedIndex({
  days: [
    { day: "2026-08-20", source: "daily" },
    { day: "2026-08-21", source: "daily" },
    { day: "2026-10-14", source: "hourly" },
    { day: "2026-10-15", source: "hourly" },
    { day: "2026-10-16", source: "hourly" },
  ],
});
const FALLBACK = { day: "2026-10-16", part: "day", colour: "temperature", shown: ["temperature", "precipitation"], okres: null };

test("which view a hash opens", () => {
  assert.equal(pageMode("#kinds/0-20000-0-11518"), "kinds");
  assert.equal(kindsStation("#kinds/0-20000-0-11518"), "0-20000-0-11518");
  assert.equal(kindsStation("#kinds"), null);
  assert.equal(pageMode(""), "measured");
  assert.equal(pageMode("#"), "measured");
  assert.equal(pageMode("#2026-10-16/afternoon/temperature/tp"), "measured");
  assert.equal(pageMode("#2026-10-16"), "measured");
  assert.equal(pageMode(KINDS_HASH), "kinds");
  assert.equal(pageMode("#0-20000-0-11518"), "station");
  assert.equal(pageMode("#0-20000-0-11518/T"), "station");
  // an old okres link opens the Weather tab on it; a malformed escape breaks nothing
  assert.equal(pageMode("#CZ0631"), "measured");
  assert.equal(parseLanding("#CZ0631", ["2026-10-15", "2026-10-16"], FALLBACK).okres, "CZ0631");
  assert.equal(parseLanding("#CZ0631", ["2026-10-15", "2026-10-16"], FALLBACK).day, "2026-10-16");
  assert.equal(kindsStation("#kinds/%E0%A4%A"), null);
  assert.equal(kindsStation("#kinds/a%20b"), "a b");
});

test("days: the newest measured day first, older ones only when chosen", () => {
  assert.equal(defaultDay(INDEX, "2026-10-17"), "2026-10-16");
  assert.equal(defaultDay(INDEX, "2026-10-16"), "2026-10-15"); // today is never measured
  assert.equal(defaultDay(parseObservedIndex(null), "2026-10-17"), null);
  assert.deepEqual(dayTabs(INDEX, "2026-10-17"), ["2026-10-16", "2026-10-15", "2026-10-14"]);
  assert.deepEqual(dayTabs(INDEX, "2026-10-17", null, 2), ["2026-10-16", "2026-10-15"]);
  // an older (daily) day from the date field gets a tab at the end
  assert.deepEqual(dayTabs(INDEX, "2026-10-17", "2026-08-20"), ["2026-10-16", "2026-10-15", "2026-10-14", "2026-08-20"]);
  // a day without a file does not
  assert.deepEqual(dayTabs(INDEX, "2026-10-17", "2026-09-01"), ["2026-10-16", "2026-10-15", "2026-10-14"]);
});

test("the Weather tab's view in the hash", () => {
  const days = INDEX.days.map((d) => d.day);
  assert.deepEqual(parseLanding("", days, FALLBACK), { ...FALLBACK });
  assert.deepEqual(parseLanding("#2026-10-15/night/gust/tg", days, FALLBACK), {
    day: "2026-10-15", part: "night", colour: "gust", shown: ["temperature", "gust"], okres: null,
  });
  // an old "/stations" or "/okresy" ending (the stations were once a layer) is ignored
  for (const end of ["stations", "okresy"]) {
    assert.deepEqual(parseLanding(`#2026-10-15/night/gust/tg/${end}`, days, FALLBACK), parseLanding("#2026-10-15/night/gust/tg", days, FALLBACK));
    assert.equal(parseLanding(`#2026-10-15/night/gust/${end}`, days, FALLBACK).okres, null);
  }
  // unknown day and part fall back; a station hash is not a landing
  assert.equal(parseLanding("#2026-01-01/noon", days, FALLBACK).day, "2026-10-16");
  assert.equal(parseLanding("#2026-01-01/noon", days, FALLBACK).part, "day");
  assert.equal(parseLanding("#0-20000-0-11518", days, FALLBACK).day, "2026-10-16");
  // an okres open
  const open = parseLanding("#2026-10-15/afternoon/temperature/tp/CZ0100", days, FALLBACK);
  assert.equal(open.okres, "CZ0100");
  // round trip
  for (const view of [open, FALLBACK, { ...FALLBACK, shown: [] }]) {
    assert.deepEqual(parseLanding(landingHash(view), days, FALLBACK), view);
  }
  assert.equal(landingHash(FALLBACK), "#2026-10-16/day/temperature/tp");
});

test("old forecast-map links to a past day go to the measured page", () => {
  assert.equal(measuredRedirect("#2026-10-15/afternoon/gust/tpg/CZ0100", "2026-10-17"), "#2026-10-15/afternoon/gust/tpg/CZ0100");
  assert.equal(measuredRedirect("#2026-10-15/afternoon/temperature/tp", "2026-10-17"), "#2026-10-15/afternoon/temperature/tp/okresy");
  // the older format "#day/part/layer/okres"
  assert.equal(measuredRedirect("#2026-10-15/morning/wind/CZ0642", "2026-10-17"), "#2026-10-15/morning/wind/tp/CZ0642");
  assert.equal(measuredRedirect("#2026-10-15", "2026-10-17"), "#2026-10-15/day/temperature/tp/okresy");
  // today, the coming days and no date stay on the forecast map
  assert.equal(measuredRedirect("#2026-10-17/evening", "2026-10-17"), null);
  assert.equal(measuredRedirect("#2026-10-19/evening", "2026-10-17"), null);
  assert.equal(measuredRedirect("", "2026-10-17"), null);
  assert.equal(measuredRedirect("#CZ0100", "2026-10-17"), null);
  // where it lands is a landing of the okres layer
  const view = parseLanding(measuredRedirect("#2026-10-15/afternoon/temperature/tp", "2026-10-17"), ["2026-10-15"], FALLBACK);
  assert.equal(view.okres, null);
  assert.equal(view.day, "2026-10-15");
});

// okres rows as okresRows makes them: one label each, the kraj capitals first
const ROWS = [
  { id: "CZ0100", name: "Praha", priority: 1, lon: 14.44, lat: 50.08, tmax: 16, tmin: 9, precipitation: 0, wind: 3, gust: 8, sunshine: 5, symbol: "clear" },
  { id: "CZ0423", name: "Litoměřice", priority: 2, lon: 14.13, lat: 50.53, tmax: 13, tmin: 5, precipitation: 2.6, symbol: "rain" },
  { id: "CZ0201", name: "Benešov", priority: 2, lon: 14.69, lat: 49.78, tmax: null, tmin: null, precipitation: null, symbol: null },
];

test("which okresy get a label: capitals first, never overlapping", () => {
  assert.equal(labelPriority(ROWS[0]), 1);
  assert.equal(labelPriority(ROWS[1]), 2);
  assert.equal(labelPriority(ROWS[1], "CZ0423"), 0);
  // an okres with nothing to show has no label, unless it is open
  assert.equal(hasLabel(ROWS[2], ["temperature"], "afternoon"), false);
  assert.equal(hasLabel({ ...ROWS[1], symbol: null }, ["temperature"], "afternoon"), true);
  const size = labelSize(ROWS[0], ["temperature", "precipitation"], "afternoon");
  assert.ok(size.w > 50 && size.h > 30, JSON.stringify(size));
  assert.ok(labelSize(ROWS[0], ["temperature", "precipitation", "wind", "gust", "sunshine"], "afternoon").h > size.h);
  // all at one place: only the capital is labelled
  const same = () => ({ x: 100, y: 100 });
  const options = { shown: ["temperature", "precipitation"], part: "afternoon", width: 400, height: 300 };
  assert.deepEqual([...pickLabels(ROWS, { ...options, project: same })], ["CZ0100"]);
  assert.deepEqual([...pickLabels(ROWS, { ...options, project: same, selected: "CZ0423" })], ["CZ0423"]);
  // far apart: all with something to show; off the map: none
  const spread = (r) => ({ CZ0100: { x: 50, y: 50 }, CZ0423: { x: 200, y: 150 }, CZ0201: { x: 350, y: 250 } })[r.id];
  assert.deepEqual([...pickLabels(ROWS, { ...options, project: spread })].sort(), ["CZ0100", "CZ0423"]);
  assert.deepEqual([...pickLabels(ROWS, { ...options, project: () => ({ x: -500, y: 50 }) })], []);
});

test("the okres rows", () => {
  const okresy = [
    { code: "CZ0100", name: "území Hlavního města Prahy", lat: 50.08, lon: 14.44 },
    { code: "CZ0423", name: "Litoměřice", lat: 50.53, lon: 14.13 },
    { code: "CZ0201", name: "Benešov", lat: 49.78, lon: 14.69 },
  ];
  const view = parseObservedDay({
    day: "2026-10-16",
    parts: ["day"],
    okresy: {
      CZ0100: { tmax: [16], tmin: [9], r: [0], n_t: [7], light: [10.7], st: ["A"] },
      CZ0423: { tmax: [13], tmin: [5], r: [2.6], n_t: [2], light: [10.7], st: ["B"] },
    },
  }, okresy);
  const rows = okresRows(view, "day");
  assert.deepEqual(rows.map((r) => [r.id, r.name, r.priority]), [["CZ0100", "Praha", 1], ["CZ0423", "Litoměřice", 2]]);
  assert.equal(rows[1].precipitation, 2.6);
  assert.equal(rows[0].okresCode, "CZ0100");
  assert.deepEqual(okresRows(null, "day"), []);
});

test("a station's link opens it in the Stations tab", () => {
  assert.equal(stationHref("0-20000-0-11518"), "#kinds/0-20000-0-11518");
  assert.equal(stationHref("0-20000-0-11518", (hash) => `${hash};m=blend`), "#kinds/0-20000-0-11518;m=blend");
});
