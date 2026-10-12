import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CAPITALS, DEFAULT_SHOWN, NEUTRAL, colorFor, currentPart, dayLabel, displayName, ease, iconName,
  labelFor, lerpRow, mixColor, nextColour, okresColours, parseOutlook, parseView, placeMarkers,
  playSteps, rowFor, startIndex, summary, today, valueFor, viewHash,
} from "./tv.js";

// the real outlook.json of the first run of the Outlook workflow (12 Oct 2026, 08:31 UTC)
const OUTLOOK = parseOutlook(JSON.parse(readFileSync(new URL("./fixtures/outlook.json", import.meta.url))));
const DAY = "2026-10-13";

test("parsing outlook.json", () => {
  assert.equal(OUTLOOK.okresy.length, 77);
  assert.equal(OUTLOOK.days.length, 6);
  const row = rowFor(OUTLOOK, "CZ0100", DAY, "afternoon");
  assert.equal(row.okres, "CZ0100");
  assert.ok(row.tmin <= row.tmax);
  assert.equal(rowFor(OUTLOOK, "CZ0100", "1999-01-01", "day"), undefined);
});

test("values and labels per layer", () => {
  const row = { tmin: 3.4, tmax: 12.6, rain_probability: 0.55, wind: 4.4, cloud: 71 };
  assert.equal(valueFor(row, "temperature", "night"), 3.4);
  assert.equal(valueFor(row, "temperature", "afternoon"), 12.6);
  assert.equal(labelFor(row, "temperature", "afternoon"), "13°");
  assert.equal(labelFor(row, "precipitation", "day"), "55 %");
  assert.equal(labelFor(row, "wind", "day"), "4 m/s");
  assert.equal(labelFor(row, "cloud", "day"), "71 %");
  assert.equal(labelFor(undefined, "temperature", "day"), "");
});

test("colour ramps interpolate and clamp", () => {
  assert.equal(colorFor(-40, "temperature"), "#313695");
  assert.equal(colorFor(50, "temperature"), "#a50026");
  assert.equal(colorFor(12.5, "temperature"), colorFor(12.5, "temperature"));
  assert.notEqual(colorFor(10, "temperature"), colorFor(15, "temperature"));
  assert.equal(colorFor(null, "wind"), "#ececec");
  assert.notEqual(colorFor(0, "precipitation"), colorFor(1, "precipitation"));
});

test("symbols get a moon at night", () => {
  assert.equal(iconName("clear", "night"), "clear-night");
  assert.equal(iconName("rain", "night"), "rain");
  assert.equal(iconName("partly", "afternoon"), "partly");
  assert.equal(iconName(null, "day"), "");
});

test("headline: warmest, coldest, rain likely", () => {
  const s = summary(OUTLOOK, DAY, "afternoon");
  assert.equal(s.okresy, 77);
  assert.ok(s.warmest.value >= s.coldest.value);
  const all = OUTLOOK.okresy.map((o) => rowFor(OUTLOOK, o.code, DAY, "afternoon").tmax);
  assert.equal(s.warmest.value, Math.max(...all));
  assert.ok(s.rainy >= 0 && s.rainy <= 77);
  const winds = OUTLOOK.okresy.map((o) => rowFor(OUTLOOK, o.code, DAY, "afternoon").wind);
  assert.equal(s.windiest.value, Math.max(...winds));
  assert.ok(s.clear >= 0 && s.clear <= 77);
  assert.equal(summary(OUTLOOK, "1999-01-01", "day"), null);
});

test("now in Prague: part of day and date", () => {
  assert.equal(currentPart(Date.parse("2026-10-12T04:30Z")), "morning"); // 06:30 CEST
  assert.equal(currentPart(Date.parse("2026-10-12T02:30Z")), "night");
  assert.equal(currentPart(Date.parse("2026-10-12T21:59Z")), "evening");
  assert.equal(today(Date.parse("2026-10-12T22:30Z")), "2026-10-13");
});

test("day tabs: today, tomorrow, then dates", () => {
  assert.deepEqual(dayLabel("2026-10-12", "2026-10-12", "cs"), { key: "tv.today" });
  assert.deepEqual(dayLabel("2026-10-13", "2026-10-12", "cs"), { key: "tv.tomorrow" });
  assert.match(dayLabel("2026-10-15", "2026-10-12", "cs").text, /15\. ?10\./);
});

test("markers: capitals first, no overlaps, by each marker's own size", () => {
  const boxes = [
    { code: "CZ0209", x: 100, y: 100, w: 40, h: 40 }, // Praha-východ, next to Praha
    { code: "CZ0100", x: 110, y: 105, w: 40, h: 40 },
    { code: "CZ0201", x: 100, y: 200, w: 40, h: 40 },
    { code: "CZ0202", x: 100, y: 150, w: 40, h: 90 }, // a tall marker reaches Praha
  ];
  const shown = placeMarkers(boxes);
  assert.deepEqual([...shown].sort(), ["CZ0100", "CZ0201"]);
  // the selected okres goes first, and its neighbours make room for it
  assert.deepEqual([...placeMarkers(boxes, 4, "CZ0209")].sort(), ["CZ0201", "CZ0209"]);
  assert.ok(CAPITALS.includes("CZ0100"));
  assert.equal(displayName("území Hlavního města Prahy"), "Praha");
  assert.equal(displayName("Benešov"), "Benešov");
});

test("the view in the URL, including old links", () => {
  const fallback = { day: "2026-10-12", part: "morning" };
  const view = parseView("#2026-10-13/night/precipitation/tw/CZ0201", OUTLOOK, fallback);
  assert.deepEqual(view, {
    day: "2026-10-13", part: "night", colour: "precipitation", shown: ["temperature", "wind"], okres: "CZ0201",
  });
  assert.equal(viewHash(view), "#2026-10-13/night/precipitation/tw/CZ0201");
  // the first version of the page: #day/part/layer/okres
  const old = parseView("#2026-10-13/afternoon/temperature/CZ0201", OUTLOOK, fallback);
  assert.equal(old.okres, "CZ0201");
  assert.deepEqual(old.shown, DEFAULT_SHOWN);
  const none = parseView("#2026-10-13/day/none/-", OUTLOOK, fallback);
  assert.deepEqual(none.shown, []);
  assert.equal(none.colour, "temperature"); // "no colour" is no longer offered
  assert.equal(viewHash(none), "#2026-10-13/day/temperature/-");
  assert.deepEqual(parseView("", OUTLOOK, fallback), {
    day: "2026-10-12", part: "morning", colour: "temperature", shown: DEFAULT_SHOWN, okres: null,
  });
});

test("play: the four parts of one day, or of every day of the week", () => {
  assert.deepEqual(playSteps(OUTLOOK, "day", DAY), [
    { day: DAY, part: "night" },
    { day: DAY, part: "morning" },
    { day: DAY, part: "afternoon" },
    { day: DAY, part: "evening" },
  ]);
  const week = playSteps(OUTLOOK, "week", DAY);
  assert.equal(week.length, 6 * 4);
  assert.deepEqual(week[0], { day: OUTLOOK.days[0], part: "night" });
  assert.ok(!week.some((s) => s.part === "day"));
  assert.equal(startIndex(week, DAY, "afternoon"), 4 + 2);
  assert.equal(startIndex(week, DAY, "day"), 0); // "whole day" shown: start from the beginning
});

test("each round colours the map with the next value", () => {
  assert.equal(nextColour("temperature"), "precipitation");
  assert.equal(nextColour("cloud"), "temperature");
  assert.equal(nextColour("none"), "temperature");
});

test("transitions: rows, colours and easing in between", () => {
  const a = { tmin: 2, tmax: 10, rain_probability: 0, wind: 2, cloud: 20, symbol: "clear" };
  const b = { tmin: 4, tmax: 14, rain_probability: 1, wind: 6, cloud: 100, symbol: "rain" };
  const mid = lerpRow(a, b, 0.25);
  assert.equal(mid.tmax, 11);
  assert.equal(mid.cloud, 40);
  assert.equal(mid.symbol, "clear");
  assert.equal(lerpRow(a, b, 0.75).symbol, "rain");
  assert.equal(lerpRow(undefined, b, 0.2), b);
  assert.equal(mixColor("#000000", "#ffffff", 0.5), "#808080");
  assert.equal(mixColor("#102030", "#102030", 0.3), "#102030");
  assert.equal(ease(0), 0);
  assert.equal(ease(1), 1);
  assert.equal(ease(0.5), 0.5);
  const colours = okresColours(OUTLOOK, DAY, "afternoon", "temperature");
  assert.equal(colours.size, 77);
  assert.equal(okresColours(OUTLOOK, DAY, "afternoon", "unknown").get("CZ0100"), NEUTRAL);
});
