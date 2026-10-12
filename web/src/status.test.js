import assert from "node:assert/strict";
import { test } from "node:test";

import { translator } from "./i18n.js";
import { statusText } from "./status.js";

const t = translator("en");

test("no scores yet", () => {
  assert.match(statusText(null, t), /No scores yet/);
  assert.match(statusText({ generated: "2026-10-12T05:30:00+00:00" }, t), /No scores yet/);
});

test("scores and update date", () => {
  const meta = { generated: "2026-10-12T05:30:00+00:00", as_of: "2026-10-11" };
  assert.equal(statusText(meta, t), "Scores up to 2026-10-11 · updated 2026-10-12");
  assert.equal(statusText(meta, translator("cs")), "Skóre do 2026-10-11 · aktualizováno 2026-10-12");
});
