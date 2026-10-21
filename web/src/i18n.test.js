import assert from "node:assert/strict";
import { test } from "node:test";

import { STRINGS, pickLanguage, translator } from "./i18n.js";

test("both languages have the same keys", () => {
  assert.deepEqual(Object.keys(STRINGS.cs).sort(), Object.keys(STRINGS.en).sort());
});

test("language choice", () => {
  assert.equal(pickLanguage("en", "cs-CZ"), "en");
  assert.equal(pickLanguage(null, "en-GB"), "cs");
  assert.equal(pickLanguage("de", "de-DE"), "cs");
  assert.equal(pickLanguage(undefined, undefined), "cs");
});

test("translation with parameters and fallbacks", () => {
  const t = translator("cs");
  assert.equal(t("status.scores", { asOf: "2026-10-11", updated: "2026-10-12" }), "Skóre do 11. 10. 2026 · aktualizováno 12. 10. 2026");
  assert.equal(t("no.such.key"), "no.such.key");
  assert.equal(translator("xx")("legend.noData"), "no data");
  // a day in the parameters is written in the language
  assert.equal(translator("cs")("status.scores", { asOf: "2026-10-19", updated: "2026-10-20" }), "Skóre do 19. 10. 2026 · aktualizováno 20. 10. 2026");
  assert.equal(translator("en")("status.scores", { asOf: "2026-10-19", updated: "2026-10-20" }), "Scores up to 19 Oct 2026 · updated 20 Oct 2026");
  assert.match(translator("cs")("farm.basis", { runs: 3, first: "2026-07-27 00 UTC", last: "2026-10-19 12 UTC", stations: 5 }), /od 27\. 7\. 2026 00 UTC do 19\. 10\. 2026 12 UTC/);
});
