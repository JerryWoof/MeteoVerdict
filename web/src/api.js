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
export const DOCS = `${SITE}/api.html`;
export const LICENCE = "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)";
// the scores published per okres, and which weights of the combination belong to them
export const SCORE_VARIABLES = ["temperature_2m", "wind_speed_10m", "precipitation_daily", "precipitation_24h"];
const WEIGHTS_OF = { temperature_2m: "temperature_2m", wind_speed_10m: "wind_speed_10m", precipitation_daily: "precipitation" };
export const HOURLY = ["temperature_2m", "precipitation", "wind_speed_10m", "cloud_cover", "sunshine_duration"];
const PART_FIELDS = [
  "day", "part", "tmin", "tmax", "precipitation", "rain_probability", "wind", "cloud", "sunshine", "symbol",
  "sunrise", "sunset",
  // optional (null without the rain calibration): P(>= 5 mm) in the period and its flag
  "heavy_rain_probability", "heavy_rain",
  // frost (on the night and day rows of the date a night ends; null elsewhere and in
  // older outlook files): corrected night minimum, coldest site, probability, warnings
  "night_min", "coldest_site", "coldest_min", "frost_probability", "frost", "ground_min", "ground_frost",
  // gusts (from the newest single run, corrected; null beyond its end and in older
  // outlook files): the strongest gust of the period in m/s and the strong-gust warning
  "gust", "gust_warning",
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
    .map((r) => Object.fromEntries(PART_FIELDS.map((k) => [k, r[k] ?? null])));
  const window = meta?.windows?.["90d"] ?? null;
  return {
    api: `MeteoVerdict open data ${VERSION}`,
    docs: DOCS,
    licence: LICENCE,
    attribution: meta?.attribution ?? null,
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
      metrics: "MAE, bias (forecast minus observed) and RMSE at D+1…D+5; rank 1 = smallest MAE; tied_with_best: not significantly worse (95 % bootstrap interval over days); weight/correction: as used in our forecast (correction: mean over the day); mos_weight: weight in the temperature and wind regression blend, used when all its models have a value",
      variables: okresModels(okres.code, scores, weightsDoc, meta?.models ?? {}),
    },
  };
}

/** The hourly forecast of an okres as CSV (UTC times; empty cells where missing). */
export function okresCsv(doc) {
  const h = doc.forecast.hourly;
  const header = ["time_utc", ...HOURLY].join(",");
  if (!h) return `${header}\n`;
  const lines = h.time.map((time, i) => [time, ...HOURLY.map((v) => h[v]?.[i] ?? "")].join(","));
  return `${[header, ...lines].join("\n")}\n`;
}

/** index.json: every okres with the addresses of its files. */
export function indexDoc(okresy, meta, generated) {
  return {
    api: `MeteoVerdict open data ${VERSION}`,
    docs: DOCS,
    licence: LICENCE,
    attribution: meta?.attribution ?? null,
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
