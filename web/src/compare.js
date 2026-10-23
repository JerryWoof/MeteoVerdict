// The model comparison page: ranking for Czechia, a kraj or an okres, the interval of
// each model's difference to the best, MAE by lead day, and bias by elevation class.

import { parseHash } from "./view.js";

const ELEVATION_ORDER = ["lowland", "upland", "mountain"];

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

/** Station sets of the ranking for Czechia: all, or one kind (the `network` level). */
export const STATION_SETS = ["all", "main", "other"];

/** How the precipitation ranking table is sorted: by MAE (the ranking) or by ETS. */
export const RANK_BY = ["mae", "ets1", "ets10"];

/** True when some row of the ranking table has a value in `key` (e.g. older files lack it). */
export const hasValues = (table, key) => table.some((r) => r[key] != null);

/**
 * The ranking table sorted by event skill (`key`: "ets1" or "ets10"; higher is better):
 * the models with a value first, numbered by it (`etsRank`, no intervals), then the
 * ones without, then the mean of all models and the models with too short a record,
 * as in the MAE ranking.
 */
export function sortByEts(table, key) {
  const group = (r) => (r.short ? 3 : r.model === "blend" ? 2 : r[key] == null ? 1 : 0);
  const sorted = table
    .slice()
    .sort((a, b) => group(a) - group(b) || (b[key] ?? 0) - (a[key] ?? 0) || (a.mae ?? 0) - (b.mae ?? 0));
  let position = 0;
  return sorted.map((r) => ({ ...r, etsRank: group(r) === 0 ? ++position : null }));
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
    .filter((r) => r.region === region && r.mae != null && !isShort(r))
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
    .filter((r) => r.lead_day === leadDay && r.model !== "blend" && r.bias != null && !isShort(r))
    .filter((r) => ELEVATION_ORDER.includes(r.region))
    .sort((a, b) => ELEVATION_ORDER.indexOf(a.region) - ELEVATION_ORDER.indexOf(b.region))
    .map((r) => ({ elevation: r.region, model: r.model, bias: r.bias }));
}

/** "1.23", "+0.45", "–" (in `language`: "1,23" in Czech) */
export function fmt(value, signed = false, language = "en") {
  if (value == null || Number.isNaN(value)) return "–";
  // the real minus sign, as in "+0,02": a hyphen next to a plus looks like a dash
  const text = value.toLocaleString(language, { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false }).replace("-", "−");
  return signed && value > 0 ? `+${text}` : text;
}

// --- chart text in the page language (Plot's defaults are English: "0.5", "Sep 13")
const decimals = (value) => (String(Number(value.toPrecision(12))).split(".")[1] ?? "").length;

/**
 * An axis tickFormat for numbers: "0,5" in Czech, the real minus sign, and as many
 * decimals on every tick ("1,0 1,5 2,0"; Plot passes the ticks as the third argument).
 */
export function numberTick(language) {
  return (value, _, ticks) => {
    const digits = Math.min(3, Math.max(0, ...(Array.isArray(ticks) ? ticks : [value]).map(decimals)));
    return value.toLocaleString(language, { minimumFractionDigits: digits, maximumFractionDigits: digits }).replace("-", "−");
  };
}

/** An axis tickFormat for days: "13. září" in Czech, "Sep 13" in English. */
export function dayTick(language) {
  const format = new Intl.DateTimeFormat(language === "cs" ? "cs-CZ" : "en-US", {
    day: "numeric", month: language === "cs" ? "long" : "short", timeZone: "UTC",
  });
  return (date) => format.format(date);
}

/** A chart tooltip (Plot's `title` channel): the lines that are given, one per row. */
export const tipText = (...lines) => lines.filter((line) => line != null && line !== "").join("\n");

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
 * first and last run (YYYY-MM-DD HH CET|CEST, Prague time) and days from the first to the last run. */
export function leadHourBasis(doc) {
  const models = Object.values(doc?.models ?? {});
  if (!models.length || !doc.first_run) return null;
  const first = new Date(doc.first_run);
  const last = new Date(doc.last_run);
  // Prague time, as the site shows it (i18n.js turns "2026-10-09 02 CEST" into the language)
  const prague = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Prague", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23", timeZoneName: "short",
  });
  const stamp = (d) => {
    const p = Object.fromEntries(prague.formatToParts(d).map((x) => [x.type, x.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour} ${p.timeZoneName}`;
  };
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

// --- does our combined forecast beat the best model? (blend-test.json)
// Out of sample: on each past day the combination used only scores known before it,
// and is compared with the model that was best for the whole of Czechia at that time
// and used everywhere (best_cz_oos, what most people do), with the best model of each
// okres at that time (best_oos, a harder competitor) and with every single model.

export const BLEND_TEST_VARIABLES = ["temperature_2m", "wind_speed_10m", "precipitation_daily"];
export const BLEND_TEST_SERIES = ["combined", "best_cz_oos", "best_oos", "blend", "best_hindsight"];
/** The model most people in Czechia use: listed first among the single models. */
export const HOME_MODEL = "chmi_aladin_cz_1km";

/** The tested variable closest to a page variable (temperature by hour, wind, rain). */
export function blendTestVariable(variable) {
  if (variable.startsWith("precipitation")) return "precipitation_daily";
  if (variable.startsWith("wind")) return "wind_speed_10m";
  return "temperature_2m";
}

/** The rows of one region (Czechia: "cz") of blend-test.json, as objects. */
export function blendTestRows(doc, region = "cz") {
  const table = doc?.groups;
  if (!table?.rows?.length) return [];
  return table.rows
    .map((row) => Object.fromEntries(table.columns.map((c, i) => [c, row[i]])))
    .filter((r) => r.region === region);
}

/**
 * The verdict of one row: "better" when the 95 % interval of (our MAE − the best
 * model's MAE) lies below 0, "worse" above 0, otherwise "same" (no significant
 * difference). `amount` is how much better (positive) or worse, with its interval
 * in the same direction (low ≤ high).
 */
export function blendVerdict(row, against = "okres") {
  const suffix = against === "cz" ? "_vs_cz" : "";
  return verdictOf(row?.[`diff_combined${suffix}`], row?.[`low_combined${suffix}`], row?.[`high_combined${suffix}`]);
}

function verdictOf(diff, low, high) {
  if (diff == null) return null;
  if (high != null && high < 0) return { verdict: "better", amount: -diff, low: -high, high: -low };
  if (low != null && low > 0) return { verdict: "worse", amount: diff, low, high };
  return { verdict: "same", amount: diff, low, high };
}

/**
 * Verdicts by variable and lead day: [{variable, lead_day, days, best, verdict, amount,
 * low, high}]. `against`: "okres" = the best model of each okres (best_oos), "cz" =
 * the best model for the whole of Czechia used everywhere (best_cz_oos; files written
 * before it existed have no such verdicts).
 */
export function blendVerdicts(rows, against = "okres") {
  const best = against === "cz" ? "best_cz_oos" : "best_oos";
  return rows
    .map((r) => ({ variable: r.variable, lead_day: r.lead_day, days: r.days, best: r[best], ...blendVerdict(r, against) }))
    .filter((r) => r.verdict)
    .sort((a, b) => BLEND_TEST_VARIABLES.indexOf(a.variable) - BLEND_TEST_VARIABLES.indexOf(b.variable)
      || a.lead_day - b.lead_day);
}

/** MAE by lead day of one variable for the chart: [{series, lead_day, mae}]. */
export function blendTestLines(rows, variable) {
  const out = [];
  for (const r of rows.filter((x) => x.variable === variable)) {
    for (const series of BLEND_TEST_SERIES) {
      const mae = r[`mae_${series}`];
      if (mae != null) out.push({ series, lead_day: r.lead_day, mae });
    }
  }
  return out.sort((a, b) => BLEND_TEST_SERIES.indexOf(a.series) - BLEND_TEST_SERIES.indexOf(b.series)
    || a.lead_day - b.lead_day);
}

/** Counts per verdict over the okresy at one variable and lead day: {better, same, worse}. */
export function okresVerdictCounts(doc, variable, leadDay) {
  const table = doc?.groups;
  const counts = { better: 0, same: 0, worse: 0 };
  if (!table?.rows) return counts;
  for (const row of table.rows) {
    const r = Object.fromEntries(table.columns.map((c, i) => [c, row[i]]));
    if (r.level !== "okres" || r.variable !== variable || r.lead_day !== leadDay) continue;
    const v = blendVerdict(r);
    if (v) counts[v.verdict] += 1;
  }
  return counts;
}

/**
 * Our forecast against every single model used everywhere in Czechia, for one variable
 * (blend-test.json `single_models`): [{model, cells: {lead_day: cell}}] with the cell
 * {verdict, diff, low, high, pct, pctLow, pctHigh, mae, maeCombined, days}: diff = our
 * MAE minus the model's (negative = ours better), pct the same relative to the model's
 * MAE. ALADIN CZ 1 km first, then by MAE at the shortest lead day (best first). Files
 * written before the intervals existed have no `diff_combined`: no rows.
 */
export function singleModelVerdicts(doc, variable) {
  const table = doc?.single_models;
  if (!table?.rows?.length || !table.columns.includes("diff_combined")) return [];
  const byModel = new Map();
  for (const row of table.rows) {
    const r = Object.fromEntries(table.columns.map((c, i) => [c, row[i]]));
    if (r.variable !== variable) continue;
    const v = verdictOf(r.diff_combined, r.low_combined, r.high_combined);
    if (!v) continue;
    const share = (x) => (x == null || !r.mae ? null : x / r.mae);
    if (!byModel.has(r.model)) byModel.set(r.model, { model: r.model, cells: {} });
    byModel.get(r.model).cells[r.lead_day] = {
      verdict: v.verdict, diff: r.diff_combined, low: r.low_combined, high: r.high_combined,
      pct: share(r.diff_combined), pctLow: share(r.low_combined), pctHigh: share(r.high_combined),
      mae: r.mae, maeCombined: r.mae_combined, days: r.days,
    };
  }
  const first = (m) => {
    const leads = Object.keys(m.cells).map(Number).sort((a, b) => a - b);
    return leads.length ? [leads[0], m.cells[leads[0]].mae] : [Infinity, Infinity];
  };
  return [...byModel.values()].sort((a, b) => {
    if ((a.model === HOME_MODEL) !== (b.model === HOME_MODEL)) return a.model === HOME_MODEL ? -1 : 1;
    const [la, ma] = first(a);
    const [lb, mb] = first(b);
    return la - lb || ma - mb || a.model.localeCompare(b.model);
  });
}

// --- ranking by lead band, run by run (leads-bands-<window>[-kraj].json, `mvd leads`) --
// Every lead hour of the 00/06/12/18 UTC runs against the observation at its valid
// time, pooled over a band of hours (H+1–6 … H+49–72). Czechia, the station kinds
// (main WMO / other) and kraje; okresy have too few of the ~100 run stations.

export const LEAD_BANDS = ["h1-6", "h7-12", "h13-24", "h25-48", "h49-72"];
export const LEAD_DAYS = [1, 2, 3, 4, 5];
/** Windows of the band ranking (the D+N windows also have seasons). */
export const BAND_WINDOWS = ["90d", "all"];
/** Variables of the band ranking, in the order of the variable select. */
export const BAND_VARIABLES = ["temperature_2m", "wind_speed_10m", "precipitation", "wind_gusts_10m"];
/** Fair sets: models with hourly output at every lead hour, or every model at H+6, H+12, … */
export const BAND_SETS = ["hourly", "6h"];
/** How the band ranking of precipitation can be sorted (ETS at 0.1 and 1 mm in the hour). */
export const BAND_RANK_BY = ["mae", "ets", "ets1"];

export const isBand = (lead) => LEAD_BANDS.includes(lead);

/** "h13-24" → the band, "1"…"5" → the lead day, anything else → null. */
export function parseLead(text) {
  if (LEAD_BANDS.includes(text)) return text;
  const day = Number.parseInt(text, 10);
  return String(day) === String(text) && LEAD_DAYS.includes(day) ? day : null;
}

/** "H+13–24" for a band, "D+2" for a lead day. */
export function leadLabel(lead) {
  if (!isBand(lead)) return `D+${lead}`;
  const [first, last] = lead.slice(1).split("-");
  return `H+${first}–${last}`;
}

/** The band variable for a page variable (any temperature → temperature_2m, …). */
export function bandVariable(variable) {
  if (BAND_VARIABLES.includes(variable)) return variable;
  if (variable.startsWith("temperature")) return "temperature_2m";
  if (variable.startsWith("wind")) return "wind_speed_10m";
  return "precipitation";
}

/** The D+N variable for a page variable: itself when offered, else the closest one. */
export function dayVariable(variable, available) {
  if (available.includes(variable)) return variable;
  const closest = variable.startsWith("precipitation")
    ? "precipitation_daily"
    : variable.startsWith("wind") ? "wind_speed_10m" : "temperature_2m";
  return available.includes(closest) ? closest : available[0];
}

/** The kraj of a region code (an okres CZ0642 → CZ064; Czechia and kraje unchanged). */
export const krajOf = (region) => (levelOf(region) === "okres" ? region.slice(0, 5) : region);

/**
 * Rows of a band file as score records like the D+N files (so the ranking table, the
 * summary, the interval chart and the map read them alike): `lead_day` is the band.
 */
export function bandRecords(doc) {
  if (!doc?.rows) return [];
  const names = doc.regions ?? {};
  return doc.rows.map((row) => {
    const r = Object.fromEntries(doc.columns.map((c, i) => [c, row[i]]));
    return {
      level: r.level, region: r.region, region_name: names[r.region] ?? r.region, lead_day: r.band,
      set: r.set, variable: r.variable, model: r.model, rank: r.rank, mae: r.mae, bias: r.bias,
      rmse: r.rmse, mae_bc: r.mae_bc, ets_0p1: r.ets_0p1, ets_1: r.ets_1, pod_1: r.pod_1, far_1: r.far_1,
      diff_ci_low: r.diff_low, diff_ci_high: r.diff_high, tied_with_best: r.tied, clear_winner: r.clear,
      stations: r.stations, days: r.days, runs: r.runs, n: r.n, enough_stations: true,
    };
  });
}

/** The fair sets a variable has (temperature and wind: both; precipitation, gusts: hourly). */
export function bandSets(rows, variable) {
  return BAND_SETS.filter((set) => rows.some((r) => r.variable === variable && r.set === set));
}

/** The bands with rows. */
export function bandsIn(rows) {
  return LEAD_BANDS.filter((band) => rows.some((r) => r.lead_day === band));
}

/**
 * What a band result rests on: runs, stations and days (the same for every model of a
 * fair set) and whether it is preliminary (fewer than `preliminaryDays` days).
 */
export function bandBasis(rows, band, region, preliminaryDays = 30) {
  const row = rows.find((r) => r.lead_day === band && r.region === region && r.rank === 1);
  if (!row) return null;
  return { runs: row.runs, stations: row.stations, days: row.days, preliminary: row.days < preliminaryDays };
}

/** MAE of every model by band in a region, for the chart: [{model, lead_day (1…5), band, mae}]. */
export function maeByBand(rows, region = "cz") {
  return rows
    .filter((r) => r.region === region && r.mae != null && isBand(r.lead_day))
    .map((r) => ({ model: r.model, lead_day: LEAD_BANDS.indexOf(r.lead_day) + 1, band: r.lead_day, mae: r.mae }))
    .sort((a, b) => a.model.localeCompare(b.model) || a.lead_day - b.lead_day);
}

/**
 * The lead the page opens at when the link names none: the band the data suggests
 * (`default_band`, written by `mvd leads` once its 90-day ranking rests on at least 60
 * days), else D+1.
 */
export function defaultLead(doc) {
  return isBand(doc?.default_band) ? doc.default_band : 1;
}

// --- the view in the URL: #variable/lead/window/region/blend-test variable/stations/sort/set
// The first four drive the model ranking; the fifth only the blend-test section; the
// last three only the ranking table (and, for the stations and the set, the charts below
// it). The lead is a lead day (1…5, D+N scores) or a band of hours ahead (h13-24, run by
// run). Links from before the fifth existed open the blend test at the ranking's
// variable, as then; links without the last ones show all stations sorted by MAE.

/** The view of a hash; `leadGiven` false when the hash names no lead (the page picks the data's default). */
export function compareViewFromHash(hash) {
  const view = parseHash(hash ?? "");
  const parts = (hash ?? "").replace(/^#/, "").split("/");
  const lead = parseLead(parts[1]);
  view.leadGiven = lead != null;
  if (lead != null) view.leadDay = lead;
  // the band variables that are no D+N variable (hourly precipitation, gusts)
  if (isBand(view.leadDay) && BAND_VARIABLES.includes(parts[0])) view.variable = parts[0];
  view.region = parts[3] || "cz";
  view.blendVariable = BLEND_TEST_VARIABLES.includes(parts[4]) ? parts[4] : blendTestVariable(view.variable);
  view.stations = STATION_SETS.includes(parts[5]) ? parts[5] : "all";
  view.rankBy = [...RANK_BY, ...BAND_RANK_BY].includes(parts[6]) ? parts[6] : "mae";
  view.set = parts[7] === "6h" ? "6h" : "hourly";
  if (BAND_WINDOWS.includes(parts[2])) view.window = parts[2];
  return view;
}

/** The hash of a view (the last three only when not the defaults). */
export function compareHash(view) {
  const base = `#${view.variable}/${view.leadDay}/${view.window}/${view.region}/${view.blendVariable}`;
  const extra = view.stations !== "all" || view.rankBy !== "mae" || view.set !== "hourly"
    ? `/${view.stations}/${view.rankBy}${view.set !== "hourly" ? `/${view.set}` : ""}`
    : "";
  return base + extra;
}

/** Is going from view `a` to view `b` a step of its own in the browser's history (another variable or region)? */
export const compareIsStep = (a, b) => Boolean(a) && (a.variable !== b.variable || a.region !== b.region);
