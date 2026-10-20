// Open data (roadmap 6.11): static JSON and CSV files per okres, built with the site
// from the data the pages already use, so anyone can fetch "their" okres:
//   api/v1/index.json             all okresy and where their files are
//   api/v1/okresy/<code>.json     forecast (hourly and by part of day) and model ranking
//   api/v1/okresy/<code>.csv      the hourly forecast as CSV
// GitHub Pages serves them with "Access-Control-Allow-Origin: *", so browsers can fetch
// them from any site.

import { records } from "./data.js";

export const VERSION = "v1";
export const SITE = "https://jerrywoof.github.io/MeteoVerdict";
export const DOCS = `${SITE}/data.html`;
export const LICENCE = "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)";
// the scores published per okres, and which weights of the combination belong to them
// the threshold flags are ours: only ČHMÚ issues weather warnings (Act 262/2024 Sb.)
export const FLAGS = ["gust_over_threshold", "gust_warning", "frost", "ground_frost", "heavy_rain"];
export const NOTICE =
  "Threshold flags (gust_over_threshold, frost, ground_frost, heavy_rain) are MeteoVerdict thresholds, not official ČHMÚ warnings; official warnings: https://www.chmi.cz/";
export const DEPRECATED = {
  gust_warning: "deprecated: the same value as gust_over_threshold; will be removed in the next API version",
};

export const SCORE_VARIABLES = ["temperature_2m", "wind_speed_10m", "precipitation_daily", "precipitation_24h"];
const WEIGHTS_OF = { temperature_2m: "temperature_2m", wind_speed_10m: "wind_speed_10m", precipitation_daily: "precipitation" };
// the 80 % range of the temperature (`mvd blend-interval`): absent from older outlook files
const RANGE = ["temperature_2m_lo", "temperature_2m_hi"];
export const HOURLY = ["temperature_2m", "precipitation", "wind_speed_10m", "cloud_cover", "sunshine_duration", "temperature_2m_lo", "temperature_2m_hi"];
const PART_FIELDS = [
  "day", "part", "tmin", "tmax", "precipitation", "rain_probability", "wind", "cloud", "sunshine", "symbol",
  "sunrise", "sunset",
  // optional (null without the rain calibration): P(>= 5 mm) in the period and its flag
  "heavy_rain_probability", "heavy_rain",
  // frost (on the night and day rows of the date a night ends; null elsewhere and in
  // older outlook files): corrected night minimum, coldest site, probability, warnings
  "night_min", "coldest_site", "coldest_min", "frost_probability", "frost", "ground_min", "ground_frost",
  // gusts (from the newest single run, corrected; null beyond its end and in older
  // outlook files): the strongest gust of the period in m/s and whether it is over the
  // threshold (gust_warning: the deprecated alias of gust_over_threshold, same value)
  "gust", "gust_over_threshold", "gust_warning",
];

const round = (v, digits) => (v == null ? null : Number(v.toFixed(digits)));

/** Ranking of the models in one okres per variable and lead day, with their weights in
 * our combined forecast where there is one. */
export function okresModels(code, scores, weightsDoc, names) {
  const weights = new Map(records(weightsDoc).map((r) => [`${r.variable}|${r.lead_day}|${r.model}`, r]));
  const variables = {};
  for (const variable of SCORE_VARIABLES) {
    const rows = (scores[variable] ?? []).filter((r) => r.region === code && r.model !== "blend");
    if (rows.length === 0) continue;
    const byLead = {};
    for (const r of rows.sort((a, b) => a.lead_day - b.lead_day || (a.rank ?? 99) - (b.rank ?? 99))) {
      const w = weights.get(`${WEIGHTS_OF[variable]}|${r.lead_day}|${r.model}`);
      (byLead[r.lead_day] ??= []).push({
        model: r.model,
        name: names[r.model] ?? r.model,
        rank: r.rank,
        mae: round(r.mae, 3),
        bias: round(r.bias, 3),
        rmse: round(r.rmse, 3),
        tied_with_best: Boolean(r.tied_with_best),
        // probability of being the best (share of the block-bootstrap resamples; null in
        // older score files) and whether the ranking rests on fewer than 30 days
        p_best: r.p_best != null ? round(r.p_best, 3) : null,
        small_sample: Boolean(r.small_sample),
        // too short a record in the window (e.g. added recently): not ranked, no weight;
        // its MAE is over its own `days` only
        short_record: Boolean(r.short_record),
        days: r.days ?? null,
        weight: w ? round(w.weight, 4) : null,
        correction: w ? round(w.correction, 4) : null,
        // temperature and wind: weight in the regression blend (null without one)
        mos_weight: w?.mos_weight != null ? round(w.mos_weight, 4) : null,
      });
    }
    const first = rows[0];
    variables[variable] = { stations: first.stations, borrowed: first.borrowed ?? 0, days: first.days, lead_days: byLead };
  }
  return variables;
}

/** The JSON file of one okres. */
export function okresDoc({ okres, outlook, hourly, weightsDoc, scores, meta }) {
  const series = hourly?.okresy?.[okres.code];
  const parts = records(outlook)
    .filter((r) => r.okres === okres.code)
    .map((r) => {
      const part = Object.fromEntries(PART_FIELDS.map((k) => [k, r[k] ?? null]));
      // outlook files from before the rename only have the old name: same value in both
      part.gust_over_threshold = r.gust_over_threshold ?? r.gust_warning ?? null;
      part.gust_warning = part.gust_over_threshold;
      return part;
    });
  const window = meta?.windows?.["90d"] ?? null;
  return {
    api: `MeteoVerdict open data ${VERSION}`,
    docs: DOCS,
    licence: LICENCE,
    attribution: meta?.attribution ?? null,
    notice: NOTICE,
    deprecated: DEPRECATED,
    okres: { code: okres.code, name: okres.name, lat: okres.lat, lon: okres.lon },
    forecast: {
      generated: hourly?.generated ?? outlook?.generated ?? null,
      method: "all models combined with weights and bias corrections from their scores in this okres over the last 90 days; temperature and wind by a regression on the models with hour-of-day and elevation corrections (docs/methodology.md)",
      time_zone_of_parts: outlook?.time_zone ?? "Europe/Prague",
      units: hourly?.variables ?? null,
      hourly: series ? { time: hourly.time, ...series } : null,
      parts,
    },
    models: {
      generated: meta?.generated ?? null,
      window: "90d",
      from: window?.from ?? null,
      to: window?.to ?? null,
      metrics: "MAE, bias (forecast minus observed) and RMSE at D+1…D+5; rank 1 = smallest MAE; tied_with_best: not significantly worse (95 % bootstrap interval over blocks of 4 days, or Diebold-Mariano test); p_best: share of bootstrap resamples in which the model is best (no clear winner below 0.6); small_sample: fewer than 30 days; weight/correction: as used in our forecast (correction: mean over the day); mos_weight: weight in the temperature and wind regression blend, used when all its models have a value; short_record: scores on fewer than 80 % of the window's days (e.g. a newly added model), not ranked and no weight, its MAE is over its own days",
      variables: okresModels(okres.code, scores, weightsDoc, meta?.models ?? {}),
    },
  };
}

/**
 * The hourly forecast of an okres as CSV (UTC times; empty cells where missing). Plain
 * CSV, one header row and no comment line, so that =IMPORTDATA, Excel and pandas read it
 * as it is. It has none of the threshold FLAGS, so it needs no NOTICE (index.json and
 * every JSON file carry it); a CSV with a flag would need one (docs/open-data.md).
 */
export function okresCsv(doc) {
  const h = doc.forecast.hourly;
  // the 80 % range columns only while the forecast has them
  const columns = HOURLY.filter((v) => !RANGE.includes(v) || h?.[v]);
  const header = ["time_utc", ...columns].join(",");
  if (!h) return `${header}\n`;
  const lines = h.time.map((time, i) => [time, ...columns.map((v) => h[v]?.[i] ?? "")].join(","));
  return `${[header, ...lines].join("\n")}\n`;
}

/** index.json: every okres with the addresses of its files. */
export function indexDoc(okresy, meta, generated) {
  return {
    api: `MeteoVerdict open data ${VERSION}`,
    docs: DOCS,
    licence: LICENCE,
    attribution: meta?.attribution ?? null,
    notice: NOTICE,
    generated,
    files: {
      okres_json: `${SITE}/api/${VERSION}/okresy/{code}.json`,
      okres_csv: `${SITE}/api/${VERSION}/okresy/{code}.csv`,
    },
    okresy: okresy.map((o) => ({
      code: o.code,
      name: o.name,
      lat: o.lat,
      lon: o.lon,
      json: `${SITE}/api/${VERSION}/okresy/${o.code}.json`,
      csv: `${SITE}/api/${VERSION}/okresy/${o.code}.csv`,
    })),
  };
}
