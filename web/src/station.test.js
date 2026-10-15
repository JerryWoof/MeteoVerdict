import assert from "node:assert/strict";
import { test } from "node:test";

import {
  defaultElement, elementLabel, elementName, elementOrder, formatNumber, isTotal, latestValues, parseStationHash,
  searchStations, seriesPoints, spanLabel, stepTime, viewsWith,
} from "./station.js";

const DOC = {
  elements: {
    T: { name: "Teplota", unit: "°C" },
    SRA: { name: "Srážka", unit: "mm" },
    "C-C1Av": { name: "Ceilometr CLOUD_1 AVG", unit: "m" },
  },
  series: {
    "10min": { start: "2026-10-14T00:10:00Z", step: "10min", values: { T: [9.5, null, 9.1] } },
    daily: { start: "2025-12-30T00:00:00Z", step: "1d", values: { T: [1, 2, null], SRA: [0, 4.2, 0.1] }, how: { T: "AVG" } },
    monthly: { start: "1961-11-01T00:00:00Z", step: "1mo", values: { T: [3.1, -0.4, -2.2] } },
  },
};

test("time of each value", () => {
  const start = new Date("2026-01-31T00:00:00Z");
  assert.equal(stepTime(start, "1d", 1).toISOString(), "2026-02-01T00:00:00.000Z");
  assert.equal(stepTime(new Date("1961-11-01T00:00:00Z"), "1mo", 2).toISOString(), "1962-01-01T00:00:00.000Z");
  assert.equal(stepTime(start, "10min", 6).toISOString(), "2026-01-31T01:00:00.000Z");
  assert.equal(stepTime(new Date("1961-01-01T00:00:00Z"), "1y", 3).toISOString(), "1964-01-01T00:00:00.000Z");
  assert.throws(() => stepTime(start, "2d", 1));
});

test("points skip missing values", () => {
  const points = seriesPoints(DOC.series["10min"], "T");
  assert.deepEqual(points.map((p) => [p.time.toISOString(), p.value]), [
    ["2026-10-14T00:10:00.000Z", 9.5],
    ["2026-10-14T00:30:00.000Z", 9.1],
  ]);
  assert.deepEqual(seriesPoints(DOC.series["10min"], "T", true).map((p) => p.value), [9.5, null, 9.1]);
  assert.deepEqual(seriesPoints(DOC.series["10min"], "SRA"), []);
  assert.deepEqual(seriesPoints(undefined, "T"), []);
  assert.equal(spanLabel(seriesPoints(DOC.series.monthly, "T")), "1961–1962");
  assert.equal(spanLabel([]), "");
});

test("views, latest values and the first element", () => {
  assert.deepEqual(viewsWith(DOC, "T"), ["10min", "daily", "monthly"]);
  assert.deepEqual(viewsWith(DOC, "SRA"), ["daily"]);
  const latest = latestValues(DOC);
  assert.equal(latest.T.value, 9.1);
  assert.equal(latest.T.view, "10min");
  assert.equal(latest.SRA.value, 0.1);
  assert.equal(latest.SRA.time.toISOString(), "2026-01-01T00:00:00.000Z");
  assert.equal(defaultElement(DOC), "T");
  assert.equal(defaultElement({ elements: { SRA: {} }, series: { daily: { values: { SRA: [1] } } } }), "SRA");
  assert.equal(defaultElement({ elements: {}, series: {} }), null);
});

test("names in both languages", () => {
  assert.equal(elementName("T", DOC.elements.T, "en"), "Air temperature");
  assert.equal(elementName("T", DOC.elements.T, "cs"), "Teplota");
  assert.equal(elementLabel("SRA", DOC.elements.SRA, "en"), "Precipitation (mm)");
  assert.equal(elementName("C-C1Av", DOC.elements["C-C1Av"], "en"), "Ceilometer cloud base 1 (mean)");
  assert.equal(elementName("XYZ", undefined, "en"), "XYZ");
  assert.equal(elementName("XYZ", { name: "Něco" }, "en"), "Něco");
  assert.equal(elementName("BO", { name: "bouřka", name_en: "storm" }, "en"), "storm");
  assert.equal(elementName("BO", { name: "bouřka", name_en: "storm" }, "cs"), "bouřka");
  assert.equal(elementLabel("BO", { name: "bouřka", name_en: "storm", unit: "kód", types: ["PHENO"] }, "en"), "storm");
  assert.equal(elementLabel("ww", { name: "Stav počasí", unit: "kód", types: ["1H"] }, "en"), "Present weather (code)");
  assert.equal(elementLabel("ww", { name: "Stav počasí", unit: "kód", types: ["1H"] }, "cs"), "Stav počasí (kód)");
  assert.deepEqual(elementOrder(["T", "C-C1Av", "API30", "BO"]), ["API30", "BO", "T", "C-C1Av"]);
});

test("totals are bars", () => {
  assert.ok(isTotal("SRA"));
  assert.ok(isTotal("SRA1H"));
  assert.ok(isTotal("SSV10M"));
  assert.ok(isTotal("RGLB_D", "SUM"));
  assert.ok(!isTotal("T", "AVG"));
  assert.ok(isTotal("X", "06:00 SUM"));
  assert.ok(isTotal("BO", "", "phenomena"));
});

test("English number format", () => {
  assert.equal(formatNumber(1013.4), "1,013.4");
  assert.equal(formatNumber(-0.25), "-0.25");
  assert.equal(formatNumber(null), "–");
});

test("search ignores diacritics and case", () => {
  const stations = [
    { id: "0-20000-0-11520", name: "Praha, Libuš" },
    { id: "0-20000-0-11723", name: "Brno, Tuřany" },
    { id: "0-203-0-11721", name: "Brno, Žabovřesky" },
    { id: "0-20000-0-11787", name: "Lysá hora" },
  ];
  assert.deepEqual(searchStations(stations, "libus").map((s) => s.name), ["Praha, Libuš"]);
  assert.deepEqual(searchStations(stations, "BRNO").map((s) => s.name), ["Brno, Tuřany", "Brno, Žabovřesky"]);
  assert.deepEqual(searchStations(stations, "zab").map((s) => s.name), ["Brno, Žabovřesky"]);
  assert.deepEqual(searchStations(stations, "11787").map((s) => s.name), ["Lysá hora"]);
  assert.deepEqual(searchStations(stations, "  "), []);
  // names starting with the query first
  assert.deepEqual(searchStations([{ id: "a", name: "Horní Bečva" }, { id: "b", name: "Lysá hora" }], "hor").map((s) => s.id), ["a", "b"]);
});

test("hash", () => {
  assert.deepEqual(parseStationHash("#0-20000-0-11520/SRA1H"), { id: "0-20000-0-11520", element: "SRA1H" });
  assert.deepEqual(parseStationHash(""), { id: null, element: null });
  assert.deepEqual(parseStationHash("#0-20000-0-11520"), { id: "0-20000-0-11520", element: null });
});
