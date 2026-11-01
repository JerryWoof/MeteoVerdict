import assert from "node:assert/strict";
import { test } from "node:test";

import { OUTSIDE_KM, forecastLink, locateErrorKey, nearestPlace, okresOf } from "./home-place.js";

const okresy = [
  { code: "CZ0100", name: "Praha" },
  { code: "CZ0423", name: "Litoměřice" },
];

test("okresOf: by name, Prague's okres is the city", () => {
  assert.equal(okresOf({ okres: "Litoměřice" }, okresy).code, "CZ0423");
  assert.equal(okresOf({ okres: "Hlavní město Praha" }, okresy).code, "CZ0100");
  assert.equal(okresOf({ okres: "Nikde" }, okresy), null);
});

test("nearestPlace: the closest place to a position", () => {
  const places = [
    { name: "A", lat: 50.0, lon: 14.0 },
    { name: "B", lat: 50.5, lon: 14.1 },
  ];
  assert.equal(nearestPlace(places, 50.45, 14.1).name, "B");
  assert.equal(nearestPlace([], 50, 14), null);
  // with a limit: a position far from every place (Madrid) is outside, not its nearest place
  assert.equal(nearestPlace(places, 40.4, -3.7, OUTSIDE_KM), null);
  assert.equal(nearestPlace(places, 50.1, 14.05, OUTSIDE_KM).name, "A");
});

test("locateErrorKey: our own sentence per geolocation error", () => {
  assert.equal(locateErrorKey({ code: 1, message: "User denied Geolocation" }), "locate.denied");
  assert.equal(locateErrorKey({ code: 2 }), "locate.unavailable");
  assert.equal(locateErrorKey({ code: 3 }), "locate.timeout");
  assert.equal(locateErrorKey(null), "locate.unavailable");
});

test("forecastLink: okres and encoded obec", () => {
  assert.equal(forecastLink("CZ0423", "Úštěk"), "./#CZ0423/%C3%9A%C5%A1t%C4%9Bk");
  assert.equal(forecastLink("CZ0100"), "./#CZ0100");
});
