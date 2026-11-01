// What the model ranking helpers share (explain.js, chart.js): the level of a region, the
// ranking table of a region at one lead day, and the home model. The comparison page itself is gone.

/** The level of a region code: "cz", a kraj (CZ064) or an okres (CZ0642, CZ020A). */
export function levelOf(region) {
  if (region === "cz") return "cz";
  return region.length === 5 ? "kraj" : "okres";
}

/** A model the window leaves out of the comparison for too short a record (scores on
 * too few of its days, e.g. added recently): its own days only, not ranked. Score
 * files from before the rule have no `short_record`. */
export const isShort = (r) => Boolean(r.short_record);

/**
 * Rows of the ranking table for a region at one lead day: ranked models first (by
 * rank), the mean of all models after them, then the models with too short a record
 * (`short`), each with its MAE difference to the best, the interval of that difference
 * and its skill against the mean of all models (1 − MAE / MAE of the mean: positive =
 * better than the mean).
 */
export function rankingTable(rows, leadDay, region = "cz") {
  const here = rows.filter((r) => r.lead_day === leadDay && r.region === region);
  const best = here.find((r) => r.rank === 1);
  const blend = here.find((r) => r.model === "blend");
  const order = (r) => (isShort(r) ? 2 : r.rank == null ? 1 : 0);
  const rank = (r) => (r.rank == null ? Number.POSITIVE_INFINITY : r.rank);
  return here
    .slice()
    .sort((a, b) => order(a) - order(b) || rank(a) - rank(b) || a.mae - b.mae)
    .map((r) => ({
      model: r.model,
      rank: r.rank,
      mae: r.mae,
      bias: r.bias,
      rmse: r.rmse,
      diff: best ? r.mae - best.mae : null,
      ci: r.diff_ci_low == null ? null : [r.diff_ci_low, r.diff_ci_high],
      tied: Boolean(r.tied_with_best),
      pBest: r.p_best ?? null,
      short: isShort(r),
      coverage: r.coverage ?? null,
      skill: blend && r.model !== "blend" && blend.mae > 0 ? 1 - r.mae / blend.mae : null,
      stations: r.stations,
      borrowed: r.borrowed ?? 0,
      days: r.days,
      ets: r.ets_0p1 ?? null,
      pod: r.pod_0p1 ?? null,
      far: r.far_0p1 ?? null,
      ets5: r.ets_5 ?? null,
      // added in October 2026 (older files: null): event skill at 1 and 10 mm a day, and
      // the MAE once the model's usual bias at the station and hour is removed
      ets1: r.ets_1 ?? null,
      pod1: r.pod_1 ?? null,
      far1: r.far_1 ?? null,
      ets10: r.ets_10 ?? null,
      pod10: r.pod_10 ?? null,
      far10: r.far_10 ?? null,
      maeBc: r.mae_bc ?? null,
    }));
}

/** The model of our own country's weather service, always shown in the charts. */
export const HOME_MODEL = "chmi_aladin_cz_1km";
