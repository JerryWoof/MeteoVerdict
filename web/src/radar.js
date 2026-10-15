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
    hours: HOURS.includes(Number(hours)) ? Number(hours) : 3,
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
