import assert from "node:assert/strict";
import { test } from "node:test";

import { formatFixed, formatNumber, formatSigned, searchStations } from "./station.js";

test("number format: English by default, else the page's language", () => {
  assert.equal(formatNumber(1013.4), "1,013.4");
  assert.equal(formatNumber(-0.25), "−0.25");
  assert.equal(formatNumber(null), "–");
  assert.equal(formatNumber(1600, "cs"), "1\u00a0600");
  assert.equal(formatNumber(1600, "en"), "1,600");
});

test("fixed decimals: the page's decimal sign, no negative zero, a true minus", () => {
  assert.equal(formatFixed(0, "cs", 1), "0,0");
  assert.equal(formatFixed(0, "en", 1), "0.0");
  assert.equal(formatFixed(-0.3, "cs"), "0");
  assert.equal(formatFixed(-0.04, "en", 1), "0.0");
  assert.equal(formatFixed(-2.6, "en"), "−3");
  assert.equal(formatFixed(null, "en"), "–");
  assert.equal(formatSigned(1.2, "en", 1), "+1.2");
  assert.equal(formatSigned(-0.4, "en"), "0");
  assert.equal(formatSigned(-1, "cs"), "−1");
  assert.equal(formatSigned(null, "cs"), "");
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
  // the stations in the okres of that name before another okres's, an exact name first
  const praha = [
    { id: "1", name: "Praha, Brdy", okres: "Příbram" },
    { id: "2", name: "Praha, Libuš", okres: "území Hlavního města Prahy" },
    { id: "3", name: "Nová Praha", okres: "Kolín" },
  ];
  assert.deepEqual(searchStations(praha, "praha").map((s) => s.id), ["2", "1", "3"]);
  assert.deepEqual(searchStations([...praha, { id: "4", name: "Praha" }], "Praha").map((s) => s.id), ["4", "2", "1", "3"]);
});
