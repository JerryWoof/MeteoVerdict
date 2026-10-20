import assert from "node:assert/strict";
import { test } from "node:test";

import { formatNumber, searchStations } from "./station.js";

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
