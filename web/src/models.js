// Every model's own hourly forecast for one okres (forecast/models/<okres>.json, written
// by `mvd outlook` with each run, docs/data-sources.md#outlook-mvd-outlook-roadmap-66):
// the raw values as Open-Meteo gave them, plus our combined series. The detailed forecast
// page and the model picker of the forecast map read these files instead of asking
// Open-Meteo from the visitor's browser.
//
// A single model's parts of day and days follow the outlook's rules (outlook.summarise):
// Prague time, night 0-6, morning 6-12, afternoon 12-18, evening 18-24; precipitation
// and sunshine belong to the hour before their time; a part needs at least 4 hours, a day
// 18; tmin/tmax, the precipitation total, the highest hourly wind, the mean cloud cover
// (a whole day: of 6-18). What one model cannot give: the probability of precipitation
// (the share of wet models) is null, and its symbol is simplified (modelSymbol).

export const MODEL_VARIABLES = ["temperature_2m", "precipitation", "wind_speed_10m", "cloud_cover", "sunshine_duration"];
export const TIME_ZONE = "Europe/Prague";
const PARTS = ["night", "morning", "afternoon", "evening"];
const HOUR = 3600 * 1000;
// as meteoverdict.outlook
export const MIN_PART_HOURS = 4;
export const MIN_DAY_HOURS = 18;
export const RAIN_MM = 0.3;
export const CLEAR_BELOW = 30;
export const PARTLY_BELOW = 65;
export const SNOW_AT_OR_BELOW = 0.5;
export const SLEET_AT_OR_BELOW = 2;

/**
 * forecast/models/<okres>.json → {generated, okres, times: [ms], combined: {variable:
 * [..]}, models: {model: {variable: [..]}}}, every series as long as `times` (a model's
 * series ends at its last hour in the file: padded with null). Null without hours.
 */
export function parseModels(doc) {
  if (!Array.isArray(doc?.time) || doc.time.length === 0) return null;
  const times = doc.time.map((s) => Date.parse(s));
  const pad = (values) => times.map((_, i) => values?.[i] ?? null);
  const series = (byVariable) => Object.fromEntries(
    Object.entries(byVariable ?? {}).map(([variable, values]) => [variable, pad(values)]),
  );
  const models = Object.fromEntries(Object.entries(doc.models ?? {}).map(([model, s]) => [model, series(s)]));
  return { generated: doc.generated ?? null, okres: doc.okres ?? null, times, combined: series(doc.combined), models };
}

/** The models as forecast.js wants them: {times, values: {variable: {model: [..]}}}. */
export function asForecast(parsed, variables) {
  const values = {};
  for (const variable of variables) {
    values[variable] = {};
    for (const [model, series] of Object.entries(parsed?.models ?? {})) {
      if (series[variable]?.some((v) => v != null)) values[variable][model] = series[variable];
    }
  }
  return { times: parsed?.times ?? [], values };
}

/** The last hour (ms) a model has a temperature for, or null. */
export function modelHorizon(parsed, model) {
  const values = parsed?.models?.[model]?.temperature_2m ?? [];
  for (let i = values.length - 1; i >= 0; i -= 1) if (values[i] != null) return parsed.times[i];
  return null;
}

const localFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: TIME_ZONE, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
});

/** Local day ("YYYY-MM-DD") and part of day of a moment. */
export function localPeriod(time) {
  const p = Object.fromEntries(localFormat.formatToParts(time).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, part: PARTS[Math.floor(Number(p.hour) / 6)] };
}

/**
 * A single model's symbol, honest about what one model can say: rain (sleet, snow at a
 * mean of ≤ 2 / ≤ 0.5 °C) when its own total is at least RAIN_MM, otherwise the sky from
 * its raw cloud cover (clear < 30 %, partly cloudy < 65 %, else cloudy). No showers:
 * those come from a probability, which one model does not have.
 */
export function modelSymbol(cloud, precipitation, temperature) {
  if ((precipitation ?? 0) >= RAIN_MM) {
    if (temperature != null && temperature <= SNOW_AT_OR_BELOW) return "snow";
    if (temperature != null && temperature <= SLEET_AT_OR_BELOW) return "sleet";
    return "rain";
  }
  if (cloud == null) return null;
  if (cloud < CLEAR_BELOW) return "clear";
  return cloud < PARTLY_BELOW ? "partly" : "cloudy";
}

const sum = (values) => values.reduce((a, b) => a + b, 0);
const mean = (values) => (values.length ? sum(values) / values.length : null);

/**
 * One model's parts of day and days: Map "day|part" (part "day" for the whole day) →
 * {tmin, tmax, precipitation, rain_probability: null, wind, cloud, sunshine, symbol}.
 * A period is there only when the model covers all of its hours in the file (and at
 * least MIN_PART_HOURS / MIN_DAY_HOURS): beyond the model's horizon, or where it ends
 * inside a period, there is no row (the page shows "–").
 */
export function modelPeriods(parsed, model) {
  const series = parsed?.models?.[model];
  const out = new Map();
  if (!series) return out;
  const periods = new Map();
  const entry = (key) => {
    if (!periods.has(key)) {
      periods.set(key, { hours: 0, sumHours: 0, t: [], w: [], c: [], p: [], s: [] });
    }
    return periods.get(key);
  };
  const temperature = series.temperature_2m ?? [];
  const has = (variable) => series[variable]?.some((v) => v != null);
  parsed.times.forEach((time, i) => {
    // instants (temperature, wind, cloud) by their own time
    const at = localPeriod(time);
    for (const key of [`${at.day}|${at.part}`, `${at.day}|day`]) {
      const e = entry(key);
      e.hours += 1;
      if (temperature[i] != null) e.t.push(temperature[i]);
      if (series.wind_speed_10m?.[i] != null) e.w.push(series.wind_speed_10m[i]);
      const daytime = at.part === "morning" || at.part === "afternoon";
      if (series.cloud_cover?.[i] != null && (!key.endsWith("|day") || daytime)) e.c.push(series.cloud_cover[i]);
    }
    // sums (precipitation, sunshine) belong to the hour ending at their time
    const before = localPeriod(time - HOUR);
    for (const key of [`${before.day}|${before.part}`, `${before.day}|day`]) {
      const e = entry(key);
      e.sumHours += 1;
      if (series.precipitation?.[i] != null) e.p.push(series.precipitation[i]);
      if (series.sunshine_duration?.[i] != null) e.s.push(series.sunshine_duration[i]);
    }
  });
  const rainy = has("precipitation");
  for (const [key, e] of periods) {
    const least = key.endsWith("|day") ? MIN_DAY_HOURS : MIN_PART_HOURS;
    // the whole period, or nothing: a model ending inside it would undercount the rain
    if (e.t.length < least || e.t.length < e.hours) continue;
    if (rainy && e.p.length < e.sumHours) continue;
    const tmean = mean(e.t);
    const precipitation = rainy ? sum(e.p) : null;
    const cloud = mean(e.c);
    out.set(key, {
      tmin: Math.min(...e.t),
      tmax: Math.max(...e.t),
      precipitation,
      rain_probability: null,
      wind: e.w.length ? Math.max(...e.w) : null,
      cloud,
      sunshine: e.s.length ? sum(e.s) / 3600 : null,
      symbol: modelSymbol(cloud, precipitation, tmean),
      gust: null,
      gust_warning: null,
    });
  }
  return out;
}
