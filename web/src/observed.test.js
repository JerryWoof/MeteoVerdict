import assert from "node:assert/strict";
import { test } from "node:test";

import {
  OBSERVED_LAYERS, dayKind, defaultLead, difference, isDark, nearestDay, observedSummary, observedSymbol,
  parseForecasts, parseObservedDay, parseObservedIndex, pastTabs, stationLink, stationValues, stepDay,
} from "./observed.js";
import { BEYOND, dayLabel, labelFor, okresColours, parseView, rowFor, valueFor, viewHash } from "./tv.js";

const OKRESY = [
  { code: "CZ0423", name: "Litoměřice", lat: 50.53, lon: 14.13 },
  { code: "CZ0642", name: "Brno-město", lat: 49.2, lon: 16.6 },
  { code: "CZ0100", name: "území Hlavního města Prahy", lat: 50.08, lon: 14.44 },
];

const INDEX = parseObservedIndex({
  generated: "2026-10-17T05:00+00:00",
  part_days: 30,
  days: [
    { day: "2026-10-16", source: "hourly", leads: [1] },
    { day: "2026-09-01", source: "daily", leads: [] },
    { day: "2026-10-15", source: "hourly", leads: [] },
    { day: "2026-10-14", source: "hourly", leads: [] },
  ],
});

// a day as `mvd observed-map` writes it (night, morning, afternoon, evening, day)
const DOC = {
  day: "2026-10-16",
  source: "hourly",
  parts: ["night", "morning", "afternoon", "evening", "day"],
  okresy: {
    CZ0423: {
      tmax: [8.2, 10.4, 13.2, 10.9, 13.2], tmin: [5.5, 5.8, 9.8, 8.2, 5.5],
      tmax_hi: [9.8, 12.8, 14.1, 11.6, 14.1], tmin_lo: [3, 3.4, 8, 6.8, 3],
      r: [0, 2.4, 0.2, 0, 2.6], r_hi: [0, 4.1, 0.3, 0, 4.4],
      wind: [2.9, 3.3, 4, 4.4, 4.4], gust: [4.1, 7.2, 8.8, 8.8, 8.8],
      ssv: [null, 0.5, 3.8, null, 4.3], cloud: [19, 80, 15, 38, 40],
      n_t: [2, 2, 2, 2, 2], n_r: [5, 5, 5, 5, 5], n_w: [2, 2, 2, 2, 2], n_g: [2, 2, 2, 2, 2],
      n_s: [0, 2, 2, 0, 2], n_c: [1, 1, 1, 1, 1],
      light: [0, 4.5, 6, 0.2, 10.7], st: ["0-20000-0-11464", "0-20000-0-11509"], ph: ["ML"], sno: 0,
    },
    CZ0642: {
      tmax: [9.4, 14.7, 17.4, 14.6, 17.4], tmin: [6.4, 6.5, 13.9, 5.5, 5.5],
      tmax_hi: [9.7, 15.1, 17.9, 15.5, 17.9], tmin_lo: [6.2, 6.3, 13.7, 5.3, 5.3],
      r: [0, 0, 0, 0, 0], r_hi: [0, 0, 0, 0, 0],
      wind: [2.2, 1.5, 1.8, 1.6, 2.5], gust: [3.4, 4.1, 12.6, 3.6, 12.6],
      ssv: [null, 3.5, 5.8, null, 9.2], cloud: [92, 48, 8, 6, 39],
      n_t: [2, 2, 2, 2, 2], n_r: [2, 2, 2, 2, 2], n_w: [2, 2, 2, 2, 2], n_g: [2, 2, 2, 2, 2],
      n_s: [0, 2, 2, 0, 2], n_c: [1, 1, 1, 1, 1],
      light: [0, 4.7, 6, 0, 10.8], st: ["0-20000-0-11723"],
    },
    // Praha: nothing measured (an okres without stations has nulls and zero counts)
    CZ0100: {
      tmax: [null, null, null, null, null], r: [null, null, null, null, null],
      n_t: [0, 0, 0, 0, 0], n_r: [0, 0, 0, 0, 0], light: [0, 4.6, 6, 0.2, 10.7], st: [],
    },
  },
  forecasts: [
    {
      lead: 2, issued: "2026-10-14T20:50Z", columns: ["tmin", "tmax", "precipitation", "rain_probability", "symbol"],
      okresy: { CZ0423: { tmin: [6, 6, 9, 8, 6], tmax: [9, 11, 15, 12, 15], precipitation: [0, 0.2, 0, 0, 0.2], rain_probability: [0.1, 0.3, 0.1, 0.1, 0.3], symbol: ["cloudy", "partly", "clear", "partly", "partly"] } },
    },
    {
      lead: 1, issued: "2026-10-15T20:50Z", columns: ["tmin", "tmax", "precipitation", "rain_probability", "symbol"],
      okresy: { CZ0423: { tmin: [5, 6, 10, 8, 5], tmax: [8, 11, 14, 11, 14], precipitation: [0, 1.5, 0, 0, 1.5], rain_probability: [0.1, 0.7, 0.2, 0.1, 0.7], symbol: ["cloudy", "rain", "partly", "cloudy", "rain"] } },
    },
  ],
};
const VIEW = parseObservedDay(DOC, OKRESY);

test("the index of measured days, oldest first", () => {
  assert.deepEqual(INDEX.days.map((d) => d.day), ["2026-09-01", "2026-10-14", "2026-10-15", "2026-10-16"]);
  assert.equal(INDEX.first, "2026-09-01");
  assert.equal(INDEX.last, "2026-10-16");
  assert.equal(INDEX.byDay.get("2026-09-01").source, "daily");
  // no file yet: nothing offered
  assert.deepEqual(parseObservedIndex(null).days, []);
  assert.equal(parseObservedIndex(null).last, null);
});

test("past day tabs: the last two before today, and an older chosen day", () => {
  assert.deepEqual(pastTabs(INDEX, "2026-10-17"), ["2026-10-15", "2026-10-16"]);
  assert.deepEqual(pastTabs(INDEX, "2026-10-17", "2026-09-01"), ["2026-09-01", "2026-10-15", "2026-10-16"]);
  // a chosen forecast day or a day without a file adds nothing
  assert.deepEqual(pastTabs(INDEX, "2026-10-17", "2026-10-18"), ["2026-10-15", "2026-10-16"]);
  assert.deepEqual(pastTabs(INDEX, "2026-10-17", "2026-08-01"), ["2026-10-15", "2026-10-16"]);
  // only days before today (the index may be a day behind or ahead)
  assert.deepEqual(pastTabs(INDEX, "2026-10-16"), ["2026-10-14", "2026-10-15"]);
  assert.equal(dayKind("2026-10-16", "2026-10-17"), "past");
  assert.equal(dayKind("2026-10-17", "2026-10-17"), "forecast");
});

test("a picked date goes to the nearest measured day; stepping through the days", () => {
  assert.equal(nearestDay(INDEX, "2026-10-15"), "2026-10-15");
  assert.equal(nearestDay(INDEX, "2026-09-20"), "2026-09-01");
  assert.equal(nearestDay(INDEX, "2026-10-01"), "2026-10-14");
  assert.equal(nearestDay(INDEX, "2026-01-01"), "2026-09-01");
  assert.equal(nearestDay(INDEX, ""), null);
  assert.equal(stepDay(INDEX, "2026-10-15", -1), "2026-10-14");
  assert.equal(stepDay(INDEX, "2026-10-16", 1), null);
});

test("day labels for yesterday and the day before", () => {
  assert.equal(dayLabel("2026-10-16", "2026-10-17", "cs").key, "day.yesterday");
  assert.equal(dayLabel("2026-10-15", "2026-10-17", "cs").key, "day.dayBefore");
  assert.equal(dayLabel("2026-10-14", "2026-10-17", "cs").key, undefined);
});

test("parsing a day: rows per okres and part, counts, every okres present", () => {
  assert.equal(VIEW.observed, true);
  assert.deepEqual(VIEW.days, ["2026-10-16"]);
  assert.equal(VIEW.stations, 3);
  const row = rowFor(VIEW, "CZ0423", "2026-10-16", "morning");
  assert.equal(row.measured, true);
  assert.equal(row.tmax, 10.4);
  assert.equal(row.precipitation, 2.4);
  assert.deepEqual(row.counts, { t: 2, r: 5, w: 2, g: 2, s: 2, c: 1 });
  const praha = rowFor(VIEW, "CZ0100", "2026-10-16", "afternoon");
  assert.equal(praha.tmax, null);
  assert.equal(praha.counts.t, 0);
  assert.equal(parseObservedDay(null, OKRESY), null);
});

test("the observed symbol comes from what was measured (diary.js rules)", () => {
  const at = (code, part) => rowFor(VIEW, code, "2026-10-16", part).symbol;
  // 2.4 mm in the morning, with little sun (0.5 of 4.5 h): rain
  assert.equal(at("CZ0423", "morning"), "rain");
  // dry afternoon with 3.8 of 6 h of sun (63 %): clear
  assert.equal(at("CZ0423", "afternoon"), "clear");
  // night: no daylight, the sky from the cloud cover (19 %)
  assert.equal(at("CZ0423", "night"), "clear");
  // Brno's night: 92 % cloud
  assert.equal(at("CZ0642", "night"), "cloudy");
  // nothing measured: no symbol
  assert.equal(at("CZ0100", "afternoon"), null);
  // snow from new snow on the ground, showers when the sun also shone a lot
  assert.equal(observedSymbol({ precipitation: 3, sno: 2, light: 6, sunshine: 0 }, "2026-01-10"), "snow");
  assert.equal(observedSymbol({ precipitation: 1, sunshine: 4, light: 6, tmax: 20, tmin: 12 }, "2026-07-10"), "showers");
  assert.equal(observedSymbol({ precipitation: 0.2, sunshine: 2, light: 6 }, "2026-07-10"), "partly");
});

test("dark parts get the moon", () => {
  assert.equal(isDark("night", 0), true);
  assert.equal(isDark("evening", 0.2), true);
  assert.equal(isDark("morning", 4.5), false);
  assert.equal(isDark("day", 0), false);
  assert.equal(rowFor(VIEW, "CZ0423", "2026-10-16", "evening").dark, true);
});

test("labels and colours of a measured day: mm, gust, sunshine, grey without stations", () => {
  const row = rowFor(VIEW, "CZ0423", "2026-10-16", "morning");
  assert.equal(valueFor(row, "precipitation", "morning"), 2.4);
  assert.equal(labelFor(row, "precipitation", "morning"), "2.4 mm");
  assert.equal(labelFor(row, "gust", "morning"), "7 m/s");
  assert.equal(labelFor(row, "sunshine", "morning"), "0.5 h");
  assert.equal(labelFor(row, "temperature", "morning"), "10°");
  assert.equal(labelFor(row, "temperature", "night"), "6°"); // the minimum
  const praha = rowFor(VIEW, "CZ0100", "2026-10-16", "morning");
  assert.equal(labelFor(praha, "temperature", "morning"), "–");
  const colours = okresColours(VIEW, "2026-10-16", "morning", "precipitation");
  assert.equal(colours.get("CZ0100"), BEYOND);
  assert.notEqual(colours.get("CZ0423"), BEYOND);
  assert.notEqual(colours.get("CZ0423"), colours.get("CZ0642"));
  assert.ok(OBSERVED_LAYERS.includes("gust") && OBSERVED_LAYERS.includes("sunshine"));
});

test("a past day and the measured layers in the URL", () => {
  const offered = { days: ["2026-10-16", "2026-10-17"], okresy: OKRESY };
  const view = parseView("#2026-10-16/afternoon/gust/tps/CZ0423", offered, { day: "2026-10-17", part: "day" });
  assert.deepEqual(view, { day: "2026-10-16", part: "afternoon", colour: "gust", shown: ["temperature", "precipitation", "sunshine"], okres: "CZ0423" });
  assert.equal(viewHash(view), "#2026-10-16/afternoon/gust/tps/CZ0423");
});

test("summary of a measured day", () => {
  const s = observedSummary(VIEW, "afternoon");
  assert.equal(s.warmest.name, "Brno-město");
  assert.equal(s.warmest.value, 17.4);
  assert.equal(s.coldest.name, "Litoměřice");
  assert.equal(s.coldest.value, 9.8);
  assert.equal(s.gust.value, 12.6);
  assert.equal(s.sunniest.name, "Brno-město");
  assert.equal(s.okresy, 2); // Praha measured nothing
  const morning = observedSummary(VIEW, "morning");
  assert.equal(morning.wettest.name, "Litoměřice");
  assert.equal(morning.wettestStation.value, 4.1);
  assert.equal(morning.wet, 1);
  assert.equal(morning.rainOkresy, 2);
  // at night the warmest is by its minimum
  assert.equal(observedSummary(VIEW, "night").warmest.value, 6.4);
});

test("forecast vs. measured: leads, rows and the difference", () => {
  const forecasts = parseForecasts(DOC);
  assert.deepEqual(forecasts.map((f) => f.lead), [1, 2]);
  assert.equal(defaultLead(forecasts), 1);
  assert.equal(defaultLead([{ lead: 0 }]), 0);
  assert.equal(defaultLead([]), null);
  const f = forecasts[0].rows.get("CZ0423|afternoon");
  assert.deepEqual(f, { tmin: 10, tmax: 14, precipitation: 0, rain_probability: 0.2, symbol: "partly" });
  assert.equal(forecasts[0].rows.get("CZ0642|afternoon"), undefined);
  const measured = rowFor(VIEW, "CZ0423", "2026-10-16", "afternoon");
  assert.equal(difference(f, measured, "temperature", "afternoon"), 0.8);
  assert.equal(difference(forecasts[0].rows.get("CZ0423|night"), rowFor(VIEW, "CZ0423", "2026-10-16", "night"), "temperature", "night"), -0.5);
  assert.equal(difference(f, measured, "precipitation", "afternoon"), -0.2);
  assert.equal(difference(undefined, measured, "temperature", "day"), null);
});

test("station dots and links", () => {
  const doc = {
    parts: ["night", "morning", "afternoon", "evening", "day"],
    columns: ["tmax", "tmin", "r", "wind", "gust", "ssv", "cloud"],
    stations: {
      A: [1, 0, 0, 2, 3, null, 50, 2, 1, 0.4, 2, 3, 1, 50, 9, 8, 0, 2, 4, 3, 20, 5, 4, 0, 2, 3, null, 40, 9, 0, 0.4, 2, 4, 4, 40],
      B: Array(35).fill(null),
    },
  };
  const index = { stations: [{ id: "A", name: "Alpha", lat: 50, lon: 14 }, { id: "B", name: "Beta", lat: 49, lon: 15 }] };
  assert.deepEqual(stationValues(doc, index, "afternoon", "temperature"), [{ id: "A", name: "Alpha", lat: 50, lon: 14, value: 9 }]);
  assert.deepEqual(stationValues(doc, index, "night", "temperature")[0].value, 0); // the night's minimum
  assert.equal(stationValues(doc, index, "morning", "precipitation")[0].value, 0.4);
  assert.equal(stationValues(doc, index, "afternoon", "sunshine")[0].value, 3);
  assert.deepEqual(stationValues(doc, index, "day", "nothing"), []);
  assert.deepEqual(stationValues(null, index, "day", "temperature"), []);
  assert.equal(stationLink("0-20000-0-11518", "2026-10-16"), "station.html?day=2026-10-16#0-20000-0-11518");
});
