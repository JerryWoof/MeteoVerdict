// Our own forecast for one okres (roadmap 6.3): today's forecasts of all models from
// Open-Meteo, combined with the weights and bias corrections `mvd aggregate` publishes
// per okres, variable and lead day (forecast/<okres>.json, roadmap 6.2).

import { records } from "./data.js";

export const VARIABLES = ["temperature_2m", "precipitation", "wind_speed_10m"];
export const MAX_LEAD_DAY = 5;
export const FORECAST_DAYS = 6;
// variables that cannot be negative after the bias correction
const NON_NEGATIVE = new Set(["precipitation", "wind_speed_10m"]);
const HOUR = 3600 * 1000;

/** Open-Meteo Forecast API request for all `models` at an okres's point, in UTC. */
export function forecastUrl(point, models) {
  const params = new URLSearchParams({
    latitude: point.lat,
    longitude: point.lon,
    hourly: VARIABLES.join(","),
    wind_speed_unit: "ms",
    timezone: "GMT",
    forecast_days: FORECAST_DAYS,
    models: models.join(","),
  });
  return `https://api.open-meteo.com/v1/forecast?${params}`;
}

/**
 * The API answer as {times: [ms], values: {variable: {model: [value|null]}}};
 * with several models each column is called `<variable>_<model>`.
 */
export function parseForecast(doc, models) {
  const hourly = doc?.hourly ?? {};
  const times = (hourly.time ?? []).map((s) => Date.parse(`${s}Z`));
  const values = {};
  for (const variable of VARIABLES) {
    values[variable] = {};
    for (const model of models) {
      const column = hourly[`${variable}_${model}`] ?? (models.length === 1 ? hourly[variable] : null);
      if (column && column.some((v) => v != null)) values[variable][model] = column;
    }
  }
  return { times, values };
}

/**
 * Which lead day's weights apply to an hour: whole days ahead of `now`, from 1 (the
 * next 24 h use D+1, the shortest lead time we score) to MAX_LEAD_DAY.
 */
export function leadDay(time, now) {
  const days = Math.floor((time - now) / (24 * HOUR));
  return Math.min(MAX_LEAD_DAY, Math.max(1, days));
}

/** forecast/<okres>.json → Map "variable|lead day" → [{model, weight, correction, rank, mae}] */
export function weightTable(doc) {
  const table = new Map();
  for (const r of records(doc)) {
    const key = `${r.variable}|${r.lead_day}`;
    if (!table.has(key)) table.set(key, []);
    table.get(key).push(r);
  }
  return table;
}

/** All models with a weight anywhere in the okres. */
export function weightedModels(table) {
  return [...new Set([...table.values()].flat().map((r) => r.model))];
}

/** Weights for a variable and lead day, falling back to the nearest shorter lead day. */
export function weightsAt(table, variable, lead) {
  for (let d = lead; d >= 1; d -= 1) {
    const rows = table.get(`${variable}|${d}`);
    if (rows?.length) return rows;
  }
  return [];
}

/** The model ranked first for a variable at a lead day (null if none is ranked). */
export function bestModel(table, variable, lead) {
  return weightsAt(table, variable, lead).find((r) => r.rank === 1)?.model ?? null;
}

// a model that ends before the others fades out over its last hours instead of
// dropping out at once (as MeteoSwiss does; docs/forecast-research.md)
export const TAPER_HOURS = 3;

/** Weight factor per hour for a series that may end early: 1, then ¾, ½, ¼ at its end. */
export function taper(values) {
  let last = values.length - 1;
  while (last >= 0 && values[last] == null) last -= 1;
  if (last === values.length - 1) return values.map(() => 1);
  return values.map((_, i) => Math.min(1, (last - i + 1) / (TAPER_HOURS + 1)));
}

// corrections at 00, 06, 12 and 18 UTC (temperature and wind, `mvd daily`)
export const SLOT_CORRECTIONS = ["correction_00", "correction_06", "correction_12", "correction_18"];

/**
 * A model's correction at an hour: the slot corrections interpolated linearly in UTC
 * hour (00 → 06 → 12 → 18 → 00) where the weight file has them, else `correction`
 * (as combine.hourly_correction).
 */
export function correctionAt(r, time) {
  if (r.correction_00 == null) return r.correction ?? 0;
  const d = new Date(time);
  const position = (d.getUTCHours() + d.getUTCMinutes() / 60) / 6;
  const index = Math.floor(position) % 4;
  const fraction = position - Math.floor(position);
  const a = r[SLOT_CORRECTIONS[index]];
  const b = r[SLOT_CORRECTIONS[(index + 1) % 4]];
  return a * (1 - fraction) + b * fraction;
}

/**
 * The combined forecast per hour: Σ weight · (forecast − correction) over the models
 * that have a value for that hour (tapered at their end), the weights rescaled to sum
 * to 1; null when fewer than `minModels` models have a value.
 *
 * Temperature and wind with a regression blend (`mos_weight`, `mos_models`, as
 * combine.combine_values): where all `mos_models` models of it have a value and none
 * is fading out, Σ mos_weight · (forecast − correction) over them instead.
 */
export function combine(forecast, table, variable, now, minModels = 2) {
  const series = forecast.values[variable] ?? {};
  const fades = Object.fromEntries(Object.entries(series).map(([m, v]) => [m, taper(v)]));
  return forecast.times.map((time, i) => {
    let sum = 0;
    let total = 0;
    let count = 0;
    let regression = 0;
    let present = 0;
    let expected = 0;
    for (const r of weightsAt(table, variable, leadDay(time, now))) {
      if (r.mos_models > 0) expected = r.mos_models;
      const value = series[r.model]?.[i];
      if (value == null) continue;
      const corrected = value - correctionAt(r, time);
      const weight = r.weight * fades[r.model][i];
      sum += weight * corrected;
      total += weight;
      count += 1;
      if (r.mos_weight != null && fades[r.model][i] >= 1) {
        regression += r.mos_weight * corrected;
        present += 1;
      }
    }
    if (count < minModels || total <= 0) return null;
    const value = expected > 0 && present === expected ? regression : sum / total;
    return NON_NEGATIVE.has(variable) ? Math.max(0, value) : value;
  });
}

/** Local calendar day (YYYY-MM-DD) of a time in a time zone. */
export function localDay(time, timeZone) {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(time);
}

/**
 * Daily summary in local time from hourly series: {day, tmin, tmax, precipitation, wind}
 * (wind: highest hourly mean). Days with fewer than 20 hours of temperature are left out.
 */
export function dailySummary(times, series, timeZone = "Europe/Prague") {
  const days = new Map();
  times.forEach((time, i) => {
    const day = localDay(time, timeZone);
    if (!days.has(day)) days.set(day, { day, t: [], p: [], w: [] });
    const entry = days.get(day);
    if (series.temperature_2m?.[i] != null) entry.t.push(series.temperature_2m[i]);
    if (series.precipitation?.[i] != null) entry.p.push(series.precipitation[i]);
    if (series.wind_speed_10m?.[i] != null) entry.w.push(series.wind_speed_10m[i]);
  });
  return [...days.values()]
    .filter((d) => d.t.length >= 20)
    .map((d) => ({
      day: d.day,
      tmin: Math.min(...d.t),
      tmax: Math.max(...d.t),
      precipitation: d.p.length ? d.p.reduce((a, b) => a + b, 0) : null,
      wind: d.w.length ? Math.max(...d.w) : null,
    }));
}

/**
 * The forecast of the model ranked best at each hour's lead day: a different model can
 * win D+1, D+2, …; where the winner has no value for the hour (it ended), the next
 * ranked model with one. Returns [{value, model}] per hour ({null, null} without any).
 */
export function bestPerLeadDay(forecast, table, variable, now) {
  const series = forecast.values[variable] ?? {};
  return forecast.times.map((time, i) => {
    const ranked = weightsAt(table, variable, leadDay(time, now))
      .filter((r) => r.rank != null)
      .sort((a, b) => a.rank - b.rank);
    const hit = ranked.find((r) => series[r.model]?.[i] != null);
    return hit ? { value: series[hit.model][i], model: hit.model } : { value: null, model: null };
  });
}

/** The ranked-first model per lead day 1..MAX_LEAD_DAY: [{lead, model}]. */
export function winnersByLeadDay(table, variable) {
  const out = [];
  for (let lead = 1; lead <= MAX_LEAD_DAY; lead += 1) {
    const rows = table.get(`${variable}|${lead}`);
    if (rows?.length) out.push({ lead, model: rows.find((r) => r.rank === 1)?.model ?? null });
  }
  return out;
}

// --- night on the hourly charts -------------------------------------------------------

/** A local wall-clock time ("YYYY-MM-DD", "HH:MM") in a time zone as ms since the epoch. */
export function localTime(day, hhmm, timeZone = "Europe/Prague") {
  const format = new Intl.DateTimeFormat("en-GB", {
    timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
  // how far the zone's wall clock is ahead of UTC at a moment
  const offset = (at) => {
    const p = Object.fromEntries(format.formatToParts(at).map((x) => [x.type, x.value]));
    return Date.parse(`${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:00Z`) - at;
  };
  const guess = Date.parse(`${day}T${hhmm}:00Z`);
  // twice, so that a time near a DST change gets the offset that applies at it
  return guess - offset(guess - offset(guess));
}

/**
 * Nights between `start` and `end` (ms) as [{start, end}], from sunset to sunrise in
 * local time. `sunOf(day)` gives {sunrise, sunset} ("HH:MM") for a "YYYY-MM-DD" day, or
 * null. A night next to a day without sun times is estimated from the known day ±24 h
 * (a few minutes off); without any sun times there are no nights.
 */
export function nightBands(sunOf, start, end, timeZone = "Europe/Prague") {
  const days = [];
  for (let at = start - 24 * HOUR; at <= end + 24 * HOUR; at += HOUR) {
    const day = localDay(at, timeZone);
    if (days.at(-1) !== day) days.push(day);
  }
  const sun = days.map((day) => {
    const s = sunOf(day);
    return s?.sunrise && s?.sunset
      ? { rise: localTime(day, s.sunrise, timeZone), set: localTime(day, s.sunset, timeZone) }
      : null;
  });
  const nights = [];
  sun.forEach((s, i) => {
    if (!s) return;
    nights.push({ start: sun[i - 1]?.set ?? s.set - 24 * HOUR, end: s.rise });
    nights.push({ start: s.set, end: sun[i + 1]?.rise ?? s.rise + 24 * HOUR });
  });
  const merged = [];
  for (const n of nights.sort((a, b) => a.start - b.start)) {
    const clipped = { start: Math.max(start, n.start), end: Math.min(end, n.end) };
    if (clipped.end <= clipped.start) continue;
    const last = merged.at(-1);
    if (last && clipped.start <= last.end) last.end = Math.max(last.end, clipped.end);
    else merged.push(clipped);
  }
  return merged;
}
