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

/** The last `days` calendar days up to and including `to` ("YYYY-MM-DD"), as the first of them. */
export function windowStart(to, days) {
  const d = new Date(`${to}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - (days - 1));
  return d.toISOString().slice(0, 10);
}

/**
 * The period's entry of one region and lead: with `week` = {from, to} the live file's daily
 * MAEs of exactly those days (every series of an entry shares its dates, stations and hours,
 * so the models and the AI stand on the same sample), else the entry as the engine wrote it.
 * Null when a series has no daily values or fewer than `minDays` of the period's days remain.
 */
export function periodEntry(entry, week, minDays = 4) {
  if (!week) return entry;
  const dates = entry.date_list ?? [];
  const keep = dates.map((d, i) => (d >= week.from && d <= week.to ? i : -1)).filter((i) => i >= 0);
  if (keep.length < minDays) return null;
  const series = [];
  for (const s of entry.series) {
    const daily = keep.map((i) => s.daily?.[i]);
    if (daily.some((v) => typeof v !== "number")) continue;
    series.push({ id: s.id, kind: s.kind, mae: daily.reduce((a, b) => a + b, 0) / daily.length });
  }
  series.sort((a, b) => a.mae - b.mae);
  // the ranking is a short sample on purpose: no interval, no probability of being best
  return { stations: entry.stations, days: keep.length, small_sample: false, series };
}

/**
 * One region's file → rows by "variable" (the entries' "variable/lead" keys): score rows of the
 * ranking format, best first; the mean of all models is listed unranked. `minStations` is the
 * map's own rule for a region to count (meta.json min_stations); `week` = {from, to} ranks the
 * live file on those days only (periodEntry).
 */
export function regionRows(doc, minStations = 3, week = null) {
  const out = new Map();
  for (const [key, whole] of Object.entries(doc?.entries ?? {})) {
    const entry = whole && periodEntry(whole, week);
    if (!entry) continue;
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
