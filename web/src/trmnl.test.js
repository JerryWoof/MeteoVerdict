import assert from "node:assert/strict";
import { test } from "node:test";

import { TEMPLATE_URL, forecastUrl, obceOf, obecUrl, pollingLines } from "./trmnl.js";

const index = { obce: [["CZ0100", "b", "Zlíčín", 50, 14], ["CZ0100", "a", "Ďáblice", 50, 14], ["CZ0642", "c", "Brno", 49, 16]] };

test("forecast urls", () => {
  assert.equal(forecastUrl("ai/okresy", "CZ0100"), "https://jerrywoof.github.io/MeteoVerdict/api/v1/ai/okresy/CZ0100.json");
  assert.equal(forecastUrl("junk", "CZ0100"), "https://jerrywoof.github.io/MeteoVerdict/api/v1/okresy/CZ0100.json");
  assert.equal(obecUrl("CZ0100", "a"), "https://jerrywoof.github.io/MeteoVerdict/api/v1/obce/CZ0100/a.json");
  assert.equal(obecUrl("CZ0100", "a", "ai/okresy"), "https://jerrywoof.github.io/MeteoVerdict/api/v1/ai/obce/CZ0100/a.json");
});

test("obce of one okres, sorted", () => {
  assert.deepEqual(obceOf(index, "CZ0100").map((o) => o.name), ["Ďáblice", "Zlíčín"]);
  assert.deepEqual(obceOf(null, "CZ0100"), []);
});

test("polling lines", () => {
  assert.deepEqual(pollingLines("CZ0100"), [TEMPLATE_URL]);
  assert.deepEqual(pollingLines("CZ0100", { id: "a" }), [forecastUrl("okresy", "CZ0100"), obecUrl("CZ0100", "a")]);
  assert.deepEqual(pollingLines("CZ0100", { id: "a" }, "ai/okresy"), [
    "https://jerrywoof.github.io/MeteoVerdict/api/v1/ai/okresy/CZ0100.json",
    "https://jerrywoof.github.io/MeteoVerdict/api/v1/ai/obce/CZ0100/a.json",
  ]);
});
