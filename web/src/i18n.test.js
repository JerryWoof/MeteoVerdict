import assert from "node:assert/strict";
import { test } from "node:test";

import { STRINGS, pickLanguage, translator } from "./i18n.js";

test("both languages have the same keys", () => {
  assert.deepEqual(Object.keys(STRINGS.cs).sort(), Object.keys(STRINGS.en).sort());
});

test("language choice", () => {
  assert.equal(pickLanguage("en", "cs-CZ"), "en");
  assert.equal(pickLanguage(null, "cs-CZ"), "cs");
  assert.equal(pickLanguage(null, "sk"), "cs");
  assert.equal(pickLanguage("de", "de-DE"), "en");
  assert.equal(pickLanguage(undefined, undefined), "en");
});

test("translation with parameters and fallbacks", () => {
  const t = translator("cs");
  assert.equal(t("status.scores", { asOf: "2026-10-11", updated: "2026-10-12" }), "Skóre do 2026-10-11 · aktualizováno 2026-10-12");
  assert.equal(t("no.such.key"), "no.such.key");
  assert.equal(translator("xx")("legend.noData"), "no data");
});
