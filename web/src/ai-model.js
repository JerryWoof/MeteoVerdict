// MeteoVerdict AI as one more model of the forecast pages (forecast.html and
// forecast-detail.html): its published forecast (data/scores/ai/ai-forecast.json, hourly
// temperature and wind per okres at the station point) offered next to the public models.
// It is the default and listed first (experimental only in its name); when its file is
// missing, malformed or stale (a failed daily run) it is not offered and the pages stay on our
// combination, and an okres without AI data falls back to the combination too.

import { modelPeriods, modelSymbol } from "./models.js";

export const AI_MODEL = "mv_ai";
export const AI_URL = "data/scores/ai/ai-forecast.json";
/** Older than this (hours since issue): not offered. The daily run is ~every 24 h. */
export const MAX_AGE_HOURS = 36;
/** The AI's cloud, sunshine and gusts per okres and part of day (a shadow file of the engine). */
export const SKY_URL = "data/scores/ai/fc/sky/ai-sky.json";
const AI_VARIABLES = ["temperature_2m", "wind_speed_10m"];
// what the AI does not forecast hourly: rain, taken from our blend (labelled "z blendu" on the
// pages); cloud, sunshine and gusts come from its sky file per part of day when it has them
const BLEND_VARIABLES = ["precipitation", "cloud_cover", "sunshine_duration"];
/** The outlook's gust warning threshold (m/s). */
const GUST_THRESHOLD = 13.5;
const BLEND_FIELDS = ["precipitation", "cloud", "sunshine", "symbol", "gust", "gust_over_threshold"];

/**
 * The AI forecast file → {issued (ISO), okresy: {code: {times: [ms], temperature_2m,
 * wind_speed_10m}}}, or null when it is missing, malformed or older than MAX_AGE_HOURS.
 * An okres without a usable temperature series is left out.
 */
export function parseAi(doc, now = Date.now()) {
  const issued = Date.parse(doc?.issued ?? doc?.generated ?? "");
  if (!doc?.okresy || Number.isNaN(issued)) return null;
  if (now - issued > MAX_AGE_HOURS * 3600 * 1000 || issued - now > 3600 * 1000) return null;
  const okresy = {};
  for (const [code, o] of Object.entries(doc.okresy)) {
    if (!Array.isArray(o?.time)) continue;
    const times = o.time.map((s) => Date.parse(s));
    if (times.some(Number.isNaN)) continue;
    const series = { times };
    for (const variable of AI_VARIABLES) {
      const values = o[variable]?.ai;
      series[variable] = Array.isArray(values) && values.length === times.length
        ? values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null))
        : null;
    }
    if (series.temperature_2m?.some((v) => v != null)) okresy[code] = series;
  }
  return { issued: doc.issued ?? doc.generated, okresy };
}

/**
 * The sky file → Map okres → Map "day|part" → {cloud, sunshine, gust} (numbers or null), or
 * null when it is missing, malformed or older than MAX_AGE_HOURS.
 */
export function parseSky(doc, now = Date.now()) {
  const issued = Date.parse(doc?.issued ?? "");
  if (!doc?.okresy || Number.isNaN(issued)) return null;
  if (now - issued > MAX_AGE_HOURS * 3600 * 1000 || issued - now > 3600 * 1000) return null;
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const out = new Map();
  for (const [code, o] of Object.entries(doc.okresy)) {
    if (!Array.isArray(o?.rows)) continue;
    out.set(code, new Map(o.rows.map((r) => [`${r.day}|${r.part}`, { cloud: num(r.cloud), sunshine: num(r.sunshine), gust: num(r.gust) }])));
  }
  return out;
}

/** Loads (once per `getJson` result promise) and parses the files; null when unusable. */
let loaded = null;
export function loadAi(getJson) {
  loaded ??= Promise.all([
    Promise.resolve(getJson(AI_URL)).then((doc) => parseAi(doc)).catch(() => null),
    Promise.resolve(getJson(SKY_URL)).then((doc) => parseSky(doc)).catch(() => null),
  ]).then(([ai, sky]) => (ai ? { ...ai, sky } : null));
  return loaded;
}

/**
 * A row (an okres's part of day from the blend or from the hourly series) with the AI's own
 * cloud, sunshine and gust where its sky file has them (the rest stays), and the symbol
 * recomputed from the AI's cloud.
 */
export function skyRow(row, ai, code, key) {
  const own = ai?.sky?.get(code)?.get(key);
  if (!own || !row) return row;
  const next = { ...row };
  if (own.cloud != null) next.cloud = own.cloud;
  if (own.sunshine != null) next.sunshine = own.sunshine;
  if (own.gust != null) {
    next.gust = own.gust;
    next.gust_over_threshold = own.gust >= GUST_THRESHOLD;
  }
  if (own.cloud != null && row.tmin != null && row.tmax != null) {
    next.symbol = modelSymbol(next.cloud, next.precipitation, (row.tmin + row.tmax) / 2) ?? row.symbol;
  }
  return next;
}

/** A model's periods (modelPeriods) with the AI's sky values: a new Map. */
export function aiPeriods(periods, ai, code) {
  return new Map([...periods].map(([key, row]) => [key, skyRow(row, ai, code, key)]));
}

/** True when the AI has a forecast for this okres. */
export const hasAi = (ai, code) => Boolean(ai?.okresy?.[code]);

/** A copy of forecast/models parsed data with the AI added (as `models.mv_ai`), on its times. */
export function withAi(parsed, ai, code) {
  const own = ai?.okresy?.[code];
  if (!parsed || !own) return parsed;
  const at = new Map(own.times.map((t, i) => [t, i]));
  const series = {};
  for (const variable of AI_VARIABLES) {
    if (own[variable]) series[variable] = parsed.times.map((t) => (at.has(t) ? own[variable][at.get(t)] : null));
  }
  if (!series.temperature_2m.some((v) => v != null)) return parsed;
  // rain, cloud and sunshine from the blend, on the hours the AI covers
  for (const variable of BLEND_VARIABLES) {
    const blend = parsed.combined?.[variable];
    if (blend?.some((v) => v != null)) series[variable] = blend.map((v, i) => (series.temperature_2m[i] != null ? v : null));
  }
  return { ...parsed, models: { ...parsed.models, [AI_MODEL]: series }, aiIssued: ai.issued };
}

const PARTS = ["night", "morning", "afternoon", "evening"];
const EMPTY = { tmin: null, tmax: null, precipitation: null, wind: null, cloud: null, sunshine: null, symbol: null };

/** The AI as a whole-map view (the shape of models.js parseModelParts), or null. */
export function aiMapView(ai, outlook) {
  if (!ai || !outlook) return null;
  const rows = new Map();
  let lastHour = null;
  for (const o of outlook.okresy) {
    const own = ai.okresy[o.code];
    const periods = own
      ? modelPeriods({ times: own.times, models: { [AI_MODEL]: Object.fromEntries(AI_VARIABLES.filter((v) => own[v]).map((v) => [v, own[v]])) } }, AI_MODEL)
      : new Map();
    if (own) {
      for (let i = own.times.length - 1; i >= 0; i -= 1) {
        if (own.temperature_2m[i] != null) { lastHour = Math.max(lastHour ?? 0, own.times[i]); break; }
      }
    }
    for (const day of outlook.days) {
      const sun = [...PARTS, "day"].map((p) => outlook.rows.get(`${o.code}|${day}|${p}`)).find((r) => r?.sunrise);
      const sunTimes = sun ? { sunrise: sun.sunrise, sunset: sun.sunset } : {};
      for (const part of [...PARTS, "day"]) {
        const p = periods.get(`${day}|${part}`);
        const blend = outlook.rows.get(`${o.code}|${day}|${part}`);
        const fill = blend ? Object.fromEntries(BLEND_FIELDS.map((f) => [f, blend[f] ?? null])) : {};
        // an okres the AI has no forecast for shows our blend's row whole (same look, rain in mm),
        // so the map has no gaps; a period beyond the AI's hours stays "–"
        rows.set(`${o.code}|${day}|${part}`, p
          ? skyRow({ ...EMPTY, ...p, ...fill, single: true, ...sunTimes }, ai, o.code, `${day}|${part}`)
          : !own && blend
            ? { ...blend, single: true }
            : { ...EMPTY, rain_probability: null, single: true, beyond: true, ...sunTimes });
      }
    }
  }
  return { single: true, model: AI_MODEL, generated: ai.issued, lastHour, days: outlook.days, okresy: outlook.okresy, rows };
}
