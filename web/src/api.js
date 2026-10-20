// Open data (roadmap 6.11): static JSON and CSV files per okres, built with the site
// from the data the pages already use, so anyone can fetch "their" okres:
//   api/v1/index.json             all okresy and where their files are
//   api/v1/okresy/<code>.json     forecast (hourly and by part of day) and model ranking
//   api/v1/okresy/<code>.csv      the hourly forecast as CSV
//   api/v1/ai/okresy/<code>.json  the same forecast with temperature and wind from the AI (experimental)
//   api/v1/obce/<okres>/<id>.json hourly forecast and parts of day of one obec (test)
//   api/v1/obce/index.json        every obec: okres, id, name, position
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

/** The parts of day of one okres from an outlook file. */
function blendParts(outlook, code) {
  return records(outlook)
    .filter((r) => r.okres === code)
    .map((r) => {
      const part = Object.fromEntries(PART_FIELDS.map((k) => [k, r[k] ?? null]));
      // outlook files from before the rename only have the old name: same value in both
      part.gust_over_threshold = r.gust_over_threshold ?? r.gust_warning ?? null;
      part.gust_warning = part.gust_over_threshold;
      return part;
    });
}

/** The JSON file of one okres. */
export function okresDoc({ okres, outlook, hourly, weightsDoc, scores, meta }) {
  const series = hourly?.okresy?.[okres.code];
  const parts = blendParts(outlook, okres.code);
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
      ai_okres_json: `${SITE}/api/${VERSION}/ai/okresy/{code}.json`,
      obec_json: `${SITE}/api/${VERSION}/obce/{okres}/{id}.json`,
      obce_index: `${SITE}/api/${VERSION}/obce/index.json`,
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

// ---------------------------------------------------------------------------------------
// AI okres files: our combined forecast with temperature and wind from the MeteoVerdict AI

export const AI_METHOD =
  "Temperature and wind from the MeteoVerdict AI (experimental, unverified); everything else (precipitation, cloud, sunshine, symbol, gusts, frost, rain probability) from the combined forecast";
const AI_HOURLY = ["temperature_2m", "wind_speed_10m"];
const AI_PART_FIELDS = ["tmin", "tmax", "wind"];

/**
 * The AI file of one okres, or null where the AI has no hourly series for it. Hourly:
 * the combined series with temperature and wind replaced by the AI's where it has a value
 * for the same hour (the 80 % range of the temperature is null on those hours: it belongs
 * to the combined forecast). Parts: the combined parts with tmin, tmax and wind from the
 * AI outlook where it has a value.
 */
export function aiOkresDoc({ okres, outlook, hourly, aiForecast, aiOutlook, meta }) {
  const series = hourly?.okresy?.[okres.code];
  const ai = aiForecast?.okresy?.[okres.code];
  if (!series || !ai?.time) return null;
  const at = new Map(ai.time.map((t, i) => [t, i]));
  const h = { time: hourly.time, ...Object.fromEntries(Object.entries(series).map(([k, v]) => [k, [...v]])) };
  const usedTemperature = new Array(hourly.time.length).fill(false);
  for (const v of AI_HOURLY) {
    const values = ai[v]?.ai;
    if (!values || !h[v]) continue;
    hourly.time.forEach((t, i) => {
      const j = at.get(t);
      const x = j === undefined ? null : values[j];
      if (x == null) return;
      h[v][i] = x;
      if (v === "temperature_2m") usedTemperature[i] = true;
    });
  }
  for (const k of RANGE) if (h[k]) h[k] = h[k].map((x, i) => (usedTemperature[i] ? null : x));
  const aiRows = new Map(records(aiOutlook).filter((r) => r.okres === okres.code).map((r) => [`${r.day}|${r.part}`, r]));
  const parts = blendParts(outlook, okres.code).map((part) => {
    const row = aiRows.get(`${part.day}|${part.part}`);
    for (const k of AI_PART_FIELDS) if (row && row[k] != null) part[k] = row[k];
    delete part.gust_warning;
    return part;
  });
  const sources = {
    ...Object.fromEntries(HOURLY.map((v) => [v, AI_HOURLY.includes(v) ? "ai" : "blend"])),
    ...Object.fromEntries(PART_FIELDS.filter((k) => k !== "gust_warning" && !["day", "part", "sunrise", "sunset"].includes(k)).map((k) => [k, AI_PART_FIELDS.includes(k) ? "ai" : "blend"])),
  };
  return {
    api: `MeteoVerdict open data ${VERSION}`,
    docs: DOCS,
    licence: LICENCE,
    attribution: meta?.attribution ?? null,
    notice: NOTICE,
    okres: { code: okres.code, name: okres.name, lat: okres.lat, lon: okres.lon },
    forecast: {
      model: "ai",
      generated: hourly?.generated ?? outlook?.generated ?? null,
      ai_issued: aiForecast.issued ?? null,
      method: AI_METHOD,
      sources,
      time_zone_of_parts: outlook?.time_zone ?? "Europe/Prague",
      units: hourly?.variables ?? null,
      hourly: h,
      parts,
    },
  };
}

// ---------------------------------------------------------------------------------------
// Obec files (test): the combined forecast of one obec on the hourly axis of its okres

const HOUR = 3600e3;
const ZONE = "Europe/Prague";
// part of day → [first, last+1] local hour; the whole day is 0–24
const PART_HOURS = { night: [0, 6], morning: [6, 12], afternoon: [12, 18], evening: [18, 24], day: [0, 24] };
// hours a part needs (a part 4, a whole day 18), as in `mvd outlook`
const MIN_HOURS = { night: 4, morning: 4, afternoon: 4, evening: 4, day: 18 };
const parts_fmt = new Intl.DateTimeFormat("en-CA", { timeZone: ZONE, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit" });
const OBEC_ATTRIBUTION_EXTRA = " Obec elevation: Copernicus DEM GLO-90 (© DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA).";

/** Local (Prague) date and hour of an instant in ms. */
function local(ms) {
  const p = Object.fromEntries(parts_fmt.formatToParts(ms).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) };
}

/** URL part of an obec: lowercase ASCII, other runs "-". */
export function slug(name) {
  const s = String(name ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || "obec";
}

/** Ids of the places of one okres: the slug, "-2", "-3" … on duplicates (largest first). */
export function obecIds(places) {
  const order = places.map((p, i) => i).sort((a, b) => (places[b].population ?? 0) - (places[a].population ?? 0) || a - b);
  const used = new Set();
  const ids = new Array(places.length);
  for (const i of order) {
    const base = slug(places[i].name);
    let id = base;
    for (let n = 2; used.has(id); n++) id = `${base}-${n}`;
    used.add(id);
    ids[i] = id;
  }
  return ids;
}

/**
 * One variable of an obec on the okres axis. An hour the obec has: its value. Between
 * two of its hours at most 3 h apart (`interpolate`): the straight line. Otherwise the
 * okres value plus the mean difference obec minus okres. Where the okres has no value:
 * null. Returns [values, offset].
 */
function onAxis(times, okres, sample, { interpolate, offset: useOffset, floor, digits }) {
  const own = times.map((ms, i) => (okres[i] == null ? undefined : sample.get(ms)));
  let sum = 0, n = 0;
  times.forEach((ms, i) => {
    const v = sample.get(ms);
    if (v != null && okres[i] != null) { sum += v - okres[i]; n++; }
  });
  const offset = useOffset && n ? sum / n : 0;
  const known = [...sample.entries()].filter(([, v]) => v != null).sort((a, b) => a[0] - b[0]);
  const values = times.map((ms, i) => {
    if (okres[i] == null) return null;
    let v = own[i];
    if (v == null && interpolate) {
      // last known at or before, first known after (binary search)
      let lo = 0, hi = known.length;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (known[mid][0] < ms) lo = mid + 1; else hi = mid; }
      const prev = known[lo - 1], next = known[lo];
      if (prev && next && next[0] - prev[0] <= 3 * HOUR) v = prev[1] + ((next[1] - prev[1]) * (ms - prev[0])) / (next[0] - prev[0]);
    }
    if (v == null) v = okres[i] + offset;
    if (floor != null) v = Math.max(floor, v);
    return round(v, digits);
  });
  return [values, offset];
}

/** Hourly series and parts of day of one place on the axis of an okres file. */
export function obecForecast(place, times, okresHourly, okresParts) {
  const stamp = (t) => Date.parse(t); // "2026-10-20T12:00Z" and "2026-10-20T12:00+00:00"
  const sampleOf = (v) => new Map(place.times.map((t, i) => [stamp(t), place[v]?.[i] ?? null]));
  const ms = times.map(stamp);
  const [temperature_2m, tOffset] = onAxis(ms, okresHourly.temperature_2m, sampleOf("temperature_2m"), { interpolate: true, offset: true, digits: 1 });
  const [wind_speed_10m] = onAxis(ms, okresHourly.wind_speed_10m, sampleOf("wind_speed_10m"), { interpolate: true, offset: true, floor: 0, digits: 1 });
  // precipitation is the amount in the hour ending at the time, hourly in the obec file:
  // the obec's own value, the okres's where it has none
  const [precipitation] = onAxis(ms, okresHourly.precipitation, sampleOf("precipitation"), { interpolate: false, offset: false, digits: 2 });
  const hours = ms.map((m) => local(m)); // hour starting at the time (temperature, wind)
  const ending = ms.map((m) => local(m - 60e3)); // hour ending at the time (precipitation)
  const diff = temperature_2m.map((v, i) => (v == null || okresHourly.temperature_2m[i] == null ? null : v - okresHourly.temperature_2m[i]));
  // the night a date ends (18–06 UTC), as for the frost fields of the okres file
  const nightDiff = (day) => {
    const end = Date.parse(`${day}T06:00Z`);
    const d = ms.map((m, i) => (m >= end - 12 * HOUR && m < end ? diff[i] : null)).filter((x) => x != null);
    return d.length ? d.reduce((a, b) => a + b, 0) / d.length : null;
  };
  const parts = okresParts.map((row) => {
    const [a, b] = PART_HOURS[row.part] ?? [0, 24];
    const inside = (h) => h.day === row.day && h.hour >= a && h.hour < b;
    const T = [], W = [], P = [];
    ms.forEach((_, i) => {
      if (inside(hours[i]) && temperature_2m[i] != null) { T.push(temperature_2m[i]); W.push(wind_speed_10m[i]); }
      if (inside(ending[i]) && precipitation[i] != null) P.push(precipitation[i]);
    });
    const enough = T.length >= (MIN_HOURS[row.part] ?? 4);
    const out = {
      day: row.day,
      part: row.part,
      tmin: enough && row.tmin != null ? Math.min(...T) : null,
      tmax: enough && row.tmax != null ? Math.max(...T) : null,
      precipitation: enough && row.precipitation != null ? round(P.reduce((x, y) => x + y, 0), 1) : null,
      wind: enough && row.wind != null ? Math.max(...W) : null,
    };
    const dn = row.night_min != null || row.ground_min != null ? nightDiff(row.day) : null;
    if (row.night_min != null && dn != null) { out.night_min = round(row.night_min + dn, 1); out.frost = out.night_min <= 1; }
    if (row.ground_min != null && dn != null) { out.ground_min = round(row.ground_min + dn, 1); out.ground_frost = out.ground_min <= 0; }
    return out; // night_min, frost, ground_min, ground_frost only on the rows that have them
  });
  return { hourly: { start: times[0], step_hours: 1, hours: times.length, temperature_2m, precipitation, wind_speed_10m }, parts, temperature_offset: tOffset };
}

/** The files of the obce of one okres: [{id, doc}] (docs/open-data.md). */
export function obceDocs({ okresDoc: doc, obceFile, meta }) {
  const h = doc?.forecast?.hourly;
  if (!h || !obceFile?.places?.length) return [];
  const ids = obecIds(obceFile.places);
  return obceFile.places.map((place, i) => {
    const f = obecForecast({ ...place, times: obceFile.times }, h.time, h, doc.forecast.parts);
    return {
      id: ids[i],
      doc: {
        api: `MeteoVerdict open data ${VERSION}`,
        docs: DOCS,
        licence: LICENCE,
        attribution: `${meta?.attribution ?? ""}${OBEC_ATTRIBUTION_EXTRA}`.trim(),
        notice: NOTICE,
        test: true,
        obec: { id: ids[i], name: place.name, okres: doc.okres.code, lat: place.lat, lon: place.lon, elevation: place.elevation ?? null },
        generated: obceFile.generated ?? null,
        hourly: f.hourly,
        parts: f.parts,
      },
    };
  });
}

/** api/v1/obce/index.json: every obec as [okres, id, name, lat, lon]. */
export function obceIndexDoc(rows, generated) {
  return {
    api: `MeteoVerdict open data ${VERSION}`,
    licence: LICENCE,
    test: true,
    generated,
    url: `${SITE}/api/${VERSION}/obce/{okres}/{id}.json`,
    obce: rows,
  };
}
