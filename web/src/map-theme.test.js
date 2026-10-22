import assert from "node:assert/strict";
import { test } from "node:test";
import { withTheme } from "./map-theme.js";
import { baseLayers, topLayers } from "./radar-basemap.js";

test("light layers are untouched, dark ones get the dark values", () => {
  assert.equal(baseLayers(false)[0].paint["background-color"], "#f3f1ec");
  assert.equal(baseLayers(true)[0].paint["background-color"], "#151412");
  assert.equal(topLayers("cs", false).find((l) => l.id === "place-city").paint["text-color"], "#22292f");
  assert.notEqual(topLayers("cs", true).find((l) => l.id === "place-city").paint["text-color"], "#22292f");
});

test("withTheme sets layout properties without a layout object", () => {
  const [out] = withTheme([{ id: "a", paint: {} }], { a: { "layout:x": ["l", "d"] } }, true);
  assert.equal(out.layout.x, "d");
});
