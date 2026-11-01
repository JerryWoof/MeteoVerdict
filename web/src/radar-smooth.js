// Smooth drawing of a radar frame at k × the grid's resolution. The frames are classes (levels
// 1 … 15) on ČHMÚ's ~1 km grid; drawing each cell as a flat square looks pixelated.
// Here the classes become a continuous field first:
//  - coverage: the echo indicator, blurred (Gaussian, σ = 0.6 cell); a pixel shows rain where it
//    is at least 0.3, which puts an edge within about a third of a cell of the cell edge (the echo
//    never grows by more than half a cell) and rounds the corners; a lone cell stays a small blob;
//  - level: the echo cells' levels blurred the same way and divided by the blurred coverage
//    (normalised convolution), so the empty cells around do not dilute the intensity;
//  - aloft: the share of echo cells that are "aloft" (lighter colours).
// The fields are interpolated bilinearly to the k × finer pixels and coloured from the legend's
// table: "bands" rounds the level to its class (sharp class edges, only legend colours),
// "gradient" blends smoothly between the colours of the two classes around the level.
// A filter on the levels (colour table with hidden classes) applies to the smooth level.
import { ALOFT, LEVELS, NODATA } from "./radar-palette.js";

const SIGMA = 0.6;
const COVERAGE_MIN = 0.3;
const RADIUS = 1; // the weight two cells away is 0.4 %
const KERNEL = (() => {
  const w = [];
  for (let d = -RADIUS; d <= RADIUS; d++) w.push(Math.exp(-(d * d) / (2 * SIGMA * SIGMA)));
  const sum = w.reduce((x, y) => x + y, 0);
  return w.map((x) => x / sum);
})();

/** Gaussian blur of a w × h field; rows (and their neighbours) without any echo are skipped. */
function blur(src, w, h, rowHas) {
  const tmp = new Float32Array(w * h);
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    if (!rowHas[y]) continue;
    const row = y * w;
    for (let x = 0; x < w; x++) {
      const l = src[row + (x > 0 ? x - 1 : 0)];
      const r = src[row + (x < w - 1 ? x + 1 : w - 1)];
      tmp[row + x] = KERNEL[0] * l + KERNEL[1] * src[row + x] + KERNEL[2] * r;
    }
  }
  for (let y = 0; y < h; y++) {
    const up = y > 0 ? y - 1 : 0;
    const down = y < h - 1 ? y + 1 : h - 1;
    if (!rowHas[up] && !rowHas[y] && !rowHas[down]) continue;
    const row = y * w;
    for (let x = 0; x < w; x++) out[row + x] = KERNEL[0] * tmp[up * w + x] + KERNEL[1] * tmp[row + x] + KERNEL[2] * tmp[down * w + x];
  }
  return out;
}

/** The continuous fields of a frame (w × h codes): {coverage, level, aloft}, each Float32Array. */
export function smoothField(codes, w, h) {
  const n = w * h;
  const echo = new Float32Array(n);
  const weighted = new Float32Array(n);
  const aloft = new Float32Array(n);
  const rowHas = new Uint8Array(h);
  for (let p = 0; p < n; p++) {
    const c = codes[p];
    const level = c & NODATA ? 0 : c & 31;
    if (level > 0) {
      echo[p] = 1;
      weighted[p] = level;
      if (c & ALOFT) aloft[p] = 1;
      rowHas[(p / w) | 0] = 1;
    }
  }
  const coverage = blur(echo, w, h, rowHas);
  const level = blur(weighted, w, h, rowHas);
  const aloftShare = blur(aloft, w, h, rowHas);
  for (let p = 0; p < n; p++) {
    const e = coverage[p];
    level[p] = e > 1e-4 ? level[p] / e : 0;
    aloftShare[p] = e > 1e-4 ? aloftShare[p] / e : 0;
  }
  return { coverage, level, aloft: aloftShare };
}

// the last frames' fields (the colour table or the filter changing redraws the same frame)
const fields = new WeakMap();
const fieldOf = (codes, w, h) => {
  let f = fields.get(codes);
  if (!f) fields.set(codes, (f = smoothField(codes, w, h)));
  return f;
};

const STEPS = 16;
const channel = (c, s) => (c >>> s) & 255;
const mix = (a, b, f, s) => Math.round(channel(a, s) * (1 - f) + channel(b, s) * f);

/** Colours at levels 1 … LEVELS in 1/STEPS steps from the table's two classes (hidden ones: 0). */
function gradientTable(lut, flag) {
  const table = new Uint32Array(LEVELS * STEPS + 1);
  for (let i = STEPS; i <= LEVELS * STEPS; i++) {
    const level = i / STEPS;
    if (!lut[Math.round(level) | flag]) continue; // that class is hidden
    const lo = Math.floor(level);
    const f = level - lo;
    const a = lut[lo | flag];
    const b = lut[Math.min(LEVELS, lo + 1) | flag];
    table[i] = a === 0 || b === 0 ? a || b : (mix(a, b, f, 0) | (mix(a, b, f, 8) << 8) | (mix(a, b, f, 16) << 16) | (mix(a, b, f, 24) << 24)) >>> 0;
  }
  return table;
}
const tables = new WeakMap();
function gradientsOf(lut) {
  let t = tables.get(lut);
  if (!t) tables.set(lut, (t = [gradientTable(lut, 0), gradientTable(lut, ALOFT)]));
  return t;
}

/**
 * Draw `codes` (w × h) into `out` (packed RGBA, w·k × h·k) with the colour table `lut`.
 * The output pixel centres are the source's sub-cell centres, so the picture stays aligned.
 * mode: "gradient" (blended colours) or "bands" (the legend's classes).
 */
export function smoothDraw(out, codes, w, h, k, lut, mode = "gradient") {
  const { coverage, level, aloft } = fieldOf(codes, w, h);
  const [solid, light] = mode === "gradient" ? gradientsOf(lut) : [null, null];
  const ow = w * k;
  const oh = h * k;
  const x0 = new Int32Array(ow);
  const x1 = new Int32Array(ow);
  const fx = new Float32Array(ow);
  for (let ox = 0; ox < ow; ox++) {
    const sx = (ox + 0.5) / k - 0.5;
    const i = Math.floor(sx);
    x0[ox] = Math.max(0, Math.min(w - 1, i));
    x1[ox] = Math.max(0, Math.min(w - 1, i + 1));
    fx[ox] = Math.min(1, Math.max(0, sx - i));
  }
  const nodata = lut[NODATA];
  for (let oy = 0; oy < oh; oy++) {
    const sy = (oy + 0.5) / k - 0.5;
    const j = Math.floor(sy);
    const r0 = Math.max(0, Math.min(h - 1, j)) * w;
    const r1 = Math.max(0, Math.min(h - 1, j + 1)) * w;
    const fy = Math.min(1, Math.max(0, sy - j));
    const nearRow = fy < 0.5 ? r0 : r1;
    for (let ox = 0; ox < ow; ox++) {
      const a = x0[ox];
      const b = x1[ox];
      const gx = fx[ox];
      const o = oy * ow + ox;
      const i00 = r0 + a;
      const i10 = r0 + b;
      const i01 = r1 + a;
      const i11 = r1 + b;
      const c0 = coverage[i00] + (coverage[i10] - coverage[i00]) * gx;
      const c1 = coverage[i01] + (coverage[i11] - coverage[i01]) * gx;
      if (c0 + (c1 - c0) * fy < COVERAGE_MIN) {
        out[o] = codes[nearRow + (gx < 0.5 ? a : b)] & NODATA ? nodata : 0;
        continue;
      }
      const l0 = level[i00] + (level[i10] - level[i00]) * gx;
      const l1 = level[i01] + (level[i11] - level[i01]) * gx;
      const v = l0 + (l1 - l0) * fy;
      const f0 = aloft[i00] + (aloft[i10] - aloft[i00]) * gx;
      const f1 = aloft[i01] + (aloft[i11] - aloft[i01]) * gx;
      const flag = f0 + (f1 - f0) * fy > 0.5;
      if (mode === "gradient") {
        out[o] = (flag ? light : solid)[Math.round(Math.min(LEVELS, Math.max(1, v)) * STEPS)];
      } else {
        out[o] = lut[Math.min(LEVELS, Math.max(1, Math.round(v))) | (flag ? ALOFT : 0)];
      }
    }
  }
  return out;
}
