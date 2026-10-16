import assert from "node:assert/strict";
import { test } from "node:test";

import { translator } from "./i18n.js";
import {
  DEFAULT_VIEW, availableLeadDays, availableWindows, pickWindow, availableVariables, dayCount, formatRange, parseHash, sameAs90d,
  toHash, windowLabel, windowSpan,
} from "./view.js";

// the published meta.json of 12 Oct 2026 (site/data/meta.json): history still short
const SHORT = {
  "90d": { from: "2026-08-23", to: "2026-09-30" },
  all: { from: "2026-08-23", to: "2026-09-30" },
  jja: { from: "2026-08-23", to: "2026-09-30" },
  season: { from: "2026-09-01", to: "2026-09-30" },
  son: { from: "2026-08-23", to: "2026-09-30" },
};
// once the backfill reached January 2024
const LONG = {
  "90d": { from: "2026-07-03", to: "2026-09-30" },
  all: { from: "2024-01-01", to: "2026-09-30" },
  djf: { from: "2024-01-01", to: "2026-09-30" },
};

test("the URL hash round-trips", () => {
  const view = { variable: "wind_speed_10m", leadDay: 3, window: "jja" };
  assert.deepEqual(parseHash(toHash(view)), view);
});

test("unknown parts of the hash fall back to the default", () => {
  assert.deepEqual(parseHash(""), DEFAULT_VIEW);
  assert.deepEqual(parseHash("#nonsense/9/forever"), DEFAULT_VIEW);
  assert.equal(parseHash("#precipitation_24h/x/all").leadDay, 1);
});

test("variables follow meta.json", () => {
  assert.deepEqual(availableVariables({ variables: ["wind_speed_10m", "temperature_2m", "precipitation"] }), [
    "temperature_2m",
    "wind_speed_10m",
  ]);
  assert.ok(availableVariables(null).includes("precipitation_24h"));
});

test("lead days with data", () => {
  assert.deepEqual(availableLeadDays([{ lead_day: 3 }, { lead_day: 1 }, { lead_day: 3 }]), [1, 3]);
  assert.deepEqual(availableLeadDays([]), [1]);
});

test("a window's real days: seasonal windows only count their season", () => {
  assert.deepEqual(windowSpan("all", SHORT), { from: "2026-08-23", to: "2026-09-30", days: 39 });
  assert.deepEqual(windowSpan("jja", SHORT), { from: "2026-08-23", to: "2026-08-31", days: 9 });
  assert.deepEqual(windowSpan("son", SHORT), { from: "2026-09-01", to: "2026-09-30", days: 30 });
  assert.deepEqual(windowSpan("djf", LONG), { from: "2024-01-01", to: "2026-02-28", days: 31 + 29 + (31 + 31 + 28) + (31 + 31 + 28) });
  assert.equal(windowSpan("mam", SHORT), null);
  assert.equal(windowSpan("90d", null), null);
});

test("windows covering the same days as the 90-day window", () => {
  assert.equal(sameAs90d("all", SHORT), true);
  assert.equal(sameAs90d("90d", SHORT), false);
  assert.equal(sameAs90d("season", SHORT), false);
  assert.equal(sameAs90d("jja", SHORT), false); // same from/to in meta, but only August days
  assert.equal(sameAs90d("all", LONG), false);
  assert.equal(sameAs90d("mam", SHORT), false);
});

test("date ranges in Czech and English", () => {
  assert.equal(formatRange("2026-08-23", "2026-09-30", "en"), "23 Aug – 30 Sep 2026");
  assert.equal(formatRange("2026-08-23", "2026-09-30", "cs"), "23. 8. – 30. 9. 2026");
  assert.equal(formatRange("2024-01-01", "2026-09-30", "en"), "1 Jan 2024 – 30 Sep 2026");
  assert.equal(formatRange("2024-01-01", "2026-09-30", "cs"), "1. 1. 2024 – 30. 9. 2026");
  assert.equal(formatRange("2026-09-30", "2026-09-30", "cs"), "30. 9. 2026");
});

test("Czech day counts", () => {
  const cs = translator("cs");
  assert.deepEqual([1, 2, 4, 5, 39].map((n) => dayCount(n, cs)), ["1 den", "2 dny", "4 dny", "5 dní", "39 dní"]);
  assert.equal(dayCount(1, translator("en")), "1 day");
});

test("window labels show the range, the days and duplicates of the 90-day window", () => {
  const en = translator("en");
  const cs = translator("cs");
  assert.equal(windowLabel("90d", SHORT, en, "en"), "Last 90 days: 23 Aug – 30 Sep 2026 (39 days)");
  assert.equal(
    windowLabel("all", SHORT, en, "en"),
    "All time: 23 Aug – 30 Sep 2026 (39 days) · same as last 90 days for now",
  );
  assert.equal(
    windowLabel("all", SHORT, cs, "cs"),
    "Celé období: 23. 8. – 30. 9. 2026 (39 dní) · zatím stejné jako 90 dní",
  );
  assert.equal(windowLabel("season", SHORT, cs, "cs"), "Tato sezóna: 1. 9. – 30. 9. 2026 (30 dní)");
  assert.equal(windowLabel("mam", SHORT, en, "en"), "All springs: no data yet");
  assert.equal(windowLabel("all", LONG, en, "en"), "All time: 1 Jan 2024 – 30 Sep 2026 (1004 days)");
});

test("only windows with scored days are offered, never an empty default", () => {
  assert.deepEqual(availableWindows(SHORT), ["90d", "season", "all", "jja", "son"]);
  assert.deepEqual(availableWindows(LONG), ["90d", "all", "djf"]);
  assert.deepEqual(availableWindows({ "90d": { from: "2026-08-23", to: "2026-09-30" }, djf: { from: "2026-08-23", to: "2026-09-30" } }), ["90d"]);
  assert.equal(availableWindows(null).length, 7);
  assert.equal(pickWindow("mam", availableWindows(SHORT)), "90d");
  assert.equal(pickWindow("jja", availableWindows(SHORT)), "jja");
  assert.equal(pickWindow("mam", ["all", "son"]), "all");
});
