// Smooth radar animation: the time between two frames, the motion field of a pair, and
// the warp that draws an in-between minute (semi-Lagrangian advection of both frames
// along the motion, blended by time). Pure functions on typed arrays, tested in node.

import { ALOFT, NODATA, levelOf } from "./radar-palette.js";
import { parseStamp } from "./radar.js";

/** Where `ms` falls among the steps: frame i and the fraction tau (0 … 1) towards i + 1. */
export function locate(steps, ms) {
  if (!steps.length) return { i: -1, tau: 0 };
  if (ms <= steps[0].time) return { i: 0, tau: 0 };
  const last = steps.length - 1;
  if (ms >= steps[last].time) return { i: last, tau: 0 };
  let lo = 0;
  let hi = last;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (steps[mid].time <= ms) lo = mid;
    else hi = mid;
  }
  const span = steps[hi].time - steps[lo].time;
  return { i: lo, tau: span > 0 ? (ms - steps[lo].time) / span : 0 };
}

/** Round a time down to a multiple of `stepMs` (1 minute: what the animation draws). */
export const quantize = (ms, stepMs = 60000) => Math.floor(ms / stepMs) * stepMs;

/** Real milliseconds per data minute at a speed (1× = a 5-minute frame in 0.6 s). */
export const msPerDataMinute = (speed = 1) => 120 / speed;
export const SPEEDS = [0.5, 1, 2, 4];

/**
 * Advance the animation clock by `dt` real milliseconds. Data time runs at `rate` data
 * ms per real ms; at the end it holds `holdMs` (real) and then starts over.
 *   state = {ms, hold}
 */
export function advanceClock(state, dt, { first, last, rate, holdMs = 1200 }) {
  if (!(last > first)) return { ms: first, hold: 0 };
  if (state.ms >= last) {
    const hold = state.hold + dt;
    return hold >= holdMs ? { ms: first, hold: 0 } : { ms: last, hold };
  }
  return { ms: Math.min(last, state.ms + dt * rate), hold: 0 };
}

/**
 * The motion file to use between frames a and b (steps): the one stamped at b, else the
 * newest one within `maxAgeMin` before b (the nowcast has none of its own), and the
 * interval in seconds the displacement must be scaled to.
 */
export function motionFor(motionStamps, a, b, maxAgeMin = 30) {
  if (!a || !b || !motionStamps?.length) return null;
  const seconds = (b.time - a.time) / 1000;
  if (!(seconds > 0)) return null;
  if (motionStamps.includes(b.radar)) return { stamp: b.radar, seconds };
  let best = null;
  for (const s of motionStamps) {
    const t = parseStamp(s);
    if (t != null && t <= b.time && b.time - t <= maxAgeMin * 60000 && (best == null || t > parseStamp(best))) best = s;
  }
  return best ? { stamp: best, seconds } : null;
}

/** Is a motion file usable ({nx, ny, dt_s, u, v} with nx × ny numbers each)? */
export function validMotion(m) {
  return Boolean(
    m && m.nx > 0 && m.ny > 0 && m.dt_s > 0 && Array.isArray(m.u) && Array.isArray(m.v) &&
      m.u.length === m.nx * m.ny && m.v.length === m.nx * m.ny,
  );
}

/**
 * The coarse motion (grid pixels per dt_s, u east, v down the rows) bilinearly
 * interpolated to every drawn pixel and scaled to `seconds`. `scale` > 1 draws every
 * scale-th pixel (phones). Returns {u, v, ow, oh} in grid pixels.
 */
export function upsampleFlow(motion, w, h, seconds, scale = 1) {
  const { nx, ny, dt_s: dt } = motion;
  const ow = Math.ceil(w / scale);
  const oh = Math.ceil(h / scale);
  const u = new Float32Array(ow * oh);
  const v = new Float32Array(ow * oh);
  const factor = seconds / dt;
  for (let oy = 0; oy < oh; oy++) {
    const gy = Math.min(ny - 1, Math.max(0, ((oy * scale + 0.5) * ny) / h - 0.5));
    const y0 = Math.floor(gy);
    const y1 = Math.min(ny - 1, y0 + 1);
    const fy = gy - y0;
    for (let ox = 0; ox < ow; ox++) {
      const gx = Math.min(nx - 1, Math.max(0, ((ox * scale + 0.5) * nx) / w - 0.5));
      const x0 = Math.floor(gx);
      const x1 = Math.min(nx - 1, x0 + 1);
      const fx = gx - x0;
      const i00 = y0 * nx + x0, i01 = y0 * nx + x1, i10 = y1 * nx + x0, i11 = y1 * nx + x1;
      const o = oy * ow + ox;
      u[o] = factor * ((1 - fy) * ((1 - fx) * motion.u[i00] + fx * motion.u[i01]) + fy * ((1 - fx) * motion.u[i10] + fx * motion.u[i11]));
      v[o] = factor * ((1 - fy) * ((1 - fx) * motion.v[i00] + fx * motion.v[i01]) + fy * ((1 - fx) * motion.v[i10] + fx * motion.v[i11]));
    }
  }
  return { u, v, ow, oh };
}

// codes 0 … 15, 32 … 47 and 64 → 0 … 32 (a small table for the blend)
const COMPACT = new Uint8Array(256);
const EXPAND = [];
for (let c = 0; c < 256; c++) {
  const ok = c === NODATA || (c & ~(ALOFT | 15)) === 0;
  COMPACT[c] = ok ? EXPAND.length : 0;
  if (ok) EXPAND.push(c);
}
export const COMPACT_SIZE = EXPAND.length; // 33

/**
 * The code drawn at a fraction tau between code a (earlier) and b (later): the levels
 * blended linearly (a cell fades in or out instead of popping), lighter (aloft) as the
 * nearer frame says, no coverage only where there is no echo.
 */
export function blendCode(a, b, tau) {
  const la = levelOf(a);
  const lb = levelOf(b);
  const level = Math.round((1 - tau) * la + tau * lb);
  const near = tau < 0.5 ? a : b;
  const far = tau < 0.5 ? b : a;
  if (level === 0) return near & NODATA || (far & NODATA && !levelOf(near)) ? NODATA : 0;
  const flagFrom = levelOf(near) ? near : far;
  return level | (flagFrom & ALOFT);
}

/** Packed colours for every (a, b) pair at tau: one lookup per pixel in the warp. */
export function blendTable(tau, lut) {
  const table = new Uint32Array(COMPACT_SIZE * COMPACT_SIZE);
  for (let i = 0; i < COMPACT_SIZE; i++) {
    for (let j = 0; j < COMPACT_SIZE; j++) table[i * COMPACT_SIZE + j] = lut[blendCode(EXPAND[i], EXPAND[j], tau)];
  }
  return table;
}

/**
 * Draw the minute at tau between frames a and b (codes on the w × h grid) into `out`
 * (packed RGBA, ow × oh). With `flow` each output pixel x takes a at x − tau·d and b at
 * x + (1 − tau)·d (d = motion over the interval): the echoes move instead of fading.
 * Without it, a plain cross-fade. b may be null (a single frame).
 */
export function warpBlend(out, a, b, w, h, flow, tau, lut, scale = 1) {
  const ow = Math.ceil(w / scale);
  const oh = Math.ceil(h / scale);
  const table = blendTable(b ? tau : 0, lut);
  const other = b ?? a;
  const S = COMPACT_SIZE;
  const nodata = lut[NODATA];
  for (let oy = 0; oy < oh; oy++) {
    const y = oy * scale;
    for (let ox = 0; ox < ow; ox++) {
      const x = ox * scale;
      const o = oy * ow + ox;
      let ca, cb;
      if (flow && b) {
        const dx = flow.u[o];
        const dy = flow.v[o];
        const xa = Math.round(x - tau * dx);
        const ya = Math.round(y - tau * dy);
        const xb = Math.round(x + (1 - tau) * dx);
        const yb = Math.round(y + (1 - tau) * dy);
        ca = xa >= 0 && xa < w && ya >= 0 && ya < h ? a[ya * w + xa] : 0;
        cb = xb >= 0 && xb < w && yb >= 0 && yb < h ? b[yb * w + xb] : 0;
      } else {
        const p = y * w + x;
        ca = a[p];
        cb = other[p];
      }
      // the coverage does not move: no coverage where frame a has none at x itself
      if (ca === NODATA) ca = 0;
      if (cb === NODATA) cb = 0;
      const colour = table[COMPACT[ca] * S + COMPACT[cb]];
      out[o] = colour === 0 && a[y * w + x] === NODATA ? nodata : colour;
    }
  }
  return out;
}
