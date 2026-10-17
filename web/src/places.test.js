import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { gzipSync } from "node:zlib";

import { fold, parsePlaces, placeLabel, placesLoader, searchPlaces } from "./places.js";

const DATA = {
  okresy: ["Litoměřice", "Liberec", "Hlavní město Praha", "Ústí nad Labem", "Praha-východ", "Jindřichův Hradec"],
  obce: [
    ["Třeboň", 5, 49.0037, 14.7706],
    ["Nová Ves", 1, 50.8315, 15.0011],
    ["Nová Ves", 0, 50.5, 14.1],
    ["Nová Ves pod Pleší", 4, 49.83, 14.27],
    ["Praha", 2, 50.0846, 14.4178],
    ["Prackovice nad Labem", 0, 50.57, 14.03],
    ["Ústí nad Labem", 3, 50.66, 14.04],
    ["Velké Žernoseky", 0, 50.54, 14.06],
  ],
};
const places = parsePlaces(DATA);
const labels = (query, limit) => searchPlaces(places, query, limit).map(placeLabel);

test("fold drops diacritics, case and extra spaces", () => {
  assert.equal(fold("  Ústí  nad Labem "), "usti nad labem");
  assert.equal(fold("Třeboň"), "trebon");
  assert.equal(fold("ŽĎÁR"), "zdar");
  assert.equal(fold(null), "");
});

test("search ignores diacritics and shows the okres", () => {
  assert.deepEqual(labels("trebon"), ["Třeboň (Jindřichův Hradec)"]);
  assert.deepEqual(labels("TŘEBOŇ"), ["Třeboň (Jindřichův Hradec)"]);
});

test("search ranks the whole name, then the start, then a word, then anywhere", () => {
  assert.equal(labels("praha")[0], "Praha (Hlavní město Praha)");
  assert.deepEqual(labels("pra"), ["Praha (Hlavní město Praha)", "Prackovice nad Labem (Litoměřice)"]);
  assert.deepEqual(labels("labem"), ["Ústí nad Labem (Ústí nad Labem)", "Prackovice nad Labem (Litoměřice)"]);
  assert.deepEqual(labels("zernos"), ["Velké Žernoseky (Litoměřice)"]);
  // inside a word only from three letters
  assert.deepEqual(labels("er"), []);
  assert.deepEqual(labels("ern"), ["Velké Žernoseky (Litoměřice)"]);
});

test("same names are told apart by the okres, and the okres narrows them", () => {
  assert.deepEqual(labels("nova ves").slice(0, 2), ["Nová Ves (Liberec)", "Nová Ves (Litoměřice)"]);
  assert.deepEqual(labels("nova ves lito"), ["Nová Ves (Litoměřice)"]);
  assert.deepEqual(labels("nova ves pod"), ["Nová Ves pod Pleší (Praha-východ)"]);
});

test("search: nothing typed, and the limit", () => {
  assert.deepEqual(labels("   "), []);
  assert.equal(labels("a", 2).length, 0);
  assert.equal(searchPlaces(places, "n", 2).length, 2);
});

test("parsePlaces skips rows that are not a place in Czechia", () => {
  assert.deepEqual(parsePlaces(null), []);
  assert.deepEqual(parsePlaces({ okresy: [] }), []);
  const parsed = parsePlaces({
    okresy: ["Benešov"],
    obce: [["Ok", 0, 49.7, 14.7], ["", 0, 49.7, 14.7], ["No okres", 3, 49.7, 14.7], ["Far", 0, 10, 14.7], "junk", ["Nan", 0, null, 14]],
  });
  assert.deepEqual(parsed.map((p) => p.name), ["Ok"]);
  assert.deepEqual(parsed[0], { name: "Ok", okres: "Benešov", lat: 49.7, lon: 14.7, key: "ok", okresKey: "benesov" });
});

test("placesLoader fetches once and retries after a failure", async () => {
  let calls = 0;
  let fail = true;
  const fakeFetch = async () => {
    calls++;
    if (fail) throw new Error("offline");
    return { ok: true, json: async () => DATA };
  };
  const load = placesLoader("obce.json", fakeFetch);
  assert.deepEqual(await load(), []);
  fail = false;
  const [a, b] = await Promise.all([load(), load()]);
  assert.equal(a.length, DATA.obce.length);
  assert.equal(a, b);
  assert.equal(await load(), a);
  assert.equal(calls, 2);
  const notFound = placesLoader("x", async () => ({ ok: false, json: async () => DATA }));
  assert.deepEqual(await notFound(), []);
});

test("the committed municipalities: all of them, small enough", () => {
  const raw = readFileSync(new URL("./data/obce.json", import.meta.url));
  const data = JSON.parse(raw);
  const all = parsePlaces(data);
  assert.equal(all.length, data.obce.length);
  assert.ok(all.length > 6200, String(all.length));
  assert.equal(data.okresy.length, 77);
  assert.ok(gzipSync(raw).length < 300 * 1024);
  assert.deepEqual(searchPlaces(all, "trebon").slice(0, 2).map(placeLabel), ["Třeboň (Jindřichův Hradec)", "Třebonín (Kutná Hora)"]);
  assert.equal(placeLabel(searchPlaces(all, "brno")[0]), "Brno (Brno-město)");
  assert.equal(searchPlaces(all, "praha")[0].okres, "Hlavní město Praha");
});
