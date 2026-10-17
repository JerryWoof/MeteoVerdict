import assert from "node:assert/strict";
import { gzipSync } from "node:zlib";
import { test } from "node:test";

import {
  addDays, chunksFor, columnsFor, dayCourse, dayLength, dayRows, daySymbol, daytimeCloud, parseDiaryFile,
  parseDiaryQuery, periodSummary, pragueDayBounds, precipitationKind, shiftDay, viewRange, weekStart,
} from "./diary.js";

const PRAHA = 50.1;

/** A row as dayRows gives it. */
const row = (fields = {}) => ({
  day: "2026-07-01", tx: null, tn: null, t: null, r: null, sno: null, sce: null, ssv: null, g: null,
  phenomena: [], flags: {}, unchecked: false, ...fields,
});

test("days, weeks and months", () => {
  assert.equal(addDays("2026-02-28", 1), "2026-03-01");
  assert.equal(addDays("2024-03-01", -1), "2024-02-29");
  assert.equal(weekStart("2026-10-18"), "2026-10-12"); // a Sunday → its Monday
  assert.equal(weekStart("2026-10-12"), "2026-10-12");
  assert.deepEqual(viewRange("days", "2026-10-16"), { from: "2026-10-03", to: "2026-10-16" });
  assert.deepEqual(viewRange("week", "2026-10-16"), { from: "2026-10-12", to: "2026-10-18" });
  assert.deepEqual(viewRange("month", "2024-02-10"), { from: "2024-02-01", to: "2024-02-29" });
  // never past the archive
  assert.deepEqual(viewRange("month", "2026-10-10", "1946-01-01", "2026-10-16"), { from: "2026-10-01", to: "2026-10-16" });
  assert.deepEqual(viewRange("days", "1946-01-05", "1946-01-01", "2026-10-16"), { from: "1946-01-01", to: "1946-01-05" });
  assert.equal(shiftDay("days", "2026-10-16", -1), "2026-10-02");
  assert.equal(shiftDay("week", "2026-10-16", 1), "2026-10-23");
  assert.equal(shiftDay("month", "2026-03-31", -1), "2026-02-28");
  assert.equal(shiftDay("month", "2025-12-15", 1), "2026-01-15");
});

test("which decade files a period needs", () => {
  const diary = { decade: 10, chunks: [1940, 1950, 2010, 2020] };
  assert.deepEqual(chunksFor(diary, "2019-12-25", "2020-01-07"), [2010, 2020]);
  assert.deepEqual(chunksFor(diary, "1955-07-01", "1955-07-31"), [1950]);
  assert.deepEqual(chunksFor(diary, "1975-07-01", "1975-07-31"), []); // a gap in the history
});

test("rows of days from the decade files", () => {
  const chunk = {
    start: "2020-01-01",
    days: 3,
    values: { tx: [5, null, 7], r: [0, 2.5, 0] },
    phenomena: { BO: [1], DE: [1], ML: [0] },
    flags: { r: { T: [2] } },
    unchecked: [2],
  };
  const rows = dayRows([chunk], "2019-12-31", "2020-01-04");
  assert.deepEqual(rows.map((r) => r.day), ["2019-12-31", "2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"]);
  assert.equal(rows[0].tx, null); // before the file
  assert.equal(rows[1].tx, 5);
  assert.deepEqual(rows[1].phenomena, ["ML"]);
  assert.deepEqual(rows[2].phenomena, ["BO", "DE"]);
  assert.equal(rows[2].r, 2.5);
  assert.equal(rows[2].tx, null); // missing value
  assert.deepEqual(rows[3].flags, { r: "T" });
  assert.equal(rows[3].unchecked, true);
  assert.equal(rows[4].r, null); // after the file's last day
});

test("day length", () => {
  assert.ok(Math.abs(dayLength(PRAHA, "2026-06-21") - 16.3) < 0.2);
  assert.ok(Math.abs(dayLength(PRAHA, "2026-12-21") - 8.1) < 0.2);
  assert.ok(Math.abs(dayLength(0, "2026-03-20") - 12.1) < 0.2);
});

test("the observed symbol: sky from the sunshine", () => {
  // 16.3 h of day at midsummer
  assert.equal(daySymbol(row({ day: "2026-06-21", r: 0, ssv: 14 }), PRAHA), "clear");
  assert.equal(daySymbol(row({ day: "2026-06-21", r: 0, ssv: 6 }), PRAHA), "partly");
  assert.equal(daySymbol(row({ day: "2026-06-21", r: 0, ssv: 1 }), PRAHA), "cloudy");
  // 2 h of sun in December is a quarter of the day: partly cloudy
  assert.equal(daySymbol(row({ day: "2026-12-21", r: 0, ssv: 2.1 }), PRAHA), "partly");
  // no sunshine measured: the daytime cloud cover (octas), as the forecast symbols
  assert.equal(daySymbol(row({ r: 0, cloud: 1 }), PRAHA), "clear");
  assert.equal(daySymbol(row({ r: 0, cloud: 4 }), PRAHA), "partly");
  assert.equal(daySymbol(row({ r: 0, cloud: 7.5 }), PRAHA), "cloudy");
  // neither: no symbol for a dry day (a rain gauge)
  assert.equal(daySymbol(row({ r: 0 }), PRAHA), null);
  assert.equal(daySymbol(row({}), PRAHA), null);
});

test("the observed symbol: precipitation", () => {
  assert.equal(daySymbol(row({ r: 4, ssv: 0.5, day: "2026-07-01" }), PRAHA), "rain");
  assert.equal(daySymbol(row({ r: 4, ssv: 9, day: "2026-07-01" }), PRAHA), "showers"); // rain and sun
  assert.equal(daySymbol(row({ r: 0.4, ssv: 0.5 }), PRAHA), "cloudy"); // below WET_MM
  assert.equal(daySymbol(row({ r: 4 }), PRAHA), "rain"); // a rain gauge: wet days only
  // what the observer recorded comes first
  assert.equal(precipitationKind(row({ r: 3, phenomena: ["SN"], tx: 5, tn: 1 })), "snow");
  assert.equal(precipitationKind(row({ r: 3, phenomena: ["DE", "SN"] })), "sleet");
  assert.equal(precipitationKind(row({ r: 3, phenomena: ["DE"], t: -1 })), "rain");
  assert.equal(precipitationKind(row({ r: 3, phenomena: ["MS"] })), "rain"); // freezing rain
  // then new snow, then the temperature
  assert.equal(precipitationKind(row({ r: 3, sno: 4, t: 3 })), "snow");
  assert.equal(precipitationKind(row({ r: 3, t: 0.2 })), "snow");
  assert.equal(precipitationKind(row({ r: 3, tx: 3, tn: 0 })), "sleet");
  assert.equal(precipitationKind(row({ r: 3, t: 8 })), "rain");
  assert.equal(precipitationKind(row({ r: 3 })), "rain");
  // snow never shows as showers
  assert.equal(daySymbol(row({ day: "2026-01-10", r: 5, sno: 6, ssv: 6 }), PRAHA), "snow");
});

test("columns: only what the station measured in the period", () => {
  const main = [
    row({ tx: 20, tn: 10, r: 0, sce: 0, ssv: 8, g: 9, phenomena: ["RO"] }),
    row({ tx: 21, tn: 9, r: 3, sce: 0, ssv: 2, g: 14, phenomena: ["BO", "DE"] }),
  ];
  assert.deepEqual(columnsFor(main, PRAHA), ["symbol", "temperature", "precipitation", "sunshine", "gust", "phenomena"]);
  // no snow column in summer, but one in winter
  const winter = [row({ day: "2026-01-05", tx: -2, tn: -8, r: 1, sno: 2, sce: 5, ssv: 0 })];
  assert.deepEqual(columnsFor(winter, PRAHA), ["symbol", "temperature", "precipitation", "snow", "sunshine"]);
  // a dusting flagged at 0 cm counts
  assert.ok(columnsFor([row({ r: 0, sce: 0, flags: { sce: "P" } })], PRAHA).includes("snow"));
  // a rain gauge: its precipitation, and symbols only where it rained
  const gauge = [row({ r: 0, sce: 0 }), row({ r: 6.2, sce: 0 })];
  assert.deepEqual(columnsFor(gauge, PRAHA), ["symbol", "precipitation"]);
  assert.deepEqual(columnsFor([row({ r: 0 }), row({ r: 0.1 })], PRAHA), ["precipitation"]);
  assert.deepEqual(columnsFor([row({})], PRAHA), []);
});

test("period summary", () => {
  const rows = [
    row({ day: "2026-01-01", tx: 2, tn: -3, t: -0.5, r: 0, ssv: 1.5, g: 8, sce: 3 }),
    row({ day: "2026-01-02", tx: -1, tn: -6.4, t: -3, r: 4.2, ssv: 0, g: 15.5, sce: 6, phenomena: ["SN"] }),
    row({ day: "2026-01-03", tx: 4, tn: 0.5, t: 2, r: 1, ssv: null, g: 6, sce: 0, phenomena: ["BO"] }),
    row({ day: "2026-01-04" }), // nothing measured
  ];
  const s = periodSummary(rows);
  assert.equal(s.days, 4);
  assert.equal(s.count.t, 3);
  assert.equal(s.count.ssv, 2);
  assert.equal(s.tmean, -0.5);
  assert.deepEqual(s.tmax, { value: 4, day: "2026-01-03" });
  assert.deepEqual(s.tmin, { value: -6.4, day: "2026-01-02" });
  assert.equal(s.precipitation, 5.2);
  assert.equal(s.wetDays, 2);
  assert.equal(s.frostDays, 2);
  assert.equal(s.iceDays, 1);
  assert.equal(s.summerDays, 0);
  assert.equal(s.sunshine, 1.5);
  assert.deepEqual(s.gust, { value: 15.5, day: "2026-01-02" });
  assert.equal(s.snowDays, 2);
  assert.deepEqual(s.snowMax, { value: 6, day: "2026-01-02" });
  assert.equal(s.storms, 1);
  // a rain gauge: no temperatures, no phenomena
  const gauge = periodSummary([row({ r: 0 }), row({ r: 12.3 })]);
  assert.equal(gauge.tmean, null);
  assert.equal(gauge.tmax, null);
  assert.equal(gauge.frostDays, null);
  assert.equal(gauge.sunshine, null);
  assert.equal(gauge.storms, null);
  assert.equal(gauge.precipitation, 12.3);
  assert.equal(gauge.wetDays, 1);
});

test("Prague days and the course of a day", () => {
  // summer time (UTC+2) and winter time (UTC+1), and the day the clocks change
  assert.equal(new Date(pragueDayBounds("2026-07-01").start).toISOString(), "2026-06-30T22:00:00.000Z");
  assert.equal(new Date(pragueDayBounds("2026-01-01").start).toISOString(), "2025-12-31T23:00:00.000Z");
  const change = pragueDayBounds("2026-10-25");
  assert.equal((change.end - change.start) / 3_600_000, 25);
  // 10-minute values (stamped at the end of their 10 minutes) from 2026-10-14 00:00 UTC
  const n = 3 * 144;
  const doc = {
    series: {
      "10min": {
        start: "2026-10-14T00:00:00Z",
        step: "10min",
        values: { T: Array.from({ length: n }, (_, i) => i), SRA10M: Array(n).fill(0), F: Array(n).fill(2), Fmax: Array(n).fill(5) },
      },
      "1hour": {
        start: "2026-09-17T00:00:00Z",
        step: "1h",
        values: { T: Array.from({ length: 30 * 24 }, () => 10), SRA1H: Array(30 * 24).fill(0.2) },
      },
    },
  };
  const course = dayCourse(doc, "2026-10-15");
  assert.equal(course.view, "10min");
  assert.equal(course.temperature.length, 144);
  // 00:10 local (22:10 UTC the day before) is the first, 24:00 the last
  assert.equal(course.temperature[0].time.toISOString(), "2026-10-14T22:10:00.000Z");
  assert.equal(course.temperature.at(-1).time.toISOString(), "2026-10-15T22:00:00.000Z");
  // the 10-minute series starts within 14 October local: that day hourly, whole
  assert.equal(dayCourse(doc, "2026-10-14").view, "1hour");
  assert.equal(dayCourse(doc, "2026-09-20").view, "1hour");
  assert.equal(dayCourse(doc, "2026-09-20").precipitation.length, 24);
  assert.deepEqual(dayCourse(doc, "2026-09-20").wind, []);
  assert.equal(dayCourse(doc, "2025-07-01"), null); // daily values only
});

test("daytime cloud cover from the hourly series", () => {
  // 2026-07-01 00:00 UTC = 02:00 Prague; octas 2 all day, 9 (sky obscured) ignored
  const values = Array.from({ length: 48 }, (_, i) => (i === 10 ? 9 : 2));
  const cloud = daytimeCloud({ start: "2026-07-01T00:00:00Z", step: "1h", values: { N: values } });
  assert.equal(cloud.get("2026-07-01"), 2);
  assert.equal(daytimeCloud({ start: "2026-07-01T00:00:00Z", step: "1h", values: {} }).size, 0);
});

test("diary files, gzipped or not", async () => {
  const doc = { start: "2020-01-01", days: 1, values: { r: [1.5] } };
  const text = JSON.stringify(doc);
  assert.deepEqual(await parseDiaryFile(gzipSync(text)), doc);
  assert.deepEqual(await parseDiaryFile(new TextEncoder().encode(text).buffer), doc);
});

test("view and day from the query", () => {
  assert.deepEqual(parseDiaryQuery("?view=month&day=2010-07-14"), { view: "month", day: "2010-07-14" });
  assert.deepEqual(parseDiaryQuery("?view=year&day=14.7.2010"), { view: null, day: null });
  assert.deepEqual(parseDiaryQuery(""), { view: null, day: null });
});

test("the symbol of a part of the day uses that part's daylight", () => {
  const row = { day: "2026-10-16", r: 0, ssv: 3.8, cloud: null, phenomena: [], sno: null, tx: 13, tn: 9, t: null };
  // 3.8 h of a 6-hour daylit afternoon: clear; of the whole day's ~10.7 h: partly cloudy
  assert.equal(daySymbol(row, null, 6), "clear");
  assert.equal(daySymbol(row, 50.5), "partly");
  // no daylight (night): the sky from the cloud cover, or nothing
  assert.equal(daySymbol({ ...row, ssv: null, cloud: 7 }, null, 0), "cloudy");
  assert.equal(daySymbol({ ...row, ssv: null }, null, 0), null);
});
