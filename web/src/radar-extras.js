// Pure helpers of the radar page's extras: rain at a point (pixel of a place, the series
// and the sentence), satellite product by day or night, storm cells as map shapes, the
// timeline's hour ticks and "how long ago" labels.

import { categoryOf, isAloft, levelDbz, levelOf } from "./radar-palette.js";
import { parseStamp, rainRate } from "./radar.js";

const R = 6378137;
const mercY = (lat) => R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

/** Grid cell (column, row) of a place on a Web Mercator image with `bounds`, or null outside. */
export function lonLatToPixel(lon, lat, bounds, w, h) {
  const x = ((lon - bounds.west) / (bounds.east - bounds.west)) * w;
  const y = ((mercY(bounds.north) - mercY(lat)) / (mercY(bounds.north) - mercY(bounds.south))) * h;
  const col = Math.floor(x);
  const row = Math.floor(y);
  return col >= 0 && col < w && row >= 0 && row < h ? { col, row } : null;
}

/** One sample of the point series from a frame code: level, rain rate, aloft. */
export function sample(time, code, forecast = false) {
  const level = levelOf(code);
  const aloft = level > 0 && isAloft(code);
  return { time, level, aloft, forecast, rate: level ? rainRate(levelDbz(level)) : 0 };
}

const wet = (s) => s.level > 0 && !s.aloft;
const strongest = (list) => list.reduce((best, s) => (s.level > (best?.level ?? 0) ? s : best), null);
const roundTo5 = (min) => Math.max(5, Math.round(min / 5) * 5);

/**
 * What the series says about the next hour at a place, as an i18n key and its values:
 *   {key: "now", cat, rate, then: "stops" | "continues" | null, min}
 *   {key: "expected", cat, min}   rain reaching the ground in about `min` minutes
 *   {key: "aloft"}                only echoes aloft (virga), nothing on the ground
 *   {key: "dry"} / {key: "dryNoForecast"}
 * `anchor` is the time of the newest measured frame; samples after it are the nowcast.
 */
export function nowcastSentence(series, anchor, categories = undefined) {
  const observed = series.filter((s) => !s.forecast && s.time <= anchor);
  const current = observed.at(-1);
  const future = series.filter((s) => s.forecast && s.time > anchor);
  if (current && wet(current)) {
    const stop = future.find((s) => !wet(s));
    const peak = strongest([current, ...future.filter(wet)]);
    return {
      key: "now",
      cat: categoryOf(current.level, categories),
      peak: categoryOf(peak.level, categories),
      rate: current.rate,
      then: future.length ? (stop ? "stops" : "continues") : null,
      min: stop ? roundTo5((stop.time - anchor) / 60000) : null,
    };
  }
  const first = future.find(wet);
  if (first) {
    return { key: "expected", cat: categoryOf(strongest(future.filter(wet)).level, categories), min: roundTo5((first.time - anchor) / 60000) };
  }
  if ((current && current.aloft) || future.some((s) => s.aloft)) return { key: "aloft", forecast: future.length > 0 };
  return { key: future.length ? "dry" : "dryNoForecast" };
}

// --- satellite ------------------------------------------------------------------------

/** Solar elevation in degrees (NOAA's low-accuracy formula, good to about 1°). */
export function sunElevation(ms, lat, lon) {
  const rad = Math.PI / 180;
  const days = ms / 86400000 + 2440587.5 - 2451545.0;
  const g = (357.529 + 0.98560028 * days) * rad;
  const q = 280.459 + 0.98564736 * days;
  const L = (q + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 0.00000036 * days) * rad;
  const decl = Math.asin(Math.sin(e) * Math.sin(L));
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L)) / rad;
  const gmst = (18.697374558 + 24.06570982441908 * days) % 24;
  const hourAngle = ((gmst * 15 + lon - ra) % 360) * rad;
  return Math.asin(Math.sin(lat * rad) * Math.sin(decl) + Math.cos(lat * rad) * Math.cos(decl) * Math.cos(hourAngle)) / rad;
}

export const CENTRE = { lat: 49.8, lon: 15.5 };

/**
 * Satellite product to show: "clouds" means visible + infrared while the sun is at least
 * `minSun`° high over Czechia, else the night microphysics; "wv" the water vapour.
 * Falls back to any available product; null when there is none.
 */
export function satelliteProduct(mode, ms, available, minSun = 5) {
  // available: product names, or index.json `satellite` (products without frames do not count)
  if (available && !Array.isArray(available)) {
    available = Object.entries(available).filter(([, m]) => m?.frames?.length).map(([p]) => p);
  }
  const has = (p) => available?.includes(p);
  if (!mode || mode === "off" || !available?.length) return null;
  if (mode === "wv") return has("wv062") ? "wv062" : null;
  const day = sunElevation(ms, CENTRE.lat, CENTRE.lon) >= minSun;
  const wanted = day ? ["vis-ir", "night-M"] : ["night-M", "vis-ir"];
  return wanted.find(has) ?? null;
}

/** The frames around `ms` (at most `maxMin` away) and the fraction between them, for a cross-fade. */
export function bracket(stamps, ms, maxMin = 30) {
  const times = (stamps ?? []).map((s) => [s, parseStamp(s)]).filter(([, t]) => t != null).sort((a, b) => a[1] - b[1]);
  let before = null;
  let after = null;
  for (const st of times) {
    if (st[1] <= ms) before = st;
    else if (!after) after = st;
  }
  if (before && ms - before[1] > maxMin * 60000) before = null;
  if (after && after[1] - ms > maxMin * 60000) after = null;
  if (before && after) return { a: before[0], b: after[0], tau: (ms - before[1]) / (after[1] - before[1]) };
  const only = before ?? after;
  return only ? { a: only[0], b: null, tau: 0 } : null;
}

// --- storm cells ----------------------------------------------------------------------

/** A point `km` away towards `bearing` (degrees from north), flat-earth (fine for < 100 km). */
export function destination(lon, lat, km, bearing) {
  const b = (bearing * Math.PI) / 180;
  const dLat = (km * Math.cos(b)) / 111.32;
  const dLon = (km * Math.sin(b)) / (111.32 * Math.cos((lat * Math.PI) / 180));
  return [lon + dLon, lat + dLat];
}

/**
 * GeoJSON of the cells `offsetMin` minutes after their frame (moved along their motion):
 * points (with the cell's properties), arrows of the next `arrowMin` minutes and tracks.
 */
export function cellFeatures(cells, offsetMin = 0, arrowMin = 30) {
  const features = [];
  for (const c of Array.isArray(cells) ? cells : []) {
    if (!Number.isFinite(c?.lon) || !Number.isFinite(c?.lat)) continue;
    const speed = Number.isFinite(c.speed_kmh) ? c.speed_kmh : 0;
    const dir = Number.isFinite(c.dir_deg) ? c.dir_deg : 0;
    const here = offsetMin && speed ? destination(c.lon, c.lat, (speed * offsetMin) / 60, dir) : [c.lon, c.lat];
    const properties = {
      id: String(c.id ?? ""), max_dbz: c.max_dbz ?? null, echotop_km: c.echotop_km ?? null,
      area_km2: c.area_km2 ?? null, speed_kmh: speed, dir_deg: dir, hail: Boolean(c.hail),
    };
    features.push({ type: "Feature", properties: { ...properties, kind: "cell" }, geometry: { type: "Point", coordinates: here } });
    if (speed >= 3) {
      const tip = destination(here[0], here[1], (speed * arrowMin) / 60, dir);
      const head = Math.min(4, (speed * arrowMin) / 60 / 3);
      const left = destination(tip[0], tip[1], head, dir + 150);
      const right = destination(tip[0], tip[1], head, dir - 150);
      features.push({
        type: "Feature",
        properties: { ...properties, kind: "arrow" },
        geometry: { type: "MultiLineString", coordinates: [[here, tip], [left, tip, right]] },
      });
    }
    const track = (c.track ?? []).filter((p) => Array.isArray(p) && p.length >= 2);
    if (track.length >= 2) {
      features.push({ type: "Feature", properties: { ...properties, kind: "track" }, geometry: { type: "LineString", coordinates: track } });
    }
  }
  return { type: "FeatureCollection", features };
}

/** Compass point of a direction of motion: 0 → "N", 100 → "E", 225 → "SW". */
export function compass(deg) {
  const points = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  return points[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}

// --- time labels -------------------------------------------------------------------------

/**
 * How a time relates to now: {key: "now"} within a minute, {key: "minAgo"|"minIn", n}
 * under two hours, {key: "hAgo"|"hIn", n}, else {key: "days", n}.
 */
export function relativeTime(ms, now) {
  const min = Math.round((now - ms) / 60000);
  if (Math.abs(min) < 1) return { key: "now" };
  const past = min > 0;
  const abs = Math.abs(min);
  if (abs < 120) return { key: past ? "minAgo" : "minIn", n: abs };
  if (abs < 48 * 60) return { key: past ? "hAgo" : "hIn", n: Math.round(abs / 60) };
  return { key: past ? "daysAgo" : "daysIn", n: Math.round(abs / 1440) };
}

/** Prague hour (0 … 23) of a time. */
function pragueHour(ms) {
  return Number(new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: "Europe/Prague" }).format(ms));
}

/**
 * Full Prague hours between `first` and `last` for the timeline's labels, every 1, 2, 3
 * or 6 hours so that at most `maxLabels` are shown. [{ms, hour}]
 */
export function hourTicks(first, last, maxLabels = 7) {
  if (!(last > first)) return [];
  const hours = (last - first) / 3600000;
  const every = [1, 2, 3, 6].find((n) => hours / n <= maxLabels) ?? 12;
  const ticks = [];
  for (let ms = Math.ceil(first / 3600000) * 3600000; ms <= last; ms += 3600000) {
    // Prague is a whole number of hours off UTC, so UTC full hours are Prague full hours
    const hour = pragueHour(ms);
    if (hour % every === 0) ticks.push({ ms, hour });
  }
  return ticks;
}
