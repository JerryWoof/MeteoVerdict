import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  colorFor, currentPart, dayLabel, fillExpression, iconName, labelFor, parseOutlook,
  pointFeatures, rowFor, sequence, summary, today, valueFor,
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
  const expression = fillExpression(OUTLOOK, DAY, "afternoon", "temperature");
  assert.equal(expression[0], "match");
  assert.equal(expression.length, 3 + 2 * 77);
});

test("symbols get a moon at night", () => {
  assert.equal(iconName("clear", "night"), "clear-night");
  assert.equal(iconName("rain", "night"), "rain");
  assert.equal(iconName("partly", "afternoon"), "partly");
  assert.equal(iconName(null, "day"), "");
});

test("points carry symbol and label for every okres", () => {
  const points = pointFeatures(OUTLOOK, DAY, "afternoon", "temperature");
  assert.equal(points.features.length, 77);
  const praha = points.features.find((f) => f.properties.code === "CZ0100");
  assert.match(praha.properties.label, /^-?\d+°$/);
  assert.ok(praha.properties.icon.length > 0);
});

test("headline: warmest, coldest, rain likely", () => {
  const s = summary(OUTLOOK, DAY, "afternoon");
  assert.equal(s.okresy, 77);
  assert.ok(s.warmest.value >= s.coldest.value);
  const all = OUTLOOK.okresy.map((o) => rowFor(OUTLOOK, o.code, DAY, "afternoon").tmax);
  assert.equal(s.warmest.value, Math.max(...all));
  assert.ok(s.rainy >= 0 && s.rainy <= 77);
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

test("play goes through every part of every day from the current one", () => {
  const steps = sequence(OUTLOOK, DAY, "afternoon");
  assert.deepEqual(steps[0], { day: DAY, part: "afternoon" });
  assert.equal(steps.length, 6 * 4);
  assert.equal(new Set(steps.map((s) => `${s.day}|${s.part}`)).size, steps.length);
});
