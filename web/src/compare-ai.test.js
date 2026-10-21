import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  aiStatus, aiVerdict, defaultOpponent, pairVersus, threeWayPBest, aiVersus, availableModels, opponentSeries, bestModel, compareRows, dailyRows, defaultSeries, parseView, regionGroups,
} from "./compare-ai.js";

const entry = (aiVs, clear = true) => ({
  clear_winner: clear,
  date_list: ["2026-10-01", "2026-10-02"],
  series: [
    { id: "meteoverdict_ai", kind: "ai", mae: 0.9, tied: false, daily: [0.8, 1.0], vs_outlook: aiVs },
    { id: "combined", kind: "outlook", mae: 1.0, tied: true, daily: [1, 1.1], vs_outlook: null },
    { id: "dwd_icon_d2", kind: "model", mae: 1.2, tied: false, daily: [1.2, null], vs_outlook: { diff: 0.2, low: 0.1, high: 0.3, p: 0.001 }, vs_ai: { diff: 0.3, low: 0.2, high: 0.4, p: 0.001, p_lower: 0 } },
    { id: "icon_eu", kind: "model", mae: 1.0, tied: false, daily: [1, 1], vs_outlook: null, vs_ai: { diff: 0.1, low: -0.05, high: 0.25, p: 0.2, p_lower: 0.1 } },
    { id: "old", kind: "model", mae: 1.3, tied: false, daily: [1, 1], vs_outlook: null },
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

describe("the AI against a chosen opponent", () => {
  const e = entry({ diff: -0.1, low: -0.15, high: -0.05, p: 0.001, p_lower: 0.99 });
  it("uses the blend's interval for the blend and flips vs_ai for a model", () => {
    assert.equal(aiVersus(e, "outlook").verdict, "better");
    const m = aiVersus(e, "dwd_icon_d2");
    assert.equal(m.verdict, "better");
    assert.ok(Math.abs(m.low + 0.4) < 1e-9 && Math.abs(m.high + 0.2) < 1e-9 && m.pAiBetter === 1);
  });
  it("says no clear winner when the interval crosses zero", () => {
    const m = aiVersus(e, "icon_eu");
    assert.equal(m.verdict, "same");
    assert.equal(m.pAiBetter, 0.9);
  });
  it("gives only the difference without an interval, and null for a missing opponent", () => {
    const m = aiVersus(e, "old");
    assert.equal(m.verdict, null);
    assert.ok(Math.abs(m.diff - (0.9 - 1.3)) < 1e-9);
    assert.equal(aiVersus(e, "nope"), null);
    assert.equal(opponentSeries(e, "best").id, "dwd_icon_d2");
    assert.deepEqual(availableModels(e), ["dwd_icon_d2", "icon_eu", "old"]);
  });
});

describe("the three series", () => {
  const e = entry({ diff: -0.1, low: -0.15, high: -0.05, p: 0.001, p_lower: 0.99 });
  it("compares any two of AI, blend and model, in both directions", () => {
    const a = pairVersus(e, "ai", "dwd_icon_d2");
    assert.equal(a.verdict, "better");
    const b = pairVersus(e, "dwd_icon_d2", "ai");
    assert.equal(b.verdict, "worse");
    // the blend against the model: the file has model - blend = +0.2, so blend - model = -0.2
    const c = pairVersus(e, "outlook", "dwd_icon_d2");
    assert.ok(Math.abs(c.diff + 0.3) < 1e-9 || c.diff < 0);
    assert.equal(c.verdict, "better");
    assert.equal(pairVersus(e, "ai", "outlook").verdict, "better");
    assert.equal(pairVersus(e, "outlook", "ai").verdict, "worse");
    assert.equal(pairVersus(e, "ai", "ai"), null);
  });
  it("picks the best model as the default and gives shares that add up to 1", () => {
    assert.equal(defaultOpponent(e), "dwd_icon_d2");
    const e2 = { ...e, series: e.series.map((s) => ({ ...s, daily: [1, 1, 1, 1, 1, 1].map((x, i) => x + (s.kind === "ai" ? -0.2 : s.kind === "outlook" ? 0 : 0.2) + i * 0.01) })) };
    const shares = threeWayPBest(e2, "dwd_icon_d2");
    assert.ok(Math.abs(shares.reduce((x, y) => x + y, 0) - 1) < 1e-9);
    assert.equal(shares[0], 1);
  });
});

describe("comparison rows", () => {
  const e = entry({ diff: -0.1, low: -0.15, high: -0.05, p: 0.001 }, false);
  it("are the AI, the blend, the mean and the best model, each against the blend", () => {
    const rows = compareRows(e);
    assert.deepEqual(rows.map((r) => r.id), ["meteoverdict_ai", "combined", "dwd_icon_d2"]);
    assert.equal(rows[0].relation.verdict, "better");
    assert.equal(rows[1].relation, null);
    assert.equal(rows[2].relation.verdict, "worse");
  });
  it("finds the best model and the default series", () => {
    assert.equal(bestModel(e).id, "dwd_icon_d2");
    assert.deepEqual(defaultSeries(e), ["meteoverdict_ai", "combined", "dwd_icon_d2"]);
  });
  it("keeps missing days as nulls so the line breaks", () => {
    assert.deepEqual(dailyRows(e, ["dwd_icon_d2"]).map((r) => r.mae), [1.2, null]);
  });
});

describe("status and view", () => {
  it("is verified only with enough live days", () => {
    assert.equal(aiStatus({ days: 0, measured_hours: 0 }).verified, false);
    assert.equal(aiStatus({ days: 28, measured_hours: 700 }).verified, true);
  });
  it("parses the view and falls back", () => {
    assert.deepEqual(parseView("wind_speed_10m.3.live.CZ0100.dwd_icon_d2", { CZ0100: 1 }), {
      variable: "wind_speed_10m", lead: 3, sample: "live", region: "CZ0100", opponent: "dwd_icon_d2",
    });
    assert.deepEqual(parseView("x.9.y.zz", { cz: 1 }), { variable: "temperature_2m", lead: 1, sample: "validation", region: "cz", opponent: "" });
    // old links naming our blend, the mean or "best" fall back to the default model
    for (const old of ["outlook", "mean", "best", "blend", "combined", "meteoverdict_ai"]) assert.equal(parseView(`temperature_2m.1.validation.cz.${old}`, { cz: 1 }).opponent, "");
  });
  it("groups the regions by level", () => {
    const g = regionGroups({ regions: { cz: ["cz", "Česko", true], CZ010: ["kraj", "Praha", true], CZ0201: ["okres", "Benešov", false] } });
    assert.deepEqual(g, { cz: true, kraje: [["CZ010", "Praha"]], okresy: [] });
  });
});

import { rankingTable } from "./compare.js";

describe("ranking table", () => {
  it("carries p_best (null in older files)", () => {
    const rows = [
      { region: "cz", lead_day: 1, model: "a", rank: 1, mae: 1, p_best: 0.7 },
      { region: "cz", lead_day: 1, model: "b", rank: 2, mae: 1.1 },
    ];
    assert.deepEqual(rankingTable(rows, 1).map((r) => r.pBest), [0.7, null]);
  });
});
