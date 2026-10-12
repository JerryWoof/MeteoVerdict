// Why is a model the best in a region? Facts for the okres panel of the score map,
// computed from the published scores of that region (all lead days of one variable
// and window) and, for temperature, the four synoptic hours.

import { rankingTable } from "./compare.js";

export const HOURS = ["00", "06", "12", "18"];
// fewer scored days than this: the ranking is preliminary
export const FEW_DAYS = 30;

const isModel = (r) => r.model !== "blend";

/** The model with the smallest MAE among rows (ranked or not), or null. */
function lowest(rows) {
  const models = rows.filter((r) => isModel(r) && r.mae != null);
  if (models.length === 0) return null;
  return models.reduce((a, b) => (b.mae < a.mae ? b : a));
}

const median = (values) => {
  const v = values.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (v.length === 0) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
};

/**
 * Facts about a region at one lead day, or null without a ranked winner.
 * `rows`: score rows of the region's level (all lead days); `hourRows`: optional
 * {"00": rows, …} of the synoptic-hour temperature files.
 */
export function explainRegion(rows, region, leadDay, hourRows = null) {
  const table = rankingTable(rows, leadDay, region);
  const ranked = table.filter((r) => r.rank != null);
  const winner = ranked[0];
  if (!winner || winner.rank !== 1) return null;
  const runnerUp = ranked[1] ?? null;
  const blend = table.find((r) => r.model === "blend") ?? null;
  const others = ranked.slice(1);
  const here = rows.filter((r) => r.region === region);

  // big misses: RMSE/MAE grows with the share of large errors
  const ratio = (r) => (r.mae > 0 && r.rmse != null ? r.rmse / r.mae : null);
  const othersRatio = median(others.map(ratio));
  const othersBias = median(others.map((r) => (r.bias == null ? null : Math.abs(r.bias))));

  const byLead = [...new Set(here.map((r) => r.lead_day))]
    .sort((a, b) => a - b)
    .map((lead) => {
      const best = here.find((r) => r.lead_day === lead && r.rank === 1) ?? lowest(here.filter((r) => r.lead_day === lead));
      return best ? { lead, model: best.model, mae: best.mae } : null;
    })
    .filter(Boolean);

  const byHour = hourRows
    ? HOURS.map((hour) => {
        const best = lowest((hourRows[hour] ?? []).filter((r) => r.region === region && r.lead_day === leadDay));
        return best ? { hour, model: best.model, mae: best.mae } : null;
      }).filter(Boolean)
    : [];

  return {
    name: here[0]?.region_name ?? region,
    winner: { model: winner.model, mae: winner.mae, bias: winner.bias, rmse: winner.rmse, skill: winner.skill },
    runnerUp: runnerUp
      ? { model: runnerUp.model, mae: runnerUp.mae, diff: runnerUp.diff, ci: runnerUp.ci, tied: runnerUp.tied }
      : null,
    tied: others.filter((r) => r.tied).map((r) => r.model),
    clear: others.length > 0 && !others.some((r) => r.tied),
    blend: blend ? { mae: blend.mae, beatsWinner: blend.mae < winner.mae } : null,
    bias: { winner: winner.bias, othersAbs: othersBias },
    misses: { winner: ratio(winner), others: othersRatio },
    byLead,
    byHour,
    basis: { stations: winner.stations, borrowed: winner.borrowed ?? 0, days: winner.days },
    preliminary: (winner.days ?? 0) < FEW_DAYS,
    table,
  };
}

/**
 * The reasons as i18n keys with parameters, in the order they are shown. `fmt` formats
 * a number with the variable's unit.
 */
export function reasons(facts, fmt) {
  const out = [];
  const w = facts.winner;
  if (facts.runnerUp) {
    if (facts.clear) out.push({ key: "why.clear", params: { diff: fmt(facts.runnerUp.diff) } });
    else out.push({ key: "why.tie", params: { n: facts.tied.length } });
  }
  if (w.skill != null) {
    const pct = Math.round(Math.abs(w.skill) * 100);
    out.push({ key: w.skill >= 0 ? "why.skill" : "why.skillWorse", params: { pct } });
  }
  const { winner: bias, othersAbs } = facts.bias;
  if (bias != null && othersAbs != null) {
    if (Math.abs(bias) < 0.6 * othersAbs) {
      out.push({ key: "why.bias", params: { bias: fmt(Math.abs(bias)), others: fmt(othersAbs) } });
    } else if (Math.abs(bias) >= 0.5 * w.mae) {
      out.push({ key: bias > 0 ? "why.biasHigh" : "why.biasLow", params: { bias: fmt(Math.abs(bias)) } });
    }
  }
  const { winner: ratio, others } = facts.misses;
  if (ratio != null && others != null && ratio < others - 0.05) {
    out.push({ key: "why.misses", params: {} });
  }
  const leadWins = facts.byLead.filter((l) => l.model === w.model).length;
  if (facts.byLead.length > 1) {
    out.push({
      key: leadWins === facts.byLead.length ? "why.allLeads" : "why.someLeads",
      params: { n: leadWins, of: facts.byLead.length },
    });
  }
  return out;
}
