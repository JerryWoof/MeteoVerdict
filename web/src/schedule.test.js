import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { SCHEDULE, pragueClock } from "./schedule.js";

// "50 4 * * *" lines of a workflow → ["04:50", …]
function cronTimes(file) {
  const text = readFileSync(new URL(`../../.github/workflows/${file}`, import.meta.url), "utf8");
  return [...text.matchAll(/- cron: "(\d+) ([\d,]+) \* \* \*"/g)].flatMap(([, m, hours]) =>
    hours.split(",").map((h) => `${h.padStart(2, "0")}:${m.padStart(2, "0")}`));
}

test("the workflow schedules shown on the Data page are the workflows' cron", () => {
  assert.deepEqual(SCHEDULE.daily, cronTimes("daily.yml"));
  assert.deepEqual(SCHEDULE.runs, cronTimes("runs.yml"));
  assert.deepEqual(SCHEDULE.chmi, cronTimes("chmi-archive.yml"));
});

test("Prague clock time: summer and winter", () => {
  assert.equal(pragueClock("05:17", new Date("2026-07-01T00:00:00Z")), "07:17");
  assert.equal(pragueClock("05:17", new Date("2026-12-01T00:00:00Z")), "06:17");
  assert.equal(pragueClock("22:50", new Date("2026-12-01T00:00:00Z")), "23:50");
});
