// Every model's own hourly forecast for one okres (forecast/models/<okres>.json, written
// by `mvd outlook` with each run, docs/data-sources.md#outlook-mvd-outlook-roadmap-66):
// the raw values as Open-Meteo gave them, plus our combined series. The detailed forecast
// page and the model picker of the forecast map read these files instead of asking
// Open-Meteo from the visitor's browser.
//
// A single model's parts of day and days follow the outlook's rules (outlook.summarise):
// Prague time, night 0-6, morning 6-12, afternoon 12-18, evening 18-24; precipitation
// and sunshine belong to the hour before their time; a part needs at least 4 hours, a day
// 18 (a part the model ends in its last hour still counts, see modelPeriods); tmin/tmax, the precipitation total, the highest hourly wind, the mean cloud cover
// (a whole day: of 6-18). What one model cannot give: the probability of precipitation
// (the share of wet models) is null, and its symbol is simplified (modelSymbol).

/** The outlook's gust warning threshold (m/s). */
export const GUST_THRESHOLD = 13.5;
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
 * inside a period, there is no row (the page shows "–"). One exception: a part of the
 * day whose every hour the model has, with only the rain of its very last hour missing
 * (ICON-D2 ending at 23:00 has no rain for 23-24) is shown, its rain the hours it has; a
 * whole day stays "–" then, so a day's total is never short.
 */
export function modelPeriods(parsed, model) {
  const series = parsed?.models?.[model];
  const out = new Map();
  if (!series) return out;
  const periods = new Map();
  const entry = (key) => {
    if (!periods.has(key)) {
      periods.set(key, { hours: 0, sumHours: 0, t: [], w: [], g: [], c: [], p: [], s: [], lastRain: false });
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
      if (series.wind_gusts_10m?.[i] != null) e.g.push(series.wind_gusts_10m[i]);
      const daytime = at.part === "morning" || at.part === "afternoon";
      if (series.cloud_cover?.[i] != null && (!key.endsWith("|day") || daytime)) e.c.push(series.cloud_cover[i]);
    }
    // sums (precipitation, sunshine) belong to the hour ending at their time
    const before = localPeriod(time - HOUR);
    for (const key of [`${before.day}|${before.part}`, `${before.day}|day`]) {
      const e = entry(key);
      e.sumHours += 1;
      e.lastRain = series.precipitation?.[i] != null;
      if (e.lastRain) e.p.push(series.precipitation[i]);
      if (series.sunshine_duration?.[i] != null) e.s.push(series.sunshine_duration[i]);
    }
  });
  const rainy = has("precipitation");
  for (const [key, e] of periods) {
    const whole = key.endsWith("|day");
    const least = whole ? MIN_DAY_HOURS : MIN_PART_HOURS;
    // the whole period, or nothing: a model ending inside it would undercount the rain
    if (e.t.length < least || e.t.length < e.hours) continue;
    // a part only one hour of rain short, at its end (the model's last hour): shown
    const lastHourShort = !whole && e.p.length === e.sumHours - 1 && !e.lastRain;
    if (rainy && e.p.length < e.sumHours && !lastHourShort) continue;
    const tmean = mean(e.t);
    const precipitation = rainy ? sum(e.p) : null;
    const cloud = mean(e.c);
    const gust = e.g.length ? Math.max(...e.g) : null;
    out.set(key, {
      tmin: Math.min(...e.t),
      tmax: Math.max(...e.t),
      precipitation,
      rain_probability: null,
      wind: e.w.length ? Math.max(...e.w) : null,
      cloud,
      sunshine: e.s.length ? sum(e.s) / 3600 : null,
      symbol: modelSymbol(cloud, precipitation, tmean),
      // only a series with gusts (MeteoVerdict AI's) has them; the rest of the models none
      gust,
      gust_over_threshold: gust == null ? null : gust >= GUST_THRESHOLD,
    });
  }
  return out;
}

// --- the whole map on one model: forecast/models-parts/<model>.json (all okresy, its
// parts of day and days by the same rules, written by `mvd outlook`) and index.json (the
// models by their mean rank over Czechia) -----------------------------------------------

/**
 * The map's model selector: the models of models-parts/index.json, ranked ones first by
 * their mean rank over Czechia (ties and unranked ones by name), then the unranked
 * ones. [{model, name, rank, position}], position 1.. for ranked models, null else.
 */
export function mapModelOptions(index, names = {}) {
  const name = (model) => names?.[model] ?? model;
  const entries = (index?.models ?? []).filter((m) => m?.model);
  const ranked = entries
    .filter((m) => m.mean_rank != null)
    .sort((a, b) => a.mean_rank - b.mean_rank || name(a.model).localeCompare(name(b.model), "cs"))
    .map((m, i) => ({ model: m.model, name: name(m.model), rank: m.mean_rank, position: i + 1 }));
  const others = entries
    .filter((m) => m.mean_rank == null)
    .sort((a, b) => name(a.model).localeCompare(name(b.model), "cs"))
    .map((m) => ({ model: m.model, name: name(m.model), rank: null, position: null }));
  return [...ranked, ...others];
}

/**
 * One model's file for all okresy → an outlook-like view for the map (tv.js reads it as
 * it reads outlook.json): {single: true, model, generated, lastHour (ms or null), days,
 * okresy, rows: Map "okres|day|part" → row}. The days and okresy are those of our
 * `outlook` (parseOutlook), so the tabs stay the same. A row has the model's values,
 * rain_probability null, `single: true`, and the day's sunrise and sunset from the
 * outlook (night symbols); a period the model does not cover (beyond its horizon) is a
 * row with `beyond: true` and no values, so the map greys it with "–".
 */
export function parseModelParts(doc, outlook) {
  if (!doc?.okresy || !Array.isArray(doc.days) || !Array.isArray(doc.parts)) return null;
  const columns = doc.columns ?? [];
  const symbols = doc.symbols ?? [];
  const dayIndex = new Map(doc.days.map((d, i) => [d, i]));
  const rows = new Map();
  const empty = { tmin: null, tmax: null, precipitation: null, wind: null, cloud: null, sunshine: null, symbol: null };
  for (const o of outlook.okresy) {
    const values = doc.okresy[o.code];
    for (const day of outlook.days) {
      const sun = PARTS.concat("day").map((p) => outlook.rows.get(`${o.code}|${day}|${p}`)).find((r) => r?.sunrise);
      const sunTimes = sun ? { sunrise: sun.sunrise, sunset: sun.sunset } : {};
      for (const part of [...PARTS, "day"]) {
        const d = dayIndex.get(day);
        const p = doc.parts.indexOf(part);
        const at = d == null || p < 0 ? null : d * doc.parts.length + p;
        const row = { ...empty, rain_probability: null, gust: null, gust_over_threshold: null, single: true, ...sunTimes };
        let any = false;
        for (const column of columns) {
          const v = at == null ? null : values?.[column]?.[at] ?? null;
          if (v == null) continue;
          any = true;
          row[column] = column === "symbol" ? (typeof v === "number" ? symbols[v] ?? null : v) : v;
        }
        // a model without values here: beyond its horizon (tmax is always there otherwise)
        if (!any || row.tmax == null) {
          rows.set(`${o.code}|${day}|${part}`, { ...empty, rain_probability: null, single: true, beyond: true, ...sunTimes });
        } else {
          rows.set(`${o.code}|${day}|${part}`, row);
        }
      }
    }
  }
  const last = doc.last_hour ? Date.parse(doc.last_hour) : Number.NaN;
  return {
    single: true,
    model: doc.model ?? null,
    generated: doc.generated ?? null,
    lastHour: Number.isNaN(last) ? null : last,
    days: outlook.days,
    okresy: outlook.okresy,
    rows,
  };
}
