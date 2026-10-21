// Pure helpers of the radar page (radar.html): frame names, timeline, bounds, legend,
// URL state. The frames are ČHMÚ radar composites, cropped by `mvd radar-live` and
// `mvd archive-radar` to the data grid (docs/data-sources.md#radar-archive).

/** Outer edges of the ČHMÚ composite grid (HDF5 /where, Web Mercator, 598 x 378 cells). */
export const GRID = { west: 11.266869, south: 48.047275, east: 19.623974, north: 51.458369 };

/** Corners for a MapLibre image source: top left, top right, bottom right, bottom left. */
export function imageCoordinates(bounds = GRID) {
  const { west, south, east, north } = bounds;
  return [
    [west, north],
    [east, north],
    [east, south],
    [west, south],
  ];
}

/** Bounds from an index.json ([[west, south], [east, north]]), else the known grid. */
export function boundsOf(index) {
  const b = index?.bounds;
  if (!Array.isArray(b) || b.length !== 2) return GRID;
  return { west: b[0][0], south: b[0][1], east: b[1][0], north: b[1][1] };
}

/** "202610151035" (UTC) → milliseconds. */
export function parseStamp(stamp) {
  const m = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})$/.exec(stamp ?? "");
  if (!m) return null;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
}

/** Milliseconds → "202610151035" (UTC). */
export function toStamp(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}${p(d.getUTCHours())}${p(d.getUTCMinutes())}`;
}

/** "2026-10-14" → "20261014" (the folder of an archived day). */
export const dayFolder = (day) => day.replaceAll("-", "");

// The archive's folders are UTC days (ČHMÚ's stamps are UTC), but a day picked on the page is a
// day in Prague: 00:00–24:00 there is 22:00 (21:00 in winter) of the UTC day before to 22:00
// (21:00) of the day. So the page reads the day's folder and the one before, keeps the frames
// of the Prague day from both (pragueDayIndex), and takes each frame from the folder of its own
// UTC day (frameFolder). The day's last two hours in its folder belong to the next Prague day.

/** Milliseconds Prague's clock is ahead of UTC at `ms` (1 or 2 hours). */
function zoneOffset(ms, timeZone) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(ms);
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  return Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute")) - Math.floor(ms / 60000) * 60000;
}

/** The calendar day "2026-10-19" in Prague as UTC milliseconds {from, to}, `to` excluded (23, 24 or 25 hours). */
export function pragueDayWindow(day, timeZone = "Europe/Prague") {
  const [y, m, d] = day.split("-").map(Number);
  // local midnight: UTC midnight less the offset there (midnight is never in a clock change)
  const midnight = (dd) => {
    let ms = Date.UTC(y, m - 1, dd);
    for (let i = 0; i < 2; i++) ms = Date.UTC(y, m - 1, dd) - zoneOffset(ms, timeZone);
    return ms;
  };
  return { from: midnight(d), to: midnight(d + 1) };
}

/** "2026-10-19" → "2026-10-18". */
export function previousDay(day) {
  return new Date(Date.parse(`${day}T00:00:00Z`) - 86400000).toISOString().slice(0, 10);
}

const STAMP_LISTS = ["maxz", "merge1h", "echotop", "motion", "cells"];

/**
 * The index of a Prague day from the index.json of its UTC day (`own`) and of the UTC day
 * before (`before`, may be null): every frame list, the satellite's too, cut to `window`
 * ({from, to}, pragueDayWindow). Null when the day's own index is missing.
 */
export function pragueDayIndex(own, before, { from, to }) {
  if (!own) return null;
  const inDay = (stamp) => {
    const ms = parseStamp(stamp);
    return ms != null && ms >= from && ms < to;
  };
  const merge = (a, b) => [...new Set([...(a ?? []), ...(b ?? [])])].filter(inDay).sort();
  const out = { ...own };
  for (const key of STAMP_LISTS) if (own[key] || before?.[key]) out[key] = merge(before?.[key], own[key]);
  if (own.satellite || before?.satellite) {
    out.satellite = {};
    for (const product of new Set([...Object.keys(before?.satellite ?? {}), ...Object.keys(own.satellite ?? {})])) {
      const meta = own.satellite?.[product] ?? before.satellite[product];
      out.satellite[product] = { ...meta, frames: merge(before?.satellite?.[product]?.frames, own.satellite?.[product]?.frames) };
    }
  }
  return out;
}

/** The folder of a frame: the live one, or the archived UTC day the frame's stamp is in. */
export function frameFolder(stamp, day, liveBase, siteBase = "radar/") {
  if (day === "live") return liveBase;
  return `${siteBase}days/${String(stamp).slice(0, 8)}/`;
}

/** URL of one frame: `<base><layer>/<stamp>.png`. */
export const frameUrl = (base, layer, stamp) => `${base}${layer}/${stamp}.png`;

/** Folder of an archived day on the site, or the live folder. */
export function sourceUrl(day, liveBase, siteBase = "radar/") {
  return day === "live" ? liveBase : `${siteBase}days/${dayFolder(day)}/`;
}

/** The newest stamp in `stamps` at or before `ms` and at most `maxAgeMin` older, else null. */
export function latestAtOrBefore(stamps, ms, maxAgeMin = 60) {
  let best = null;
  for (const s of stamps ?? []) {
    const t = parseStamp(s);
    if (t != null && t <= ms && ms - t <= maxAgeMin * 60000 && (best == null || t > parseStamp(best))) best = s;
  }
  return best;
}

/**
 * The steps of the time slider: the radar frames (of the last `hours` hours of the
 * index when given), then the nowcast frames after the last radar frame. Every step
 * has the MERGE frame (1-hour precipitation) valid then, if any.
 *   {time, radar, rain, forecast, lead}
 */
/** A nowcast older than this (from its base to the newest measured image) is not shown. */
export const NOWCAST_MAX_AGE = 20 * 60000;

export function timeline(index, { hours = null } = {}) {
  const radarStamps = [...(index?.maxz ?? [])].sort();
  const rainStamps = index?.merge1h ?? [];
  const last = parseStamp(radarStamps.at(-1));
  const from = hours != null && last != null ? last - hours * 3600000 : -Infinity;
  const steps = radarStamps
    .map((s) => ({ time: parseStamp(s), radar: s, forecast: false, lead: 0 }))
    .filter((s) => s.time != null && s.time > from - 1);
  const lastObserved = steps.at(-1)?.time ?? -Infinity;
  // ČHMÚ's nowcast only when it starts from (nearly) the newest measured image: an old
  // one would show a "forecast" that is already past; then the animation ends at now
  const base = parseStamp(index?.nowcast?.base);
  const fresh = base != null && lastObserved - base <= NOWCAST_MAX_AGE;
  for (const f of fresh ? index.nowcast.frames ?? [] : []) {
    const time = parseStamp(f.time);
    if (time != null && time > lastObserved) steps.push({ time, radar: f.time, forecast: true, lead: f.lead });
  }
  // the rain layer never shows a forecast: during the nowcast it keeps the last sum
  for (const s of steps) s.rain = latestAtOrBefore(rainStamps, Math.min(s.time, lastObserved));
  return steps;
}

/** Index of the step closest to `ms` (the last one when `ms` is null). */
export function closestStep(steps, ms) {
  if (!steps.length) return -1;
  if (ms == null) {
    const now = steps.findLastIndex((s) => !s.forecast);
    return now >= 0 ? now : steps.length - 1;
  }
  let best = 0;
  for (let i = 1; i < steps.length; i++) {
    if (Math.abs(steps[i].time - ms) < Math.abs(steps[best].time - ms)) best = i;
  }
  return best;
}

/** "10:35" in Prague time (the page is for Czechia), 24-hour clock. */
export function clock(ms, timeZone = "Europe/Prague") {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone }).format(ms);
}

/** "2026-10-14" of `ms` in Prague time. */
export function localDay(ms, timeZone = "Europe/Prague") {
  return new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone }).format(ms);
}

/** Minutes between two times, rounded down, never negative ("5 min ago"; clocks differ). */
export const minutesBetween = (earlier, later) => Math.max(0, Math.floor((later - earlier) / 60000));

// ČHMÚ colour scales (opendata.chmi.cz/meteorology/weather/radar/scl/), bottom to top:
// each colour from its value up to the next one.
export const DBZ_SCALE = [
  [4, "#380070"], [8, "#3000a8"], [12, "#0000fc"], [16, "#006cc0"], [20, "#00a000"],
  [24, "#00bc00"], [28, "#34d800"], [32, "#9cdc00"], [36, "#e0dc00"], [40, "#fcb000"],
  [44, "#fc8400"], [48, "#fc5800"], [52, "#fc0000"], [56, "#a00000"], [60, "#fcfcfc"],
];
export const MM_SCALE = [
  [0.1, "#380070"], [0.3, "#3000a8"], [0.6, "#0000fc"], [1, "#006cc0"], [2, "#00a000"],
  [4, "#00bc00"], [6, "#34d800"], [10, "#9cdc00"], [15, "#e0dc00"], [20, "#fcb000"],
  [30, "#fc8400"], [40, "#fc5800"], [60, "#fc0000"], [80, "#a00000"], [100, "#fcfcfc"],
];

/** Rain rate (mm/h) for a reflectivity, Marshall-Palmer Z = 200 R^1.6 (as on ČHMÚ's scale). */
export function rainRate(dbz) {
  return (10 ** (dbz / 10) / 200) ** (1 / 1.6);
}

/** Legend numbers in English format: "0.1", "1", "15" (never a decimal comma). */
export function legendNumber(value) {
  return value < 1 ? value.toFixed(1) : String(Math.round(value * 10) / 10);
}

/** Map layers in the URL: radar, 1-hour sums, echo tops, storm cells, satellite clouds, water vapour. */
export const LAYERS = ["radar", "rain", "echotop", "cells", "sat", "wv"];
export const HOURS = [1, 3, 6, 24];
const FILTERS = ["all", "light", "moderate", "heavy", "hail"];

/**
 * "#live/3/radar+rain/202610151035/moderate" → view state. The time may be "now" (the
 * newest frame) and the last part, the "show from" setting, may be left out.
 */
export function parseView(hash) {
  const [day, hours, layers, time, filter] = (hash ?? "").replace(/^#/, "").split("/");
  const shown = (layers ?? "").split("+").filter((l) => LAYERS.includes(l));
  // one satellite product at a time
  const layerList = shown.includes("sat") && shown.includes("wv") ? shown.filter((l) => l !== "wv") : shown;
  return {
    day: /^\d{4}-\d{2}-\d{2}$/.test(day ?? "") ? day : "live",
    hours: HOURS.includes(Number(hours)) ? Number(hours) : 24,
    layers: layers === undefined ? ["radar"] : layerList,
    time: parseStamp(time) != null ? time : null,
    filter: FILTERS.includes(filter) ? filter : null,
  };
}

export function viewHash(view) {
  const parts = [view.day, String(view.hours), view.layers.join("+")];
  if (view.time || (view.filter && view.filter !== "all")) parts.push(view.time ?? "now");
  if (view.filter && view.filter !== "all") parts.push(view.filter);
  return `#${parts.join("/")}`;
}
