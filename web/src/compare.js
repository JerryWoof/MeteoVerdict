// The model comparison page: ranking for Czechia, a kraj or an okres, the interval of
// each model's difference to the best, MAE by lead day, and bias by elevation class.

const ELEVATION_ORDER = ["lowland", "upland", "mountain"];

/** The level of a region code: "cz", a kraj (CZ064) or an okres (CZ0642, CZ020A). */
export function levelOf(region) {
  if (region === "cz") return "cz";
  return region.length === 5 ? "kraj" : "okres";
}

/**
 * Rows of the ranking table for a region at one lead day: ranked models first (by
 * rank), the mean of all models after them, each with its MAE difference to the best,
 * the interval of that difference and its skill against the mean of all models
 * (1 − MAE / MAE of the mean: positive = better than the mean).
 */
export function rankingTable(rows, leadDay, region = "cz") {
  const here = rows.filter((r) => r.lead_day === leadDay && r.region === region);
  const best = here.find((r) => r.rank === 1);
  const blend = here.find((r) => r.model === "blend");
  const order = (r) => (r.rank == null ? Number.POSITIVE_INFINITY : r.rank);
  return here
    .slice()
    .sort((a, b) => order(a) - order(b) || a.mae - b.mae)
    .map((r) => ({
      model: r.model,
      rank: r.rank,
      mae: r.mae,
      bias: r.bias,
      rmse: r.rmse,
      diff: best ? r.mae - best.mae : null,
      ci: r.diff_ci_low == null ? null : [r.diff_ci_low, r.diff_ci_high],
      tied: Boolean(r.tied_with_best),
      skill: blend && r.model !== "blend" && blend.mae > 0 ? 1 - r.mae / blend.mae : null,
      stations: r.stations,
      borrowed: r.borrowed ?? 0,
      days: r.days,
      ets: r.ets_0p1 ?? null,
      pod: r.pod_0p1 ?? null,
      far: r.far_0p1 ?? null,
      ets5: r.ets_5 ?? null,
    }));
}

/**
 * The interval chart: per ranked model its MAE difference to the best and the 95 %
 * interval; the best model is the zero line. Models whose interval reaches 0 are tied.
 */
export function intervalRows(table) {
  return table
    .filter((r) => r.rank != null && r.ci)
    .map((r) => ({
      model: r.model,
      diff: r.diff,
      low: r.rank === 1 ? 0 : r.ci[0],
      high: r.rank === 1 ? 0 : r.ci[1],
      tied: r.tied || r.rank === 1,
    }));
}

/** MAE of every model (and the mean of all) by lead day in a region: [{model, lead_day, mae}]. */
export function maeByLead(rows, region = "cz") {
  return rows
    .filter((r) => r.region === region && r.mae != null)
    .map((r) => ({ model: r.model, lead_day: r.lead_day, mae: r.mae }))
    .sort((a, b) => a.model.localeCompare(b.model) || a.lead_day - b.lead_day);
}

/** Summary of a region at a lead day: best model, whether it is a clear winner, the
 * number of models tied with it, stations (borrowed) and days. */
export function regionSummary(rows, leadDay, region = "cz") {
  const here = rows.filter((r) => r.lead_day === leadDay && r.region === region);
  const best = here.find((r) => r.rank === 1);
  if (!best) return null;
  return {
    name: best.region_name,
    model: best.model,
    mae: best.mae,
    clear: Boolean(best.clear_winner),
    tied: here.filter((r) => r.tied_with_best && r.rank != null && r.rank > 1).length,
    stations: best.stations,
    borrowed: best.borrowed ?? 0,
    days: best.days,
    enough: best.enough_stations !== false,
  };
}

/** The regions of a score file as [{code, name}] sorted by name (Czech collation). */
export function regionList(rows) {
  const names = new Map(rows.map((r) => [r.region, r.region_name]));
  return [...names]
    .map(([code, name]) => ({ code, name }))
    .sort((a, b) => a.name.localeCompare(b.name, "cs"));
}

/** [{elevation, model, bias}] at one lead day, in elevation order, without the blend. */
export function biasByElevation(rows, leadDay) {
  return rows
    .filter((r) => r.lead_day === leadDay && r.model !== "blend" && r.bias != null)
    .filter((r) => ELEVATION_ORDER.includes(r.region))
    .sort((a, b) => ELEVATION_ORDER.indexOf(a.region) - ELEVATION_ORDER.indexOf(b.region))
    .map((r) => ({ elevation: r.region, model: r.model, bias: r.bias }));
}

/** "1.23", "+0.45", "–" */
export function fmt(value, signed = false) {
  if (value == null || Number.isNaN(value)) return "–";
  const text = value.toFixed(2);
  return signed && value > 0 ? `+${text}` : text;
}
