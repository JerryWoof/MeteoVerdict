// "Include MeteoVerdict models" on the model comparison page: our own forecast (the Outlook,
// "combined") and MeteoVerdict AI ranked with the public models on the same station-days.
// The engine writes the same-sample files (ai.zip: fc/compare/<region>.json, one entry per
// variable and lead day with every series' MAE, interval and p_best); the build turns them into
// score files in the format of the other levels (scripts/build-mv-compare.mjs), so the map, its
// legend and the okres panel work on them unchanged.

export const MV_MODEL = "mv_model";
export const MV_AI = "mv_ai";
export const MV_COLUMNS = [
  "region", "region_name", "lead_day", "model", "stations", "days", "mae", "bias", "rmse", "rank",
  "diff_ci_low", "diff_ci_high", "tied_with_best", "p_best", "small_sample", "enough_stations", "borrowed", "short_record",
];

/** The model id of a series of the same-sample file: ours and the AI get the page's ids, the mean stays "blend". */
export function modelId(series) {
  if (series.kind === "outlook") return MV_MODEL;
  if (series.kind === "ai") return MV_AI;
  if (series.kind === "mean") return "blend";
  return series.id;
}

/**
 * One region's file → rows by "variable" (the entries' "variable/lead" keys): score rows of the
 * ranking format, best first; the mean of all models is listed unranked. `minStations` is the
 * map's own rule for a region to count (meta.json min_stations).
 */
export function regionRows(doc, minStations = 3) {
  const out = new Map();
  for (const [key, entry] of Object.entries(doc?.entries ?? {})) {
    const [variable, lead] = key.split("/");
    const leadDay = Number(lead);
    if (!variable || !Number.isInteger(leadDay) || !Array.isArray(entry?.series)) continue;
    const rows = out.get(variable) ?? [];
    let rank = 0;
    for (const s of entry.series) {
      if (typeof s?.mae !== "number") continue;
      const id = modelId(s);
      const ranked = id !== "blend";
      if (ranked) rank += 1;
      rows.push([
        doc.region, doc.name ?? doc.region, leadDay, id, entry.stations ?? null, entry.days ?? null, s.mae, null, null,
        ranked ? rank : null, s.low ?? null, s.high ?? null, Boolean(s.tied), s.p_best ?? null,
        Boolean(entry.small_sample), (entry.stations ?? 0) >= minStations, 0, false,
      ]);
    }
    out.set(variable, rows);
  }
  return out;
}
