import assert from "node:assert/strict";
import { test } from "node:test";

import { barRows, leadsOf, meanVerdict, monthLabel, winnerKind } from "./report.js";

const lead = {
  best: "a",
  tied_with_best: ["b"],
  clear_winner: false,
  models: [
    { model: "a", name: "A", mae: 1, bias: 0.1, short_record: false },
    { model: "b", name: "B", mae: 1.1, bias: 0, short_record: false },
    { model: "c", name: "C", mae: 2, bias: -1, short_record: false },
  ],
  mean_of_all: { ci_low: -0.1, ci_high: 0.1 },
};

test("monthLabel", () => {
  assert.equal(monthLabel("2026-09", "cs"), "září 2026");
  assert.equal(monthLabel("2026-09", "en"), "September 2026");
});

test("winnerKind and meanVerdict", () => {
  assert.equal(winnerKind(lead), "tie");
  assert.equal(winnerKind({ ...lead, clear_winner: true }), "clear");
  assert.equal(winnerKind({ best: null }), "none");
  assert.equal(meanVerdict(lead), "same");
  assert.equal(meanVerdict({ mean_of_all: { ci_low: -0.3, ci_high: -0.1 } }), "better");
  assert.equal(meanVerdict({ mean_of_all: { ci_low: 0.1, ci_high: 0.3 } }), "worse");
  assert.equal(meanVerdict({}), null);
});

test("barRows: shares, best and ties", () => {
  const rows = barRows(lead);
  assert.deepEqual(rows.map((r) => [r.model, r.best, r.tied]), [["a", true, false], ["b", false, true], ["c", false, false]]);
  assert.equal(rows[2].share, 1);
  assert.equal(rows[0].share, 0.5);
});

test("leadsOf: the leads every variable has", () => {
  const v = (...l) => ({ leads: Object.fromEntries(l.map((k) => [k, {}])) });
  const report = { variables: { temperature_2m: v("1", "2"), wind_speed_10m: v("1", "2", "3"), precipitation_24h: v("2", "1") } };
  assert.deepEqual(leadsOf(report), ["1", "2"]);
});
