import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  aiStatus, aiVerdict, bestModel, dailyRows, defaultSeries, headline, parseView, regionGroups, tableRows,
} from "./compare-ai.js";

const entry = (aiVs, clear = true) => ({
  clear_winner: clear,
  date_list: ["2026-10-01", "2026-10-02"],
  series: [
    { id: "meteoverdict_ai", kind: "ai", mae: 0.9, tied: false, daily: [0.8, 1.0], vs_outlook: aiVs },
    { id: "combined", kind: "outlook", mae: 1.0, tied: true, daily: [1, 1.1], vs_outlook: null },
    { id: "dwd_icon_d2", kind: "model", mae: 1.2, tied: false, daily: [1.2, null], vs_outlook: { diff: 0.2, low: 0.1, high: 0.3, p: 0.001 } },
  ],
});

describe("aiVerdict", () => {
  it("is better only with the interval below 0 and a significant test", () => {
    assert.equal(aiVerdict(entry({ diff: -0.1, low: -0.15, high: -0.05, p: 0.001 })).verdict, "better");
    assert.equal(aiVerdict(entry({ diff: -0.1, low: -0.15, high: -0.05, p: 0.2 })).verdict, "same");
    assert.equal(aiVerdict(entry({ diff: -0.1, low: -0.2, high: 0.01, p: 0.01 })).verdict, "same");
    assert.equal(aiVerdict(entry({ diff: 0.1, low: 0.05, high: 0.2, p: 0.01 })).verdict, "worse");
  });
  it("is null without the AI or the comparison", () => {
    assert.equal(aiVerdict({ series: [{ id: "x", kind: "model" }] }), null);
    assert.equal(aiVerdict(entry(null)), null);
  });
});

describe("ranking helpers", () => {
  const e = entry({ diff: -0.1, low: -0.15, high: -0.05, p: 0.001 }, false);
  it("marks the leaders and the headline", () => {
    assert.deepEqual(tableRows(e).map((r) => r.leader), [true, true, false]);
    assert.equal(headline(e).kind, "none");
    assert.equal(headline(e).leaders.length, 2);
    assert.equal(headline({ ...e, clear_winner: true }).kind, "winner");
  });
  it("finds the best model and the default series", () => {
    assert.equal(bestModel(e).id, "dwd_icon_d2");
    assert.deepEqual(defaultSeries(e), ["meteoverdict_ai", "combined", "dwd_icon_d2"]);
  });
  it("skips missing days in the daily rows", () => {
    assert.equal(dailyRows(e, ["dwd_icon_d2"]).length, 1);
  });
});

describe("status and view", () => {
  it("is verified only with enough live days", () => {
    assert.equal(aiStatus({ days: 0, measured_hours: 0 }).verified, false);
    assert.equal(aiStatus({ days: 28, measured_hours: 700 }).verified, true);
  });
  it("parses the view and falls back", () => {
    assert.deepEqual(parseView("wind_speed_10m.3.live.CZ0100", { CZ0100: 1 }), {
      variable: "wind_speed_10m", lead: 3, sample: "live", region: "CZ0100",
    });
    assert.deepEqual(parseView("x.9.y.zz", { cz: 1 }), { variable: "temperature_2m", lead: 1, sample: "validation", region: "cz" });
  });
  it("groups the regions by level", () => {
    const g = regionGroups({ regions: { cz: ["cz", "Česko"], CZ010: ["kraj", "Praha"], CZ0201: ["okres", "Benešov"] } });
    assert.deepEqual(g, { cz: true, kraje: [["CZ010", "Praha"]], okresy: [["CZ0201", "Benešov"]] });
  });
});
