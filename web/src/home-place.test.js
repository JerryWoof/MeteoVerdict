import assert from "node:assert/strict";
import { test } from "node:test";

import { forecastLink, nearestPlace, okresOf } from "./home-place.js";

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
});

test("forecastLink: okres and encoded obec", () => {
  assert.equal(forecastLink("CZ0423", "Úštěk"), "forecast-detail.html#CZ0423/%C3%9A%C5%A1t%C4%9Bk");
  assert.equal(forecastLink("CZ0100"), "forecast-detail.html#CZ0100");
});
