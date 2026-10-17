import assert from "node:assert/strict";
import { test } from "node:test";

import {
  KINDS_HASH, dayTabs, defaultDay, hasLabel, labelPriority, labelSize, landingHash, okresRows, pageMode,
  parseLanding, partDaylight, pickLabels, pragueOffset, stationHref, stationRows, stationSummary, sunTimes,
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
const FALLBACK = { day: "2026-10-16", part: "day", colour: "temperature", shown: ["temperature", "precipitation"], layer: "stations", okres: null };

test("which view a hash opens", () => {
  assert.equal(pageMode(""), "measured");
  assert.equal(pageMode("#"), "measured");
  assert.equal(pageMode("#2026-10-16/afternoon/temperature/tp"), "measured");
  assert.equal(pageMode("#2026-10-16"), "measured");
  assert.equal(pageMode(KINDS_HASH), "kinds");
  assert.equal(pageMode("#0-20000-0-11518"), "station");
  assert.equal(pageMode("#0-20000-0-11518/T"), "station");
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

test("the landing's view in the hash, with the layer", () => {
  const days = INDEX.days.map((d) => d.day);
  assert.deepEqual(parseLanding("", days, FALLBACK), { ...FALLBACK });
  assert.deepEqual(parseLanding("#2026-10-15/night/gust/tg", days, FALLBACK), {
    day: "2026-10-15", part: "night", colour: "gust", shown: ["temperature", "gust"], layer: "stations", okres: null,
  });
  // unknown day and part fall back; a station hash is not a landing
  assert.equal(parseLanding("#2026-01-01/noon", days, FALLBACK).day, "2026-10-16");
  assert.equal(parseLanding("#2026-01-01/noon", days, FALLBACK).part, "day");
  assert.equal(parseLanding("#0-20000-0-11518", days, FALLBACK).day, "2026-10-16");
  // the okres layer, with an okres open
  assert.deepEqual(parseLanding("#2026-10-15/afternoon/temperature/tp/okresy", days, FALLBACK).layer, "okresy");
  const open = parseLanding("#2026-10-15/afternoon/temperature/tp/CZ0100", days, FALLBACK);
  assert.equal(open.layer, "okresy");
  assert.equal(open.okres, "CZ0100");
  // round trip
  for (const view of [open, { ...FALLBACK, layer: "okresy" }, { ...FALLBACK, shown: [] }]) {
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
  assert.equal(view.layer, "okresy");
  assert.equal(view.day, "2026-10-15");
});

test("daylight of a part of the day, Prague clock", () => {
  assert.equal(pragueOffset("2026-01-15"), 1);
  assert.equal(pragueOffset("2026-07-15"), 2);
  // Praha on 16 October: sunrise about 7:20, sunset about 18:10 (within minutes is enough)
  const { rise, set } = sunTimes(50.1, 14.26, "2026-10-16");
  assert.ok(rise > 7.1 && rise < 7.6, `rise ${rise}`);
  assert.ok(set > 17.9 && set < 18.4, `set ${set}`);
  assert.equal(partDaylight(50.1, 14.26, "2026-10-16", "night"), 0);
  assert.equal(partDaylight(50.1, 14.26, "2026-10-16", "afternoon"), 6);
  assert.ok(partDaylight(50.1, 14.26, "2026-10-16", "morning") < 5);
  assert.ok(partDaylight(50.1, 14.26, "2026-10-16", "day") > 10.5);
  assert.equal(partDaylight(null, 14, "2026-10-16", "day"), null);
});

// a day's stations file (`mvd observed-map`) and the station index
const STATIONS = {
  day: "2026-10-16",
  parts: ["night", "morning", "afternoon", "evening", "day"],
  columns: ["tmax", "tmin", "r", "wind", "gust", "ssv", "cloud"],
  stations: {
    // a main station: everything
    M: [6, 4, 0, 1, 2, null, 90, 13, 5, 0, 2, 4, 2, 50, 16, 11, 0, 3, 5, 5.5, 20, 12, 9, 0, 1, 2, null, 60, 16, 4, 0, 3, 5, 7.5, 55],
    // a climate station, a wet afternoon
    C: [5, 3, 0, 1, 2, null, null, 9, 5, 0, 2, 3, 0.5, null, 10, 7, 3.2, 3, 9, null, null, 9, 6, 0.2, 1, 2, null, null, 10, 3, 3.4, 3, 9, 0.5, null],
    // a rain gauge
    R: [null, null, 0, null, null, null, null, null, null, 0, null, null, null, null, null, null, 1.1, null, null, null, null, null, null, 0, null, null, null, null, null, null, 1.1, null, null, null, null],
    // not in the index
    X: Array(35).fill(1),
  },
};
const STATION_INDEX = {
  stations: [
    { id: "M", name: "Main", lat: 50.1, lon: 14.3, network: "main" },
    { id: "C", name: "Climate", lat: 49.2, lon: 16.6, network: "climate" },
    { id: "R", name: "Gauge", lat: 49.8, lon: 15.5, network: "precipitation" },
  ],
};

test("the stations' rows of a part of the day, with their symbols", () => {
  const afternoon = stationRows(STATIONS, STATION_INDEX, "afternoon");
  assert.deepEqual(afternoon.map((r) => r.id), ["M", "C", "R"]);
  const [m, c, r] = afternoon;
  assert.equal(m.tmax, 16);
  assert.equal(m.sunshine, 5.5);
  assert.equal(m.kind, "main");
  assert.equal(m.symbol, "clear"); // 5.5 of 6 h of daylight: sunshine ≥ 60 %
  assert.equal(c.symbol, "rain"); // 3.2 mm
  assert.equal(c.precipitation, 3.2);
  assert.equal(r.symbol, "rain"); // a gauge has a symbol on a wet day only
  assert.equal(r.tmax, null);
  assert.equal(stationRows(STATIONS, STATION_INDEX, "night")[0].dark, true);
  // the night: the cloud cover (90 %) gives the sky
  assert.equal(stationRows(STATIONS, STATION_INDEX, "night")[0].symbol, "cloudy");
  // a dry gauge: no symbol
  assert.equal(stationRows(STATIONS, STATION_INDEX, "morning").find((x) => x.id === "R").symbol, null);
  assert.deepEqual(stationRows(null, STATION_INDEX, "day"), []);
  assert.deepEqual(stationRows(STATIONS, STATION_INDEX, "noon"), []);
  // a daily day has the whole day only
  const daily = { ...STATIONS, parts: ["day"], stations: { M: [16, 4, 0, null, 5, 7.5, null] } };
  assert.equal(stationRows(daily, STATION_INDEX, "day")[0].gust, 5);
  assert.deepEqual(stationRows(daily, STATION_INDEX, "afternoon"), []);
});

test("which stations get a label: main ones first, never overlapping", () => {
  const rows = stationRows(STATIONS, STATION_INDEX, "afternoon");
  assert.equal(labelPriority(rows[0]), 1);
  assert.equal(labelPriority(rows[2]), 6);
  assert.equal(labelPriority(rows[2], "R"), 0);
  // a gauge shows nothing when only temperature is chosen
  assert.equal(hasLabel(rows[2], ["temperature"], "afternoon"), true); // its rain symbol
  assert.equal(hasLabel({ ...rows[2], symbol: null }, ["temperature"], "afternoon"), false);
  const size = labelSize(rows[0], ["temperature", "precipitation"], "afternoon");
  assert.ok(size.w > 50 && size.h > 30, JSON.stringify(size));
  assert.ok(labelSize(rows[0], ["temperature", "precipitation", "wind", "gust", "sunshine"], "afternoon").h > size.h);
  // all at one place: only the main station is labelled
  const same = () => ({ x: 100, y: 100 });
  const options = { shown: ["temperature", "precipitation"], part: "afternoon", width: 400, height: 300 };
  assert.deepEqual([...pickLabels(rows, { ...options, project: same })], ["M"]);
  assert.deepEqual([...pickLabels(rows, { ...options, project: same, selected: "C" })], ["C"]);
  // far apart: all of them; off the map: none
  const spread = (r) => ({ M: { x: 50, y: 50 }, C: { x: 200, y: 150 }, R: { x: 350, y: 250 } })[r.id];
  assert.deepEqual([...pickLabels(rows, { ...options, project: spread })].sort(), ["C", "M", "R"]);
  assert.deepEqual([...pickLabels(rows, { ...options, project: () => ({ x: -500, y: 50 }) })], []);
});

test("the stations' headline", () => {
  const s = stationSummary(stationRows(STATIONS, STATION_INDEX, "afternoon"), "afternoon");
  assert.deepEqual(s.warmest, { id: "M", name: "Main", value: 16 });
  assert.deepEqual(s.coldest, { id: "C", name: "Climate", value: 7 });
  assert.deepEqual(s.wettest, { id: "C", name: "Climate", value: 3.2 });
  assert.equal(s.wet, 2);
  assert.equal(s.rainStations, 3);
  assert.deepEqual(s.gust, { id: "C", name: "Climate", value: 9 });
  assert.deepEqual(s.sunniest, { id: "M", name: "Main", value: 5.5 });
  assert.equal(s.stations, 3);
  // at night the warmest is the highest minimum
  assert.equal(stationSummary(stationRows(STATIONS, STATION_INDEX, "night"), "night").warmest.value, 4);
  const none = stationSummary([], "day");
  assert.equal(none.warmest, null);
  assert.equal(none.stations, 0);
});

test("the okres layer's rows", () => {
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

test("a station's link keeps the day", () => {
  assert.equal(stationHref("0-20000-0-11518", "2026-10-16"), "?day=2026-10-16#0-20000-0-11518");
  assert.equal(stationHref("0-20000-0-11518", null), "#0-20000-0-11518");
});
