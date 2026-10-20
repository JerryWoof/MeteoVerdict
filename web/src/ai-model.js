// MeteoVerdict AI as one more model of the forecast pages (forecast.html and
// forecast-detail.html): its published forecast (data/scores/ai/ai-forecast.json, hourly
// temperature and wind per okres at the station point) offered next to the public models.
// It is the default and listed first (experimental only in its name); when its file is
// missing, malformed or stale (a failed daily run) it is not offered and the pages stay on our
// combination, and an okres without AI data falls back to the combination too.

import { modelPeriods } from "./models.js";

export const AI_MODEL = "mv_ai";
export const AI_URL = "data/scores/ai/ai-forecast.json";
/** Older than this (hours since issue): not offered. The daily run is ~every 24 h. */
export const MAX_AGE_HOURS = 36;
const AI_VARIABLES = ["temperature_2m", "wind_speed_10m"];

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

/** Loads (once per `getJson` result promise) and parses the file; null when unusable. */
let loaded = null;
export function loadAi(getJson) {
  loaded ??= Promise.resolve(getJson(AI_URL)).then((doc) => parseAi(doc)).catch(() => null);
  return loaded;
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
        rows.set(`${o.code}|${day}|${part}`, p
          ? { ...EMPTY, ...p, single: true, ...sunTimes }
          : { ...EMPTY, rain_probability: null, single: true, beyond: true, ...sunTimes });
      }
    }
  }
  return { single: true, model: AI_MODEL, generated: ai.issued, lastHour, days: outlook.days, okresy: outlook.okresy, rows };
}
