// The model comparison page: national ranking and bias by elevation class.

const ELEVATION_ORDER = ["lowland", "upland", "mountain"];

/**
 * Rows of the national table at one lead day: ranked models first (by rank), the
 * blend after them, each with its MAE difference to the best model.
 */
export function rankingTable(rows, leadDay) {
  const here = rows.filter((r) => r.lead_day === leadDay && r.region === "cz");
  const best = here.find((r) => r.rank === 1);
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
      stations: r.stations,
      days: r.days,
    }));
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
