import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { records } from "./data.js";
import { HOURS, explainRegion, reasons } from "./explain.js";

const load = (name) => records(JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url))));
const TEMP = load("scores-90d-okres-temperature_2m.json");
const RAIN = load("scores-90d-okres-precipitation_24h.json");
const BY_HOUR = Object.fromEntries(HOURS.map((h) => [h, load(`scores-90d-okres-temperature_2m_${h}utc.json`)]));
const fmt = (v) => v.toFixed(2);

test("facts for Benešov's temperature: winner, runner-up, basis", () => {
  const f = explainRegion(TEMP, "CZ0201", 1, BY_HOUR);
  const d1 = TEMP.filter((r) => r.region === "CZ0201" && r.lead_day === 1);
  const best = d1.find((r) => r.rank === 1);
  assert.equal(f.name, "Benešov");
  assert.equal(f.winner.model, best.model);
  assert.equal(f.runnerUp.model, d1.find((r) => r.rank === 2).model);
  assert.ok(f.runnerUp.diff >= 0);
  assert.equal(f.basis.days, best.days);
  assert.equal(f.preliminary, best.days < 30);
  assert.equal(f.clear, Boolean(best.clear_winner));
});

test("winners by lead day and by synoptic hour", () => {
  const f = explainRegion(TEMP, "CZ0201", 1, BY_HOUR);
  assert.deepEqual(f.byLead.map((l) => l.lead), [1, 2, 3, 4, 5]);
  for (const { lead, model } of f.byLead) {
    assert.equal(model, TEMP.find((r) => r.region === "CZ0201" && r.lead_day === lead && r.rank === 1).model);
  }
  assert.deepEqual(f.byHour.map((h) => h.hour), HOURS);
  for (const { hour, model, mae } of f.byHour) {
    const rows = BY_HOUR[hour].filter((r) => r.region === "CZ0201" && r.lead_day === 1 && r.model !== "blend");
    assert.equal(mae, Math.min(...rows.map((r) => r.mae)));
    assert.ok(rows.some((r) => r.model === model && r.mae === mae));
  }
  assert.deepEqual(explainRegion(TEMP, "CZ0201", 1).byHour, []); // only with the hour files
});

test("reasons are i18n keys with parameters, consistent with the facts", () => {
  const f = explainRegion(RAIN, "CZ0423", 1);
  const keys = reasons(f, fmt).map((r) => r.key);
  assert.ok(keys.includes(f.clear ? "why.clear" : "why.tie"));
  assert.ok(keys.includes(f.winner.skill >= 0 ? "why.skill" : "why.skillWorse"));
  const leads = reasons(f, fmt).find((r) => r.key === "why.allLeads" || r.key === "why.someLeads");
  assert.equal(leads.params.of, f.byLead.length);
  assert.equal(explainRegion(RAIN, "CZ9999", 1), null);
});

test("bias and big misses decide their reasons", () => {
  const rows = [
    { region: "X", region_name: "X", lead_day: 1, model: "a", mae: 1.0, bias: 0.05, rmse: 1.2, rank: 1, days: 40, stations: 3 },
    { region: "X", region_name: "X", lead_day: 1, model: "b", mae: 1.3, bias: 0.9, rmse: 2.0, rank: 2, diff_ci_low: 0.1, diff_ci_high: 0.5, days: 40, stations: 3 },
    { region: "X", region_name: "X", lead_day: 1, model: "c", mae: 1.4, bias: -0.8, rmse: 2.1, rank: 3, diff_ci_low: 0.2, diff_ci_high: 0.6, days: 40, stations: 3 },
    { region: "X", region_name: "X", lead_day: 1, model: "blend", mae: 1.1, bias: 0.1, rmse: 1.4, days: 40, stations: 3 },
  ];
  const f = explainRegion(rows, "X", 1);
  assert.equal(f.clear, true);
  assert.equal(f.preliminary, false);
  const r = Object.fromEntries(reasons(f, fmt).map((x) => [x.key, x.params]));
  assert.deepEqual(r["why.clear"], { diff: "0.30" });
  assert.deepEqual(r["why.bias"], { bias: "0.05", others: "0.85" });
  assert.ok("why.misses" in r);
  assert.deepEqual(r["why.skill"], { pct: 9 });
  // a winner that is itself far off on average
  rows[0].bias = 0.8;
  const r2 = reasons(explainRegion(rows, "X", 1), fmt).map((x) => x.key);
  assert.ok(r2.includes("why.biasHigh"));
});
