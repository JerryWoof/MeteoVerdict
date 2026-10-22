import assert from "node:assert/strict";
import { test } from "node:test";

import { translator } from "./i18n.js";
import { heatStatus, statusText } from "./status.js";

const t = translator("en");

test("no scores yet", () => {
  assert.match(statusText(null, t), /No scores yet/);
  assert.match(statusText({ generated: "2026-10-12T05:30:00+00:00" }, t), /No scores yet/);
});

test("scores and update date", () => {
  const meta = { generated: "2026-10-12T05:30:00+00:00", as_of: "2026-10-11" };
  assert.equal(statusText(meta, t), "Scores up to 11 Oct 2026 · updated 12 Oct 2026");
  assert.equal(statusText(meta, translator("cs")), "Skóre do 11. 10. 2026 · aktualizováno 12. 10. 2026");
});

test("heatmap status: AI run time in Prague, days of the map, stale after 30 h", () => {
  const issued = Date.parse("2026-10-21T20:27:00Z"); // 22:27 in Prague (CEST)
  const hours = [{ time: Date.parse("2026-10-21T21:00Z") }, { time: Date.parse("2026-10-26T20:00Z") }];
  const index = { issued, hours };
  const now = issued + 12 * 3600e3;
  assert.deepEqual(heatStatus(index, translator("cs"), "cs", now), {
    text: "Výpočet AI: 21. 10. 2026 22:27 · mapa na 21.–\u206026. 10.",
    stale: false,
  });
  assert.deepEqual(heatStatus(index, translator("en"), "en", now), {
    text: "AI run: 21 Oct 2026, 22:27 · map for 21–26 Oct",
    stale: false,
  });
  const old = heatStatus(index, translator("cs"), "cs", issued + 31 * 3600e3);
  assert.equal(old.stale, true);
  assert.equal(old.text, "Výpočet AI: 21. 10. 2026 22:27 · mapa na 21.–\u206026. 10. · starší data");
  assert.deepEqual(heatStatus(null, t, "en"), { text: "", stale: false });
  const across = { issued, hours: [{ time: Date.parse("2026-10-30T22:00Z") }, { time: Date.parse("2026-11-02T22:00Z") }] };
  assert.equal(heatStatus(across, translator("cs"), "cs", now).text, "Výpočet AI: 21. 10. 2026 22:27 · mapa na 30. 10.–\u20602. 11.");
});
