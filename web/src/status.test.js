import assert from "node:assert/strict";
import { test } from "node:test";

import { statusText } from "./status.js";

test("no scores yet", () => {
  assert.match(statusText(null), /No scores yet/);
  assert.match(statusText({ generated: "2026-10-12T05:30:00+00:00" }), /No scores yet/);
});

test("scores and update date", () => {
  const meta = { generated: "2026-10-12T05:30:00+00:00", as_of: "2026-10-11" };
  assert.equal(statusText(meta), "Scores up to 2026-10-11 · updated 2026-10-12");
});
