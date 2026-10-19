// The AI tab's extra map colour: MeteoVerdict AI's temperature at 100 m from the terrain
// (data/scores/ai/fc/temp100m.json and the image it names, transparent outside Czechia,
// its rows already in the map's spacing). Without a valid file the choice is not offered.

export const TEMP100M_JSON = "data/scores/ai/fc/temp100m.json";

const TIME_ZONE = "Europe/Prague";
const finite = (v) => typeof v === "number" && Number.isFinite(v);
const COLOR = /^#[0-9a-f]{6}$/i;

/**
 * The file's parts the map needs, or null when it is not usable: `url` the image (relative
 * to the json), `coordinates` its corners for a MapLibre image source, `time` (ms),
 * `min`/`max`/`unit` and `stops` [{value, color}] for the legend.
 */
export function parseTemp100m(doc, jsonPath = TEMP100M_JSON) {
  if (!doc || typeof doc !== "object") return null;
  const b = doc.bounds;
  if (!Array.isArray(b) || b.length !== 4 || !b.every(finite)) return null;
  const [west, south, east, north] = b;
  if (!(west < east && south < north)) return null;
  const time = Date.parse(doc.time);
  if (typeof doc.png !== "string" || !/^[\w.-]+\.png$/.test(doc.png) || Number.isNaN(time)) return null;
  const stops = Array.isArray(doc.colormap)
    ? doc.colormap.filter((s) => finite(s?.value) && COLOR.test(s?.color ?? "")).sort((a, b) => a.value - b.value)
    : [];
  if (stops.length < 2) return null;
  const min = finite(doc.legend?.min) ? doc.legend.min : stops[0].value;
  const max = finite(doc.legend?.max) ? doc.legend.max : stops.at(-1).value;
  if (!(min < max)) return null;
  return {
    url: jsonPath.replace(/[^/]*$/, doc.png),
    bounds: [west, south, east, north],
    coordinates: [[west, north], [east, north], [east, south], [west, south]],
    time,
    min,
    max,
    unit: typeof doc.legend?.unit === "string" ? doc.legend.unit : "°C",
    stops: stops.map(({ value, color }) => ({ value, color })),
  };
}

/** The legend's CSS gradient, the stops placed between min and max. */
export function temp100mGradient({ stops, min, max }) {
  const at = (v) => Math.round(Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100)) * 10) / 10;
  return `linear-gradient(to right, ${stops.map((s) => `${s.color} ${at(s.value)}%`).join(", ")})`;
}

const pragueParts = (ms) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(ms);
  const get = (type) => parts.find((p) => p.type === type).value;
  return { day: `${get("year")}-${get("month")}-${get("day")}`, hour: Number(get("hour")), clock: `${get("hour")}:${get("minute")}` };
};

/**
 * When the image is for, Prague time: `key` "tonight" (this evening, the night after
 * today until 06:00, or after midnight the night still going on), "today", "tomorrow" or null (another day: `day` its date), and `clock`.
 */
export function temp100mWhen(time, now) {
  const at = pragueParts(time);
  const today = pragueParts(now).day;
  const offset = Math.round((Date.parse(`${at.day}T12:00Z`) - Date.parse(`${today}T12:00Z`)) / 86400000);
  let key = null;
  if ((offset === 0 && (at.hour >= 18 || at.hour < 6)) || (offset === 1 && at.hour < 6)) key = "tonight";
  else if (offset === 0) key = "today";
  else if (offset === 1) key = "tomorrow";
  return { key, day: at.day, clock: at.clock };
}

/** "dnes v noci 02:00", "tomorrow 14:00", "St 21. 10. 14:00" (`t` the translator). */
export function temp100mTimeText(time, now, language, t) {
  const when = temp100mWhen(time, now);
  if (when.key) return t(`ai.temp100m.${when.key}`, { time: when.clock });
  const date = new Intl.DateTimeFormat(language, { timeZone: "UTC", weekday: "short", day: "numeric", month: "numeric" })
    .format(Date.parse(`${when.day}T12:00Z`));
  return `${date} ${when.clock}`;
}

// --- reading the value under the pointer from the image itself ---------------------------

const mercatorY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

/**
 * The image pixel {x, y} under lng/lat for an image of `width` x `height` covering `bounds`
 * [west, south, east, north] (x linear in longitude, y linear in Web-Mercator Y), or null
 * outside the image.
 */
export function temp100mPixel(lng, lat, bounds, width, height) {
  const [west, south, east, north] = bounds;
  if (!(lng >= west && lng <= east && lat >= south && lat <= north)) return null;
  const yTop = mercatorY(north);
  const x = Math.min(width - 1, Math.floor(((lng - west) / (east - west)) * width));
  const y = Math.min(height - 1, Math.floor(((yTop - mercatorY(lat)) / (yTop - mercatorY(south))) * height));
  return { x, y };
}

const hexRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

/** The colour [r, g, b] of a value: linear RGB interpolation between the colormap's stops. */
export function temp100mColour(value, stops) {
  if (value <= stops[0].value) return hexRgb(stops[0].color);
  for (let i = 1; i < stops.length; i++) {
    if (value <= stops[i].value) {
      const a = stops[i - 1];
      const f = (value - a.value) / (stops[i].value - a.value);
      const from = hexRgb(a.color);
      const to = hexRgb(stops[i].color);
      return from.map((c, k) => Math.round(c + (to[k] - c) * f));
    }
  }
  return hexRgb(stops.at(-1).color);
}

/** Every step (default 0.25) from min to max with its colour: [{value, rgb}]. */
export function temp100mLookup({ stops, min, max }, step = 0.25) {
  const n = Math.round((max - min) / step);
  return Array.from({ length: n + 1 }, (_, i) => {
    const value = Math.round((min + i * step) * 1e6) / 1e6;
    return { value, rgb: temp100mColour(value, stops) };
  });
}

/** The value of the step whose colour is nearest to r, g, b; null when transparent (alpha 0). */
export function temp100mValue(lookup, r, g, b, a = 255) {
  if (!a) return null;
  let best = null;
  let bestD = Infinity;
  for (const { value, rgb } of lookup) {
    const d = (rgb[0] - r) ** 2 + (rgb[1] - g) ** 2 + (rgb[2] - b) ** 2;
    if (d < bestD) { bestD = d; best = value; }
  }
  return best;
}

/** "2,9 °C · po 02:00" (cs) / "2.9 °C · at 02:00" (en): value and the layer's Prague clock. */
export function temp100mTipText(value, time, language, unit = "°C") {
  const num = new Intl.NumberFormat(language, { minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(value);
  const clock = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(time);
  return `${num} ${unit} · ${language === "cs" ? "po" : "at"} ${clock}`;
}

// --- the time series: grayscale PNGs per day and part of day ------------------------------
// data/scores/ai/fc/temp100m/index.json: bounds, width, height, offset, step, unit and
// maps [{day, part, time, file}]. A PNG's gray 0 (or alpha 0) is no data, v >= 1 is
// offset + (v - 1) * step °C. Painted with the okres fills' temperature ramp.

export const TEMP100M_INDEX = "data/scores/ai/fc/temp100m/index.json";

/** The index's parts, or null when unusable: `bounds`, `offset`, `step`, `unit`, `maps` (with `url`, `time` ms, own `offset` and `step`). */
export function parseTemp100mIndex(doc, indexPath = TEMP100M_INDEX) {
  if (!doc || typeof doc !== "object") return null;
  const b = doc.bounds;
  if (!Array.isArray(b) || b.length !== 4 || !b.every(finite)) return null;
  if (!(b[0] < b[2] && b[1] < b[3]) || !finite(doc.offset) || !(doc.step > 0)) return null;
  const maps = (Array.isArray(doc.maps) ? doc.maps : [])
    .filter((m) => typeof m?.day === "string" && typeof m.part === "string" && /^[\w.-]+\.png$/.test(m.file ?? "") && !Number.isNaN(Date.parse(m.time)))
    .map((m) => ({
      day: m.day,
      part: m.part,
      time: Date.parse(m.time),
      url: indexPath.replace(/[^/]*$/, m.file),
      // a map may have its own (coarser) step
      offset: finite(m.offset) ? m.offset : doc.offset,
      step: m.step > 0 ? m.step : doc.step,
    }));
  if (!maps.length) return null;
  return {
    bounds: b,
    coordinates: [[b[0], b[3]], [b[2], b[3]], [b[2], b[1]], [b[0], b[1]]],
    offset: doc.offset,
    step: doc.step,
    unit: typeof doc.unit === "string" ? doc.unit : "°C",
    maps,
  };
}

/** The index's map for a day and part, or null ("100 m map only for the next 3 days"). */
export const temp100mMapFor = (index, day, part) => index?.maps.find((m) => m.day === day && m.part === part) ?? null;

/** Temperature of a gray value; null for 0 (no data). */
export const temp100mGrayValue = (v, offset, step) => (v >= 1 ? offset + (v - 1) * step : null);

/** RGBA lookup (256 x 4) for the gray values: `colour(value)` gives "#rrggbb"; 0 stays transparent. */
export function temp100mGrayLut({ offset, step }, colour, opacity = 255) {
  const lut = new Uint8ClampedArray(256 * 4);
  for (let v = 1; v < 256; v++) {
    const [r, g, b] = hexRgb(colour(temp100mGrayValue(v, offset, step)));
    lut.set([r, g, b, opacity], v * 4);
  }
  return lut;
}

/** Gray RGBA pixels (r = gray, a = 0 for no data) to the coloured RGBA pixels, plus the gray values. */
export function temp100mColourise(rgba, lut) {
  const out = new Uint8ClampedArray(rgba.length);
  const gray = new Uint8Array(rgba.length / 4);
  for (let i = 0; i < gray.length; i++) {
    const v = rgba[i * 4 + 3] ? rgba[i * 4] : 0;
    gray[i] = v;
    out.set(lut.subarray(v * 4, v * 4 + 4), i * 4);
  }
  return { out, gray };
}

/** The temperature at lng/lat from a gray image {gray, width, height}; null outside or no data. */
export function temp100mGrayAt(img, lng, lat, bounds, { offset, step }) {
  const p = temp100mPixel(lng, lat, bounds, img.width, img.height);
  return p ? temp100mGrayValue(img.gray[p.y * img.width + p.x], offset, step) : null;
}

/** The colour image's value at lng/lat (the old single file): nearest step colour; null outside. */
export function temp100mColourAt(img, lng, lat, bounds, lookup) {
  const p = temp100mPixel(lng, lat, bounds, img.width, img.height);
  if (!p) return null;
  const i = (p.y * img.width + p.x) * 4;
  return temp100mValue(lookup, img.data[i], img.data[i + 1], img.data[i + 2], img.data[i + 3]);
}

const loadImageData = async (url) => {
  const img = new Image();
  img.src = url;
  await img.decode();
  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
};

/**
 * What the map needs for one selection, loaded once and cached: `{ url, coordinates, time,
 * at(lng, lat) }` or null. `source` is {index} (the series) or {single} (the old coloured
 * file); `colour(value)` is the okres fills' temperature ramp, `key(day, part)` picks.
 */
export function temp100mLoader(source, colour) {
  const cache = new Map();
  const series = async (m) => {
    const { index } = source;
    const data = await loadImageData(m.url);
    const lut = temp100mGrayLut(m, colour);
    const { out, gray } = temp100mColourise(data.data, lut);
    const canvas = document.createElement("canvas");
    canvas.width = data.width;
    canvas.height = data.height;
    canvas.getContext("2d").putImageData(new ImageData(out, data.width, data.height), 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    const img = { gray, width: data.width, height: data.height };
    return {
      url: URL.createObjectURL(blob),
      coordinates: index.coordinates,
      time: m.time,
      at: (lng, lat) => temp100mGrayAt(img, lng, lat, index.bounds, m),
    };
  };
  const single = async () => {
    const s = source.single;
    const data = await loadImageData(s.url);
    const lookup = temp100mLookup(s);
    return {
      url: s.url,
      coordinates: s.coordinates,
      time: s.time,
      at: (lng, lat) => temp100mColourAt(data, lng, lat, s.bounds, lookup),
    };
  };
  return {
    /** The selection's map or null (no map for that day and part, or it failed to load). */
    load(day, part) {
      let job;
      let id;
      if (source.index) {
        const m = temp100mMapFor(source.index, day, part);
        if (!m) return Promise.resolve(null);
        id = m.url;
        job = () => series(m);
      } else {
        id = "single";
        job = single;
      }
      if (!cache.has(id)) cache.set(id, job().catch(() => null));
      return cache.get(id);
    },
  };
}
