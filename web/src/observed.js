// "What the weather was like": the measured days of the measured page (station.html), from the
// files of `mvd observed-map` (src/meteoverdict/observed_map.py,
// docs/data-sources.md#observed-map): data/scores/observed/index.json and one file per
// day with the values measured per okres and part of day, the number of stations behind
// each, and the forecast we archived for that day. Pure helpers; the page is the measured
// page (station.html: station-page.js, measured-okres.js).

import { daySymbol } from "./diary.js";

export const PARTS = ["night", "morning", "afternoon", "evening", "day"];
/** Values the map can show on a past day (the forecast's four, plus gust and sunshine). */
export const OBSERVED_LAYERS = ["temperature", "precipitation", "wind", "gust", "sunshine", "cloud"];
/** Hours of each part (a whole day 24): a part is dark with less than half of it in daylight. */
const PART_HOURS = { night: 6, morning: 6, afternoon: 6, evening: 6, day: 24 };
/** Octas → % (the files have cloud cover in %, the diary's symbol takes octas). */
const OCTAS = 12.5;

const DAY_MS = 86_400_000;
const toMs = (iso) => Date.parse(`${iso}T00:00:00Z`);
export const addDays = (iso, n) => new Date(toMs(iso) + n * DAY_MS).toISOString().slice(0, 10);
/** Whole days from `a` to `b` ("YYYY-MM-DD"). */
export const daysBetween = (a, b) => Math.round((toMs(b) - toMs(a)) / DAY_MS);

/** index.json → {days: [{day, source, leads}] oldest first, first, last, partDays, generated};
 * empty without a file. */
export function parseObservedIndex(doc) {
  const days = [...(doc?.days ?? [])].filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d?.day ?? "")).sort((a, b) => (a.day < b.day ? -1 : 1));
  return {
    days,
    byDay: new Map(days.map((d) => [d.day, d])),
    first: days[0]?.day ?? null,
    last: days.at(-1)?.day ?? null,
    partDays: doc?.part_days ?? null,
    generated: doc?.generated ?? null,
  };
}

/** The measured day nearest to `iso` (a date picked in the field, which may have no file). */
export function nearestDay(index, iso) {
  if (!index.days.length || !/^\d{4}-\d{2}-\d{2}$/.test(iso ?? "")) return null;
  let best = null;
  for (const { day } of index.days) {
    if (best == null || Math.abs(daysBetween(iso, day)) < Math.abs(daysBetween(iso, best))) best = day;
  }
  return best;
}

/** Is a part of day dark (less than half of it in daylight)? Never the whole day. */
export function isDark(part, light) {
  if (part === "day" || light == null) return part === "night";
  return light < PART_HOURS[part] / 2;
}

/**
 * The weather symbol of an okres's part of day, from what was measured, as the station
 * diary's (diary.js daySymbol): precipitation (okres mean) of at least 0.5 mm rain, sleet
 * or snow (from the day's phenomena, new snow or the temperature), else the sky from the
 * sunshine as a share of the part's daylight, else from the cloud cover; null when there
 * is neither.
 */
export function observedSymbol(row, day) {
  const diaryRow = {
    day,
    r: row.precipitation,
    ssv: row.sunshine,
    cloud: row.cloud != null ? row.cloud / OCTAS : null,
    phenomena: row.ph ?? [],
    sno: row.sno ?? null,
    tx: row.tmax,
    tn: row.tmin,
    t: null,
  };
  return daySymbol(diaryRow, null, row.light ?? null);
}

/**
 * One day's file → a view of the map (as parseOutlook's: rows by "okres|day|part"), with
 * `observed: true`, its `parts` (all five, or only "day" for a day from the daily
 * values), `stations` (count) and the archived `forecasts` (parseForecasts). Every okres
 * gets a row, with nulls where nothing was measured (grey "–" on the map).
 */
export function parseObservedDay(doc, okresy) {
  if (!doc?.day || !doc.okresy) return null;
  const parts = doc.parts ?? PARTS;
  const rows = new Map();
  const stations = new Set();
  for (const o of okresy) {
    const v = doc.okresy[o.code] ?? {};
    for (const s of v.st ?? []) stations.add(s);
    parts.forEach((part, i) => {
      const at = (key) => v[key]?.[i] ?? null;
      const row = {
        okres: o.code,
        day: doc.day,
        part,
        measured: true,
        tmax: at("tmax"),
        tmin: at("tmin"),
        tmax_hi: at("tmax_hi"),
        tmin_lo: at("tmin_lo"),
        precipitation: at("r"),
        precipitation_hi: at("r_hi"),
        wind: at("wind"),
        gust: at("gust"),
        sunshine: at("ssv"),
        cloud: at("cloud"),
        light: at("light"),
        counts: { t: at("n_t") ?? 0, r: at("n_r") ?? 0, w: at("n_w") ?? 0, g: at("n_g") ?? 0, s: at("n_s") ?? 0, c: at("n_c") ?? 0 },
        ph: v.ph ?? [],
        sno: v.sno ?? null,
        stations: v.st ?? [],
      };
      row.symbol = observedSymbol(row, doc.day);
      row.dark = isDark(part, row.light);
      rows.set(`${o.code}|${doc.day}|${part}`, row);
    });
  }
  return {
    observed: true,
    day: doc.day,
    days: [doc.day],
    source: doc.source ?? "hourly",
    parts,
    okresy,
    rows,
    stations: stations.size,
    generated: doc.generated ?? null,
    forecasts: parseForecasts(doc),
  };
}

/**
 * The archived forecasts of a day: [{lead, issued, rows: Map "okres|part" → {tmin, tmax,
 * precipitation, rain_probability, wind, gust, cloud, sunshine, symbol}}], by lead.
 */
export function parseForecasts(doc) {
  const parts = doc?.parts ?? PARTS;
  return (doc?.forecasts ?? [])
    .map((f) => {
      const rows = new Map();
      for (const [code, columns] of Object.entries(f.okresy ?? {})) {
        parts.forEach((part, i) => {
          const row = Object.fromEntries((f.columns ?? Object.keys(columns)).map((c) => [c, columns[c]?.[i] ?? null]));
          if (Object.values(row).some((v) => v != null)) rows.set(`${code}|${part}`, row);
        });
      }
      return { lead: f.lead, issued: f.issued, rows };
    })
    .sort((a, b) => a.lead - b.lead);
}

/** The forecast to show first: one day before if there is one, else the shortest lead. */
export function defaultLead(forecasts) {
  if (!forecasts?.length) return null;
  return forecasts.some((f) => f.lead === 1) ? 1 : forecasts[0].lead;
}

const best = (rows, value, better) =>
  rows.reduce((a, b) => (value(b) != null && (a == null || better(value(b), value(a))) ? b : a), null);

/**
 * Headline of a measured day and part: the warmest okres (highest maximum; at night the
 * highest minimum) and the coldest (lowest minimum), where it rained most (okres mean, and
 * the wettest station), how many okresy had at least 1 mm, the strongest gust and the
 * most sunshine; each null without values. `okresy`: okresy with any value.
 */
export function observedSummary(view, part) {
  const rows = view.okresy
    .map((o) => ({ o, row: view.rows.get(`${o.code}|${view.day}|${part}`) }))
    .filter(({ row }) => row);
  const pick = (value, better) => {
    const hit = best(rows, (r) => value(r.row), better);
    return hit && value(hit.row) != null ? { name: hit.o.name, code: hit.o.code, value: value(hit.row) } : null;
  };
  const up = (a, b) => a > b;
  const down = (a, b) => a < b;
  const measuredRain = rows.filter(({ row }) => row.precipitation != null);
  const wettest = pick((r) => r.precipitation, up);
  const station = best(rows, (r) => r.row.precipitation_hi, up);
  return {
    warmest: pick((r) => (part === "night" ? r.tmin : r.tmax), up),
    coldest: pick((r) => r.tmin, down),
    wettest,
    wettestStation: station?.row.precipitation_hi != null ? { name: station.o.name, value: station.row.precipitation_hi } : null,
    wet: measuredRain.filter(({ row }) => row.precipitation >= 1).length,
    rainOkresy: measuredRain.length,
    gust: pick((r) => r.gust, up),
    sunniest: pick((r) => r.sunshine, up),
    okresy: rows.filter(({ row }) => ["tmax", "tmin", "precipitation", "wind", "gust", "sunshine", "cloud"].some((k) => row[k] != null)).length,
    stations: view.stations,
  };
}

/** Forecast minus measured for a layer (null when either is missing). */
export function difference(forecast, measured, layer, part) {
  if (!forecast || !measured) return null;
  const pick = (row) => {
    if (layer === "temperature") return part === "night" ? row.tmin : row.tmax;
    return row[layer] ?? null;
  };
  const f = pick(forecast);
  const m = pick(measured);
  return f == null || m == null ? null : Math.round((f - m) * 10) / 10;
}
