// Pixel colours of the radar frames ↔ intensity classes, and the colour tables the
// radar page draws with. The frames are ČHMÚ's palette PNGs (docs/data-sources.md#radar-
// page-frames): MAX_Z "png_masked" has 15 solid colours (4, 8, … 60 dBZ), the same 15
// colours lighter for echoes that probably do not reach the ground, and a faint grey
// outside the radar coverage. MERGE (1-hour sums) uses the solid colours for 0.1 … 100 mm.
//
// A decoded frame is a Uint8Array of codes, one per grid cell:
//   0 = no echo, 1 … 15 = class (level) k, + ALOFT (32) when lighter, NODATA (64) = no coverage.

import { DBZ_SCALE, MM_SCALE, rainRate } from "./radar.js";

export const ALOFT = 32;
export const NODATA = 64;
export const LEVELS = DBZ_SCALE.length; // 15

/** The lighter colours of png_masked (palette indexes 135 … 121), 4 … 60 dBZ. */
export const ALOFT_COLOURS = [
  "#8b6ea8", "#9a8dba", "#b1b1d0", "#98afc1", "#89b889", "#96c096", "#abc7a2", "#bec8a4",
  "#c9c9a6", "#d0c7b1", "#d0c1b1", "#d0bcb1", "#d0b1b1", "#b88989", "#fefefe",
];

export const levelOf = (code) => (code & NODATA ? 0 : code & 31);
export const isAloft = (code) => (code & ALOFT) !== 0;
/** Class of a reflectivity: 4 dBZ → 1, 8 → 2, … 60+ → 15; below 4 → 0. */
export const dbzLevel = (dbz) => (dbz < 4 ? 0 : Math.min(LEVELS, Math.floor((dbz - 4) / 4) + 1));
export const levelDbz = (level) => (level > 0 ? DBZ_SCALE[level - 1][0] : null);

export function hexRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/**
 * Colour → code for opaque pixels: exact matches first (the palette), else the nearest
 * known colour (memoised), so slightly different decoders still classify every pixel.
 */
export function makeClassifier(solid = DBZ_SCALE.map(([, c]) => c), aloft = ALOFT_COLOURS) {
  const known = [];
  solid.forEach((hex, i) => known.push([hexRgb(hex), i + 1]));
  aloft.forEach((hex, i) => known.push([hexRgb(hex), (i + 1) | ALOFT]));
  known.push([[196, 196, 196], NODATA]);
  const memo = new Map();
  for (const [[r, g, b], code] of known) memo.set((r << 16) | (g << 8) | b, code);
  return function classify(r, g, b, a) {
    if (a === 0) return 0;
    if (a < 255) return NODATA; // the faint grey outside the coverage
    const key = (r << 16) | (g << 8) | b;
    let code = memo.get(key);
    if (code === undefined) {
      let best = Infinity;
      for (const [[kr, kg, kb], c] of known) {
        const d = (r - kr) ** 2 + (g - kg) ** 2 + (b - kb) ** 2;
        if (d < best) [best, code] = [d, c];
      }
      memo.set(key, code);
    }
    return code;
  };
}

const defaultClassifier = makeClassifier();

/** RGBA bytes (ImageData.data) → codes. */
export function decodePixels(rgba, classify = defaultClassifier) {
  const codes = new Uint8Array(rgba.length / 4);
  for (let i = 0, p = 0; i < codes.length; i++, p += 4) {
    codes[i] = rgba[p + 3] === 0 ? 0 : classify(rgba[p], rgba[p + 1], rgba[p + 2], rgba[p + 3]);
  }
  return codes;
}

// --- what the colours mean -----------------------------------------------------------

/** Plain-language groups of the reflectivity classes (lower bound in dBZ). */
export const CATEGORIES = [
  { key: "drizzle", dbz: 4 },
  { key: "light", dbz: 20 },
  { key: "moderate", dbz: 28 },
  { key: "heavy", dbz: 40 },
  { key: "veryHeavy", dbz: 48 },
  { key: "hail", dbz: 56 },
];

const LABEL_KEYS = {
  drizzle: "drizzle", light: "light", moderate: "moderate", heavy: "heavy", "very heavy": "veryHeavy",
  "hail possible": "hail", hail: "hail",
};
/** Category key of an English label of index.json `scales.maxz` ("very heavy" → "veryHeavy"), else null. */
export const labelKey = (label) => LABEL_KEYS[String(label ?? "").trim().toLowerCase()] ?? null;

/**
 * The categories as the backend labels the classes (`scales.maxz`), so the legend, the
 * filter and the sentences agree; ours when it sends none or labels we do not know.
 */
export function categoriesFrom(scale) {
  if (!Array.isArray(scale) || !scale.length) return CATEGORIES;
  const order = CATEGORIES.map((c) => c.key);
  const found = [];
  for (const row of scale) {
    const key = labelKey(row?.[3]);
    if (!key || !Number.isFinite(row[0])) return CATEGORIES;
    if (found.at(-1)?.key !== key) found.push({ key, dbz: row[0] });
  }
  const ranks = found.map((c) => order.indexOf(c.key));
  return ranks.every((r, i) => i === 0 || r > ranks[i - 1]) ? found : CATEGORIES;
}

/** Category key of a class (level 1 … 15), null for none. */
export function categoryOf(level, categories = CATEGORIES) {
  if (!level) return null;
  const dbz = levelDbz(level);
  return (categories.findLast((c) => c.dbz <= dbz) ?? categories[0]).key;
}

/**
 * "Show from" settings: the weakest class shown on the radar (from the category's lower
 * bound) and on the 1-hour sums (MM_SCALE class), and whether echoes aloft stay.
 */
const RAIN_FROM = { all: 1, light: 3, moderate: 5, heavy: 8, hail: 11 }; // 0.1, 0.6, 2, 10, 30 mm
export const FILTER_KEYS = ["all", "light", "moderate", "heavy", "hail"];
export function filterLevels(filter, categories = CATEGORIES) {
  if (filter === "all" || !FILTER_KEYS.includes(filter)) return { radar: 1, rain: 1, aloft: true };
  const dbz = (categories.find((c) => c.key === filter) ?? CATEGORIES.find((c) => c.key === filter)).dbz;
  return { radar: dbzLevel(dbz), rain: RAIN_FROM[filter], aloft: false };
}
export const FILTERS = Object.fromEntries(FILTER_KEYS.map((k) => [k, filterLevels(k)]));
export const parseFilter = (value) => (FILTER_KEYS.includes(value) ? value : "all");

/** 0xAABBGGRR, the byte order of ImageData on little-endian machines (all browsers' hosts). */
export function packRgba(r, g, b, a = 255) {
  return ((a << 24) | (b << 16) | (g << 8) | r) >>> 0;
}

/**
 * Code → packed colour, with the classes below `minLevel` (and the echoes aloft unless
 * `aloft`) transparent. `nodata` is the colour outside the coverage (0 = transparent).
 */
export function buildLut({
  solid = DBZ_SCALE.map(([, c]) => c), aloftColours = ALOFT_COLOURS, minLevel = 1, aloft = true,
  nodata = packRgba(196, 196, 196, 64),
} = {}) {
  const lut = new Uint32Array(256);
  for (let level = 1; level <= LEVELS; level++) {
    if (level < minLevel) continue;
    lut[level] = packRgba(...hexRgb(solid[level - 1]));
    if (aloft) lut[level | ALOFT] = packRgba(...hexRgb(aloftColours[level - 1]));
  }
  lut[NODATA] = nodata;
  return lut;
}

// --- legend -------------------------------------------------------------------------

/** "0.1", "0.6", "2", "12", "120": rain rates in English format. */
export function rateLabel(mm) {
  if (mm < 1) return (Math.round(mm * 10) / 10).toFixed(1);
  if (mm < 100) return String(Math.round(mm));
  return String(Math.round(mm / 10) * 10);
}

/**
 * The reflectivity scale as rows [dbz, colour, mm/h, label en, label cs]: from
 * index.json `scales.maxz` when the backend sends it, else ČHMÚ's scale with our words.
 */
export function maxzScale(index, labels) {
  const given = index?.scales?.maxz;
  if (Array.isArray(given) && given.length && given.every((r) => Array.isArray(r) && r.length >= 2)) return given;
  return DBZ_SCALE.map(([dbz, colour]) => {
    const key = categoryOf(dbzLevel(dbz));
    return [dbz, colour, rainRate(dbz), labels?.en?.[key] ?? key, labels?.cs?.[key] ?? key];
  });
}

/**
 * Legend rows: consecutive classes with the same label grouped, each with its colours
 * and the range of rain rates, e.g. {label: "Moderate rain", colours: […], from: 2, to: 10}.
 */
export function legendRows(scale, language = "en") {
  const rows = [];
  for (const [i, entry] of scale.entries()) {
    const [dbz, colour, mm = rainRate(dbz)] = entry;
    const label = (language === "cs" ? entry[4] : entry[3]) ?? entry[3] ?? `${dbz} dBZ`;
    const last = rows.at(-1);
    if (last && last.label === label) {
      last.colours.push(colour);
      last.dbzTo = scale[i + 1]?.[0] ?? null;
    } else {
      rows.push({ label, colours: [colour], dbz, dbzTo: scale[i + 1]?.[0] ?? null, from: mm, to: null });
    }
  }
  for (const [i, row] of rows.entries()) row.to = rows[i + 1]?.from ?? null;
  return rows;
}

/** Simple colour rows ([[value, colour], …], e.g. MERGE in mm or echo tops in km). */
export function simpleScale(index, key, fallback) {
  const given = index?.scales?.[key];
  return Array.isArray(given) && given.length ? given.map((r) => [r[0], r[1]]) : fallback;
}

export { MM_SCALE };
