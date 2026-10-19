// The AI heatmap's hourly 100 m map (heatmap.html): the browser downloads a few PNGs and one
// index.json (data/scores/ai/fc/heat/) once and combines them for any hour, as the index's
// `formula` says. Everything here is plain arithmetic on the published files; image rows are
// in the map's (Web-Mercator) spacing.

import { temp100mPixel } from "./ai-temp100m.js";

export const HEAT_INDEX = "data/scores/ai/fc/heat/index.json";

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const PNG = /^[\w.-]+\.png$/;
const FIELDS = 4;
/** The coarse grid's spacing in image pixels: the okres values are spread over it, then interpolated per pixel. */
export const GRID_STEP = 8;
/** The colour lookup's range and step (°C). */
const LUT_MIN = -40;
const LUT_MAX = 50;
const LUT_STEP = 0.1;

const nullable = (v) => (finite(v) ? v : NaN);

/**
 * The index's parts the browser needs, or null when unusable: `bounds`, `coordinates` (the
 * image's corners for a MapLibre image source), `width`, `height`, `lapse`, `cosLat`,
 * `neighbours`, `files` ({elev, fields: [{url, offset, scale, bytes}]}), `points` {lon, lat},
 * `hours` [{time (ms), w, coef}] and `sea`/`a`/`b` [hour][point] with null as NaN.
 */
export function parseHeatIndex(doc, indexPath = HEAT_INDEX) {
  if (!doc || typeof doc !== "object") return null;
  const b = doc.bounds;
  if (!Array.isArray(b) || b.length !== 4 || !b.every(finite) || !(b[0] < b[2] && b[1] < b[3])) return null;
  if (!(doc.width > 1) || !(doc.height > 1) || !finite(doc.lapse) || !(doc.cos_lat > 0)) return null;
  const file = (name) => indexPath.replace(/[^/]*$/, name);
  if (!PNG.test(doc.elev?.file ?? "")) return null;
  if (!Array.isArray(doc.fields) || doc.fields.length !== FIELDS) return null;
  const fields = doc.fields.map((f) =>
    PNG.test(f?.file ?? "") && finite(f.offset) && finite(f.scale) ? { url: file(f.file), offset: f.offset, scale: f.scale, bytes: f.bytes ?? 0 } : null,
  );
  if (fields.includes(null)) return null;
  const { lon, lat } = doc.okresy ?? {};
  if (!Array.isArray(lon) || !Array.isArray(lat) || lon.length !== lat.length || !lon.length) return null;
  if (!lon.every(finite) || !lat.every(finite)) return null;
  const n = lon.length;
  const hours = (Array.isArray(doc.hours) ? doc.hours : []).map((h) => ({
    time: Date.parse(h?.time),
    w: h?.w,
    coef: h?.coef,
  }));
  if (!hours.length || !hours.every((h) => finite(h.time) && finite(h.w) && Array.isArray(h.coef) && h.coef.length === FIELDS - 1 && h.coef.every(finite))) return null;
  const table = (rows) =>
    Array.isArray(rows) && rows.length === hours.length && rows.every((r) => Array.isArray(r) && r.length === n)
      ? rows.map((r) => Float64Array.from(r, nullable))
      : null;
  const sea = table(doc.sea);
  const a = table(doc.a);
  const bb = table(doc.b);
  if (!sea || !a || !bb) return null;
  return {
    bounds: b,
    coordinates: [[b[0], b[3]], [b[2], b[3]], [b[2], b[1]], [b[0], b[1]]],
    width: doc.width,
    height: doc.height,
    lapse: doc.lapse,
    cosLat: doc.cos_lat,
    neighbours: Math.max(1, Math.min(n, Math.round(doc.neighbours) || 8)),
    files: { elev: { url: file(doc.elev.file), bytes: doc.elev.bytes ?? 0 }, fields },
    points: { lon: Float64Array.from(lon), lat: Float64Array.from(lat) },
    hours,
    sea,
    a,
    b: bb,
    issued: Date.parse(doc.issued),
  };
}

// --- positions in the image ---------------------------------------------------------------

const mercatorY = (lat) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));

/** The latitude at the centre of image row `y` (rows equally spaced in Web-Mercator Y between north and south). */
export function heatRowLat(y, bounds, height) {
  const yTop = mercatorY(bounds[3]);
  const yBottom = mercatorY(bounds[1]);
  const m = yTop - ((y + 0.5) / height) * (yTop - yBottom);
  return ((2 * Math.atan(Math.exp(m)) - Math.PI / 2) * 180) / Math.PI;
}

/** The longitude at the centre of image column `x`. */
export const heatColLon = (x, bounds, width) => bounds[0] + ((x + 0.5) / width) * (bounds[2] - bounds[0]);

// --- the okres values spread over the map -------------------------------------------------

/**
 * The `k` nearest points to lon/lat (distance in lon·cosLat, lat) and their weights
 * 1/max(d, 1e-4)²: { idx: Int32Array(k), w: Float64Array(k) }; `into` may hold the arrays to reuse.
 */
export function heatNeighbours(points, cosLat, k, lon, lat, into = { idx: new Int32Array(k), w: new Float64Array(k) }) {
  const { idx, w } = into;
  const d2 = new Float64Array(k).fill(Infinity);
  const n = points.lon.length;
  for (let i = 0; i < n; i++) {
    const dx = (points.lon[i] - lon) * cosLat;
    const dy = points.lat[i] - lat;
    const d = dx * dx + dy * dy;
    if (d >= d2[k - 1]) continue;
    let j = k - 1;
    while (j > 0 && d2[j - 1] > d) {
      d2[j] = d2[j - 1];
      idx[j] = idx[j - 1];
      j--;
    }
    d2[j] = d;
    idx[j] = i;
  }
  for (let j = 0; j < k; j++) {
    const d = Math.max(Math.sqrt(d2[j]), 1e-4);
    w[j] = 1 / (d * d);
  }
  return into;
}

/** Inverse-distance mean of `values` (NaN = no value) over the `k` neighbours at `offset` of idx/w; NaN when none has a value. */
export function heatIdw(values, idx, w, offset = 0, k = idx.length - offset) {
  let sum = 0;
  let wsum = 0;
  for (let j = 0; j < k; j++) {
    const v = values[idx[offset + j]];
    if (v !== v) continue;
    sum += w[offset + j] * v;
    wsum += w[offset + j];
  }
  return wsum ? sum / wsum : NaN;
}

/** The coarse grid: its size and, per node, the neighbours (flat `idx`, `w` of length nodes·k). */
export function heatGrid(index, step = GRID_STEP) {
  const { width, height, bounds, points, cosLat, neighbours: k } = index;
  const gw = Math.ceil((width - 1) / step) + 1;
  const gh = Math.ceil((height - 1) / step) + 1;
  const idx = new Int16Array(gw * gh * k);
  const w = new Float32Array(gw * gh * k);
  const into = { idx: new Int32Array(k), w: new Float64Array(k) };
  for (let gy = 0; gy < gh; gy++) {
    const lat = heatRowLat(gy * step, bounds, height);
    for (let gx = 0; gx < gw; gx++) {
      const lon = heatColLon(gx * step, bounds, width);
      heatNeighbours(points, cosLat, k, lon, lat, into);
      idx.set(into.idx, (gy * gw + gx) * k);
      w.set(into.w, (gy * gw + gx) * k);
    }
  }
  return { step, gw, gh, idx, w };
}

// --- decoding the PNGs --------------------------------------------------------------------

/** Elevation in metres from RGBA pixels (R·256 + G); alpha 0 (outside Czechia) is 65535. */
export function heatDecodeElev(rgba) {
  const out = new Uint16Array(rgba.length / 4);
  for (let i = 0; i < out.length; i++) out[i] = rgba[i * 4 + 3] ? rgba[i * 4] * 256 + rgba[i * 4 + 1] : 65535;
  return out;
}

/** Gray values from RGBA pixels (alpha 0 is 0: no data). */
export function heatDecodeGray(rgba) {
  const out = new Uint8Array(rgba.length / 4);
  for (let i = 0; i < out.length; i++) out[i] = rgba[i * 4 + 3] ? rgba[i * 4] : 0;
  return out;
}

/** A field's value from its gray value: offset + (v - 1)·scale; null for 0 (no data). */
export const heatFieldValue = (v, offset, scale) => (v >= 1 ? offset + (v - 1) * scale : null);

/** The model: the index with its decoded `elev` (Uint16Array) and `gray` (4 Uint8Array), and its grid. */
export function heatModel(index, elev, gray, grid = heatGrid(index)) {
  return { index, elev, gray, grid };
}

// --- one hour's value ----------------------------------------------------------------------

/**
 * The temperature of hour `i` at image pixel (x, y) for given neighbour sets, or null outside
 * Czechia: idw(sea) − lapse·elev + w·(idw(a)·F + idw(b)), F = f0 + Σ coef·f(k+1).
 */
export function heatPixelValue(model, i, x, y, nb) {
  const { index, elev, gray } = model;
  const p = y * index.width + x;
  if (elev[p] === 65535) return null;
  const f = [];
  for (let k = 0; k < FIELDS; k++) {
    const v = heatFieldValue(gray[k][p], index.files.fields[k].offset, index.files.fields[k].scale);
    if (v === null) return null;
    f.push(v);
  }
  const hour = index.hours[i];
  const F = f[0] + hour.coef[0] * f[1] + hour.coef[1] * f[2] + hour.coef[2] * f[3];
  const T = heatIdw(index.sea[i], nb.idx, nb.w) - index.lapse * elev[p] + hour.w * (heatIdw(index.a[i], nb.idx, nb.w) * F + heatIdw(index.b[i], nb.idx, nb.w));
  return Number.isFinite(T) ? T : null;
}

/** The pixel {x, y} of lng/lat, or null outside the image. */
export const heatPixelAt = (index, lng, lat) => temp100mPixel(lng, lat, index.bounds, index.width, index.height);

/**
 * Every hour's exact value at lng/lat as a Float64Array (NaN outside Czechia): the formula
 * evaluated at the pixel itself, not on the coarse grid.
 */
export function heatSeriesAt(model, lng, lat) {
  const { index } = model;
  const out = new Float64Array(index.hours.length).fill(NaN);
  const p = heatPixelAt(index, lng, lat);
  if (!p) return out;
  const nb = heatNeighbours(index.points, index.cosLat, index.neighbours, heatColLon(p.x, index.bounds, index.width), heatRowLat(p.y, index.bounds, index.height));
  for (let i = 0; i < out.length; i++) out[i] = heatPixelValue(model, i, p.x, p.y, nb) ?? NaN;
  return out;
}

/** The value at lng/lat at position `pos` (hours, .5 steps): only the one or two hours needed; null outside Czechia. */
export function heatValueAt(model, lng, lat, pos) {
  const { index } = model;
  const p = heatPixelAt(index, lng, lat);
  if (!p) return null;
  const nb = heatNeighbours(index.points, index.cosLat, index.neighbours, heatColLon(p.x, index.bounds, index.width), heatRowLat(p.y, index.bounds, index.height));
  const last = index.hours.length - 1;
  const clamped = Math.min(last, Math.max(0, pos));
  const lo = Math.floor(clamped);
  const a = heatPixelValue(model, lo, p.x, p.y, nb);
  if (a === null || clamped === lo || lo >= last) return a;
  const b = heatPixelValue(model, lo + 1, p.x, p.y, nb);
  return b === null ? null : a + (clamped - lo) * (b - a);
}

/** A value at position `pos` (in hours, may be .5) of an hourly series: linear between the two hours. */
export function heatBlend(series, pos) {
  const last = series.length - 1;
  const p = Math.min(last, Math.max(0, pos));
  const i = Math.floor(p);
  const f = p - i;
  return f === 0 || i >= last ? series[i] : series[i] + f * (series[i + 1] - series[i]);
}

// --- the picture ---------------------------------------------------------------------------

/** RGB lookup for the temperatures LUT_MIN..LUT_MAX in 0.1° steps; `colour(value)` gives "#rrggbb". */
export function heatColourLut(colour) {
  const n = Math.round((LUT_MAX - LUT_MIN) / LUT_STEP) + 1;
  const lut = new Uint8ClampedArray(n * 3);
  for (let i = 0; i < n; i++) {
    const hex = colour(LUT_MIN + i * LUT_STEP);
    for (let c = 0; c < 3; c++) lut[i * 3 + c] = parseInt(hex.slice(1 + c * 2, 3 + c * 2), 16);
  }
  return lut;
}

/**
 * The per-node values of position `pos` (hours, .5 steps) for the picture: five coarse grids
 * so that the pixel value is c + p0·f0 + p1·f1 + p2·f2 + p3·f3 − lapse·elev (an average of two
 * hours' grids is the average of their values).
 */
function nodeGrids(model, pos) {
  const { index, grid } = model;
  const nodes = grid.gw * grid.gh;
  const k = index.neighbours;
  const g = Array.from({ length: 5 }, () => new Float32Array(nodes));
  const last = index.hours.length - 1;
  const lo = Math.min(last, Math.max(0, Math.floor(pos)));
  const f = Math.min(last, Math.max(0, pos)) - lo;
  const parts = f === 0 || lo >= last ? [[lo, 1]] : [[lo, 1 - f], [lo + 1, f]];
  for (const [i, share] of parts) {
    const { w, coef } = index.hours[i];
    for (let n = 0; n < nodes; n++) {
      const s = heatIdw(index.sea[i], grid.idx, grid.w, n * k, k);
      const a = heatIdw(index.a[i], grid.idx, grid.w, n * k, k);
      const b = heatIdw(index.b[i], grid.idx, grid.w, n * k, k);
      g[0][n] += share * (s + w * b);
      g[1][n] += share * w * a;
      g[2][n] += share * w * a * coef[0];
      g[3][n] += share * w * a * coef[1];
      g[4][n] += share * w * a * coef[2];
    }
  }
  return g;
}

/** The temperatures are kept in hundredths of a degree (Int16); this marks a pixel without data. */
export const NO_TEMP = -32768;
/** The histogram of a picture's temperatures: bins of HIST_STEP °C from HIST_MIN. */
export const HIST_MIN = LUT_MIN;
export const HIST_STEP = 0.1;
const HIST_BINS = Math.round((LUT_MAX - LUT_MIN) / HIST_STEP) + 1;

/**
 * The temperatures of position `pos` (hours, .5 steps) as `{ values, width, height, hist }`: the
 * image's size divided by `shrink`; `values` is an Int16Array in hundredths of °C (NO_TEMP outside
 * Czechia), `hist` counts them in bins of HIST_STEP from HIST_MIN. `into` may be an earlier result
 * of the same size to reuse its arrays.
 */
export function heatTemperatures(model, pos, shrink = 1, into = null) {
  const { index, elev, gray, grid } = model;
  const { width, height, lapse } = index;
  const ow = Math.ceil(width / shrink);
  const oh = Math.ceil(height / shrink);
  const values = into?.values.length === ow * oh ? into.values : new Int16Array(ow * oh);
  values.fill(NO_TEMP);
  const hist = new Uint32Array(HIST_BINS);
  const g = nodeGrids(model, pos);
  const { step, gw } = grid;
  // per output column: the grid cell and the share of its right node
  const cell = new Int32Array(ow);
  const share = new Float32Array(ow);
  for (let ox = 0; ox < ow; ox++) {
    const gx = (ox * shrink) / step;
    cell[ox] = Math.min(gw - 2, Math.floor(gx));
    share[ox] = gx - cell[ox];
  }
  const rows = Array.from({ length: 5 }, () => new Float32Array(gw));
  const [o0, o1, o2, o3] = index.files.fields.map((f) => f.offset - f.scale);
  const [s0, s1, s2, s3] = index.files.fields.map((f) => f.scale);
  const [f0, f1, f2, f3] = gray;
  const binMax = HIST_BINS - 1;
  const binOffset = Math.round(-HIST_MIN * 100);
  const binWidth = Math.round(HIST_STEP * 100);
  for (let oy = 0; oy < oh; oy++) {
    const y = oy * shrink;
    const gy = y / step;
    const r0 = Math.min(grid.gh - 2, Math.floor(gy));
    const fy = gy - r0;
    for (let q = 0; q < 5; q++) {
      const src = g[q];
      const row = rows[q];
      const a = r0 * gw;
      const b = a + gw;
      for (let i = 0; i < gw; i++) row[i] = src[a + i] + fy * (src[b + i] - src[a + i]);
    }
    const [c, p0, p1, p2, p3] = rows;
    for (let ox = 0; ox < ow; ox++) {
      const p = y * width + ox * shrink;
      const e = elev[p];
      const v0 = f0[p];
      const v1 = f1[p];
      const v2 = f2[p];
      const v3 = f3[p];
      if (e === 65535 || !v0 || !v1 || !v2 || !v3) continue;
      const i = cell[ox];
      const t = share[ox];
      const T =
        c[i] + t * (c[i + 1] - c[i]) +
        (p0[i] + t * (p0[i + 1] - p0[i])) * (o0 + v0 * s0) +
        (p1[i] + t * (p1[i + 1] - p1[i])) * (o1 + v1 * s1) +
        (p2[i] + t * (p2[i + 1] - p2[i])) * (o2 + v2 * s2) +
        (p3[i] + t * (p3[i + 1] - p3[i])) * (o3 + v3 * s3) -
        lapse * e;
      if (T !== T) continue;
      const h = T > 327 ? 32700 : T < -327 ? -32700 : Math.round(T * 100);
      values[oy * ow + ox] = h;
      // bin = (h - HIST_MIN·100) / (HIST_STEP·100), clamped
      let bin = ((h + binOffset) / binWidth) | 0;
      if (bin < 0) bin = 0;
      else if (bin > binMax) bin = binMax;
      hist[bin]++;
    }
  }
  return { values, width: ow, height: oh, hist };
}

// --- the colour options ---------------------------------------------------------------------

/** The vivid diverging ramp stretched over the range of "This hour" and "All 5 days". */
export const HEAT_RAMP = ["#313695", "#4575b4", "#74add1", "#abd9e9", "#e0f3f8", "#ffffbf", "#fee090", "#fdae61", "#f46d43", "#d73027", "#a50026"];

const rgbOf = (hex) => [0, 1, 2].map((c) => parseInt(hex.slice(1 + c * 2, 3 + c * 2), 16));

/** The ramp's colour [r, g, b] at `value` on [lo, hi]: the stops spread evenly, linear between them, clamped at the ends. */
export function heatRampColour(value, lo, hi, stops = HEAT_RAMP) {
  const n = stops.length - 1;
  const f = Math.min(1, Math.max(0, (value - lo) / (hi - lo))) * n;
  const i = Math.min(n - 1, Math.floor(f));
  const a = rgbOf(stops[i]);
  const b = rgbOf(stops[i + 1]);
  return a.map((c, k) => Math.round(c + (f - i) * (b[k] - c)));
}

/** The CSS gradient of the ramp (stops evenly spread). */
export const heatRampGradient = (stops = HEAT_RAMP) => `linear-gradient(to right, ${stops.map((c, i) => `${c} ${((i / (stops.length - 1)) * 100).toFixed(1)}%`).join(", ")})`;

/**
 * The robust ends of a histogram (from heatTemperatures): the lower edge of the bin holding the
 * `lowShare` quantile and the upper edge of the one holding the `highShare` quantile; null when empty.
 */
export function heatRobustEnds(hist, lowShare = 0.01, highShare = 0.99, min = HIST_MIN, step = HIST_STEP) {
  let total = 0;
  for (let i = 0; i < hist.length; i++) total += hist[i];
  if (!total) return null;
  const lowCount = total * lowShare;
  const highCount = total * highShare;
  let sum = 0;
  let lo = null;
  let hi = null;
  for (let i = 0; i < hist.length; i++) {
    sum += hist[i];
    if (lo === null && sum > lowCount) lo = min + i * step;
    if (sum >= highCount && hist[i]) {
      hi = min + (i + 1) * step;
      break;
    }
  }
  lo ??= min;
  hi ??= min + hist.length * step;
  return { lo, hi };
}

/** Rounds a range outwards to 0.5 °C and widens it (evenly) to at least `minSpan` °C. */
export function heatNiceRange(lo, hi, minSpan = 4) {
  let a = Math.floor(lo * 2 + 1e-9) / 2;
  let b = Math.ceil(hi * 2 - 1e-9) / 2;
  for (let up = false; b - a < minSpan - 1e-9; up = !up) {
    if (up) b += 0.5;
    else a -= 0.5;
  }
  return { lo: a, hi: b };
}

/** The "All 5 days" range from the lowest and highest robust ends: at least 0…10 °C, widened where the data goes beyond, rounded to 0.5. */
export const heatWholeRange = (lo, hi, floorLo = 0, floorHi = 10) => heatNiceRange(Math.min(lo, floorLo), Math.max(hi, floorHi));

/** The "This hour" range of a histogram, or null when empty. */
export function heatHourRange(hist) {
  const ends = heatRobustEnds(hist);
  return ends && heatNiceRange(ends.lo, ends.hi);
}

/**
 * The "All 5 days" range: the widest robust ends over all hours (at least 0…10 °C), from a subsample of the pixels
 * (a coarse grid and every `shrink`th pixel). `onStep(done, total)` may return a promise to let
 * the page breathe between hours.
 */
export async function heatAllRange(model, shrink = 16, gridStep = 64, onStep = () => {}) {
  const coarse = heatModel(model.index, model.elev, model.gray, heatGrid(model.index, gridStep));
  const n = model.index.hours.length;
  let lo = Infinity;
  let hi = -Infinity;
  let reuse = null;
  for (let i = 0; i < n; i++) {
    reuse = heatTemperatures(coarse, i, shrink, reuse);
    const ends = heatRobustEnds(reuse.hist);
    if (ends) {
      lo = Math.min(lo, ends.lo);
      hi = Math.max(hi, ends.hi);
    }
    await onStep(i + 1, n);
  }
  return lo <= hi ? heatWholeRange(lo, hi) : null;
}

/** The frost class of a temperature: 1 at or below 0 °C (frost), 2 above 0 up to 3 °C (ground frost possible), else 0. */
export const heatFrostClass = (T) => (T <= 0 ? 1 : T <= 3 ? 2 : 0);

/** A colour lookup for the paint: `rgb` (3 bytes per entry), the temperature of its first entry and its step. */
export function heatRampLut(lo, hi, entries = 256, stops = HEAT_RAMP) {
  const rgb = new Uint8ClampedArray(entries * 3);
  const step = (hi - lo) / (entries - 1);
  for (let i = 0; i < entries; i++) rgb.set(heatRampColour(lo + i * step, lo, hi, stops), i * 3);
  return { rgb, min: lo, step };
}

/** The fixed palette's lookup (from heatColourLut) in the paint's form. */
export const heatFixedLut = (rgb) => ({ rgb, min: LUT_MIN, step: LUT_STEP });

const ICE = [226, 244, 255];

/**
 * The picture as RGBA pixels from heatTemperatures' result: coloured by `lut` ({rgb, min, step}),
 * and with `frost` (T <= 0: an ice tint with white diagonal stripes) and `ground` (0 < T <= 3: white
 * dots) overlays. Outside Czechia is transparent.
 */
export function heatPaint({ values, width, height }, lut, { frost = false, ground = false } = {}) {
  const data = new Uint8ClampedArray(width * height * 4);
  const { rgb, min, step } = lut;
  const last = rgb.length / 3 - 1;
  // the lookup index from hundredths of °C: (h - min·100) · (1 / (step·100)), rounded
  const base = min * 100;
  const scale = 1 / (step * 100);
  for (let y = 0; y < height; y++) {
    for (let x = 0, k = y * width, o = k * 4; x < width; x++, k++, o += 4) {
      const h = values[k];
      if (h === NO_TEMP) continue;
      let li = ((h - base) * scale + 0.5) | 0;
      if (li < 0) li = 0;
      else if (li > last) li = last;
      li *= 3;
      let r = rgb[li];
      let g = rgb[li + 1];
      let b = rgb[li + 2];
      if (h <= 300) {
        if (h <= 0) {
          if (frost) {
            const share = (x + y) % 8 < 3 ? 0.85 : 0.35;
            r += (ICE[0] - r) * share;
            g += (ICE[1] - g) * share;
            b += (ICE[2] - b) * share;
          }
        } else if (ground && (x & 3) < 2 && (y & 3) < 2) {
          r += (255 - r) * 0.6;
          g += (255 - g) * 0.6;
          b += (255 - b) * 0.6;
        }
      }
      data[o] = r;
      data[o + 1] = g;
      data[o + 2] = b;
      data[o + 3] = 255;
    }
  }
  return { data, width, height };
}

/**
 * The picture of position `pos` (hours, .5 steps) as RGBA pixels with a fixed colour lookup:
 * `{ data, width, height }` of the image's size divided by `shrink`. Outside Czechia is
 * transparent. `lut` is from heatColourLut.
 */
export function heatCompose(model, pos, lut, shrink = 1) {
  return heatPaint(heatTemperatures(model, pos, shrink), heatFixedLut(lut));
}

// --- loading --------------------------------------------------------------------------------

async function fetchBlob(url, onBytes) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  if (!response.body) {
    const blob = await response.blob();
    onBytes(blob.size);
    return blob;
  }
  const chunks = [];
  const reader = response.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    onBytes(value.length);
  }
  return new Blob(chunks, { type: response.headers.get("content-type") ?? "image/png" });
}

/** A PNG's RGBA pixels exactly as stored (no colour conversion, no premultiplying). */
async function decodePng(blob) {
  const bitmap = await createImageBitmap(blob, { colorSpaceConversion: "none", premultiplyAlpha: "none" });
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  return ctx.getImageData(0, 0, canvas.width, canvas.height).data;
}

/**
 * Downloads and decodes the index's PNGs: resolves with the model. `onProgress(done, total)`
 * counts downloaded bytes (total from the index; 0 when it does not say).
 */
export async function loadHeatModel(index, onProgress = () => {}) {
  const parts = [index.files.elev, ...index.files.fields];
  const total = parts.reduce((s, p) => s + p.bytes, 0);
  let done = 0;
  const count = (n) => onProgress((done += n), total);
  const blobs = parts.map((p) => fetchBlob(p.url, count));
  const decoded = [];
  // one decoded image at a time keeps the memory low
  for (const [k, blob] of blobs.entries()) {
    const rgba = await decodePng(await blob);
    decoded.push(k === 0 ? heatDecodeElev(rgba) : heatDecodeGray(rgba));
  }
  const [elev, ...gray] = decoded;
  if (elev.length !== index.width * index.height) throw new Error("the elevation image does not match the index");
  return heatModel(index, elev, gray);
}

// --- the time ------------------------------------------------------------------------------

const TIME_ZONE = "Europe/Prague";

/** The hour (index) nearest to `now` (ms); the hours are in time order. */
export function heatNearestHour(hours, now) {
  let best = 0;
  for (let i = 1; i < hours.length; i++) if (Math.abs(hours[i].time - now) < Math.abs(hours[best].time - now)) best = i;
  return best;
}

/** The time (ms) at position `pos` in hours (.5 steps): linear between two hours. */
export function heatTimeAt(hours, pos) {
  const last = hours.length - 1;
  const p = Math.min(last, Math.max(0, pos));
  const i = Math.floor(p);
  return i >= last ? hours[last].time : hours[i].time + (p - i) * (hours[i + 1].time - hours[i].time);
}

/** "út 20. 10. 14:30" (cs) / "Tue 20/10 14:30" (en): weekday, date and clock in Prague. */
export function heatTimeText(ms, language) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TIME_ZONE, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(ms);
  const get = (type) => parts.find((p) => p.type === type).value;
  const weekday = new Intl.DateTimeFormat(language === "cs" ? "cs" : "en-GB", { timeZone: TIME_ZONE, weekday: "short" }).format(ms);
  const date = language === "cs" ? `${get("day")}. ${get("month")}.` : `${get("day")}/${get("month")}`;
  return `${weekday} ${date} ${get("hour")}:${get("minute")}`;
}

/** Positions (in hours) of each midnight in Prague within the hours, with the weekday's short name: [{pos, label}]. */
export function heatDayMarks(hours, language) {
  const fmt = new Intl.DateTimeFormat(language === "cs" ? "cs" : "en-GB", { timeZone: TIME_ZONE, weekday: "short" });
  const hourOf = new Intl.DateTimeFormat("en-GB", { timeZone: TIME_ZONE, hour: "2-digit", hourCycle: "h23" });
  const marks = [];
  hours.forEach((h, pos) => {
    if (Number(hourOf.format(h.time)) === 0) marks.push({ pos, label: fmt.format(h.time) });
  });
  return marks;
}
