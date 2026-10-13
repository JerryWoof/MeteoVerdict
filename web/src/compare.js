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

// --- run-based errors by lead hour (leads.json, written by `mvd leads`) -------------
// Every model from Open-Meteo's single runs; older files hold ALADIN from our archive
// only (with a region column). Both have the same columns and rows.

/** The leads.json variable for a page variable: hourly precipitation for the daily sums. */
export function leadHourVariable(variable) {
  if (variable.startsWith("temperature")) return "temperature_2m";
  if (variable.startsWith("wind")) return "wind_speed_10m";
  return "precipitation";
}

/** MAE by lead hour for Czechia: [{model, lead_h, mae, bias, n, runs}] sorted by model and hour. */
export function leadHourLines(doc, variable, runHour = "all") {
  if (!doc?.rows) return [];
  const columns = doc.columns;
  return doc.rows
    .map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])))
    .filter((r) => (r.region ?? "cz") === "cz" && r.run_hour === runHour && r.variable === variable && r.mae != null)
    .map((r) => ({ model: r.model, lead_h: r.lead_h, mae: r.mae, bias: r.bias, n: r.n, runs: r.runs }))
    .sort((a, b) => a.model.localeCompare(b.model) || a.lead_h - b.lead_h);
}

/** Run hours with rows in the file: "all" first, then "00", "06", "12", "18". */
export function leadHourRunHours(doc) {
  if (!doc?.rows) return [];
  const at = doc.columns.indexOf("run_hour");
  const found = new Set(doc.rows.map((row) => row[at]));
  return ["all", "00", "06", "12", "18"].filter((h) => found.has(h));
}

/**
 * The best models over the lead hours: at every lead hour each model gets its rank among
 * the models compared there, scaled 0 (best) to 1 (worst); models are ordered by their
 * mean scaled rank. Fair to short models, which only meet the others at early hours.
 */
export function leadHourRanking(lines) {
  const byLead = new Map();
  for (const r of lines) {
    if (!byLead.has(r.lead_h)) byLead.set(r.lead_h, []);
    byLead.get(r.lead_h).push(r);
  }
  const scores = new Map();
  for (const group of byLead.values()) {
    if (group.length < 2) continue;
    const sorted = [...group].sort((a, b) => a.mae - b.mae);
    sorted.forEach((r, i) => {
      const s = scores.get(r.model) ?? [];
      s.push(i / (sorted.length - 1));
      scores.set(r.model, s);
    });
  }
  return [...scores.entries()]
    .map(([model, s]) => ({ model, score: s.reduce((a, b) => a + b, 0) / s.length, leads: s.length }))
    .sort((a, b) => a.score - b.score || a.model.localeCompare(b.model));
}

/** True for ČHMÚ's ALADIN (both domains), marked on the chart. */
export function isAladin(model) {
  return model.startsWith("chmi_aladin");
}

/** How much history the chart rests on: runs per model (the most), models, stations,
 * first and last run (YYYY-MM-DD HH UTC) and days from the first to the last run. */
export function leadHourBasis(doc) {
  const models = Object.values(doc?.models ?? {});
  if (!models.length || !doc.first_run) return null;
  const first = new Date(doc.first_run);
  const last = new Date(doc.last_run);
  const stamp = (d) => `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 13)} UTC`;
  return {
    runs: Math.max(...models.map((m) => m.runs ?? 0)),
    models: models.length,
    stations: doc.stations ?? null,
    first: stamp(first),
    last: stamp(last),
    days: Math.round((last - first) / 864e5 * 10) / 10,
  };
}

/** Hours after a run's start before ČHMÚ has published ALADIN: the largest measured
 * median delay, or `fallback` (about 4 h, docs/data-sources.md) before delays were
 * recorded. Known for ALADIN only. */
export function unpublishedHours(doc, fallback = 4) {
  const delays = Object.values(doc?.models ?? {})
    .map((m) => m.publication_delay_h)
    .filter((d) => d != null);
  return delays.length ? Math.max(...delays) : fallback;
}
