import assert from "node:assert/strict";
import { test } from "node:test";

import { forecastUrl, obceOf, obecUrl } from "./trmnl.js";

const index = { obce: [["CZ0100", "b", "Zlíčín", 50, 14], ["CZ0100", "a", "Ďáblice", 50, 14], ["CZ0642", "c", "Brno", 49, 16]] };

test("forecast urls", () => {
  assert.equal(forecastUrl("ai/okresy", "CZ0100"), "https://meteoverdict.cz/api/v1/ai/okresy/CZ0100.json");
  assert.equal(forecastUrl("junk", "CZ0100"), "https://meteoverdict.cz/api/v1/okresy/CZ0100.json");
  assert.equal(obecUrl("CZ0100", "a"), "https://meteoverdict.cz/api/v1/obce/CZ0100/a.json");
  assert.equal(obecUrl("CZ0100", "a", "ai/okresy"), "https://meteoverdict.cz/api/v1/ai/obce/CZ0100/a.json");
});

test("obce of one okres, sorted", () => {
  assert.deepEqual(obceOf(index, "CZ0100").map((o) => o.name), ["Ďáblice", "Zlíčín"]);
  assert.deepEqual(obceOf(null, "CZ0100"), []);
});
