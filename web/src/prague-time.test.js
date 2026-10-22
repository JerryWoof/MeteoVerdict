import assert from "node:assert/strict";
import { test } from "node:test";

import { pragueClock, pragueHour } from "./prague-time.js";

test("a UTC hour is shown as Prague's clock hour of the day: CEST in summer, CET in winter", () => {
  const summer = new Date("2026-10-22T12:00:00Z");
  const winter = new Date("2026-10-26T12:00:00Z");
  assert.equal(pragueHour(0, summer), 2);
  assert.equal(pragueHour(0, winter), 1);
  assert.equal(pragueHour(18, winter), 19);
  assert.equal(pragueHour(23, winter), 0);
  assert.equal(pragueClock("runs at {@00}, {@06} h", summer), "runs at 2, 8 h");
  assert.equal(pragueClock("runs at {@00}, {@06} h", winter), "runs at 1, 7 h");
  assert.equal(pragueClock("no tokens {lead}"), "no tokens {lead}");
});
