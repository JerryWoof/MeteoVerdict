import assert from "node:assert/strict";
import { test } from "node:test";

import { dayLength, daySymbol, precipitationKind } from "./observed-symbol.js";

const PRAHA = 50.1;

/** A row as the symbol takes it. */
const row = (fields = {}) => ({
  day: "2026-07-01", tx: null, tn: null, t: null, r: null, sno: null, sce: null, ssv: null, g: null,
  phenomena: [], flags: {}, unchecked: false, ...fields,
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


test("the symbol of a part of the day uses that part's daylight", () => {
  const row = { day: "2026-10-16", r: 0, ssv: 3.8, cloud: null, phenomena: [], sno: null, tx: 13, tn: 9, t: null };
  // 3.8 h of a 6-hour daylit afternoon: clear; of the whole day's ~10.7 h: partly cloudy
  assert.equal(daySymbol(row, null, 6), "clear");
  assert.equal(daySymbol(row, 50.5), "partly");
  // no daylight (night): the sky from the cloud cover, or nothing
  assert.equal(daySymbol({ ...row, ssv: null, cloud: 7 }, null, 0), "cloudy");
  assert.equal(daySymbol({ ...row, ssv: null }, null, 0), null);
});
