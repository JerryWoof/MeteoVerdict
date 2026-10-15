import assert from "node:assert/strict";
import { test } from "node:test";

import {
  COMPACT_SIZE, advanceClock, blendCode, locate, motionFor, msPerDataMinute, quantize, upsampleFlow,
  validMotion, warpBlend,
} from "./radar-motion.js";
import { ALOFT, NODATA, buildLut } from "./radar-palette.js";
import { parseStamp, timeline } from "./radar.js";
import index from "./fixtures/radar-index.json" with { type: "json" };
import motion from "./fixtures/radar-motion.json" with { type: "json" };

const steps = timeline(index);

test("where a time falls between frames", () => {
  const t0 = steps[0].time;
  assert.deepEqual(locate(steps, t0), { i: 0, tau: 0 });
  assert.deepEqual(locate(steps, t0 + 2 * 60000), { i: 0, tau: 0.4 });
  assert.deepEqual(locate(steps, t0 - 1), { i: 0, tau: 0 });
  assert.deepEqual(locate(steps, steps.at(-1).time + 1), { i: steps.length - 1, tau: 0 });
  // the nowcast steps are 10 minutes apart
  const n = steps.findIndex((s) => s.forecast);
  assert.deepEqual(locate(steps, steps[n - 1].time + 5 * 60000), { i: n - 1, tau: 0.5 });
  assert.deepEqual(locate([], 0), { i: -1, tau: 0 });
  assert.equal(quantize(parseStamp("202610151035") + 59999), parseStamp("202610151035"));
});

test("the animation clock runs, holds at the end and starts over", () => {
  const opts = { first: 0, last: 600000, rate: 60000 / msPerDataMinute(1), holdMs: 1000 };
  // 1×: five data minutes in 0.6 s
  let state = advanceClock({ ms: 0, hold: 0 }, 600, opts);
  assert.equal(state.ms, 300000);
  state = advanceClock(state, 10000, opts);
  assert.deepEqual(state, { ms: 600000, hold: 0 });
  state = advanceClock(state, 600, opts);
  assert.deepEqual(state, { ms: 600000, hold: 600 });
  state = advanceClock(state, 600, opts);
  assert.deepEqual(state, { ms: 0, hold: 0 });
  assert.equal(msPerDataMinute(2), 60);
  assert.deepEqual(advanceClock({ ms: 5, hold: 0 }, 10, { first: 3, last: 3, rate: 1 }), { ms: 3, hold: 0 });
});

test("which motion field a pair of frames uses", () => {
  const n = steps.findIndex((s) => s.forecast);
  assert.deepEqual(motionFor(index.motion, steps[1], steps[2]), { stamp: steps[2].radar, seconds: 300 });
  // the first frame has no motion of its own; the nowcast uses the newest one, scaled to 10 min
  assert.equal(motionFor(index.motion, steps[0], steps[1]).stamp, steps[1].radar);
  assert.deepEqual(motionFor(index.motion, steps[n - 1], steps[n]), { stamp: index.motion.at(-1), seconds: 600 });
  assert.equal(motionFor([], steps[0], steps[1]), null);
  assert.equal(motionFor(undefined, steps[0], steps[1]), null);
  assert.equal(motionFor(["202001010000"], steps[0], steps[1]), null); // too old
  assert.ok(validMotion(motion));
  assert.ok(!validMotion({ nx: 2, ny: 2, dt_s: 300, u: [1], v: [1] }));
});

test("coarse motion upsampled bilinearly and scaled to the interval", () => {
  const m = { nx: 2, ny: 1, dt_s: 300, u: [0, 4], v: [2, 2] };
  const flow = upsampleFlow(m, 4, 2, 600);
  assert.equal(flow.ow, 4);
  // cell centres at x = 1 and x = 3 (pixel centres 0.5 … 3.5): u ramps 0 → 4, × 2 for 10 min
  assert.deepEqual([...flow.u.slice(0, 4)], [0, 2, 6, 8]);
  assert.deepEqual([...flow.v.slice(0, 4)], [4, 4, 4, 4]);
  const half = upsampleFlow(m, 4, 2, 300, 2);
  assert.equal(half.ow, 2);
  assert.equal(half.oh, 1);
});

test("blending two codes: levels fade, aloft and coverage follow the nearer frame", () => {
  assert.equal(blendCode(4, 8, 0), 4);
  assert.equal(blendCode(4, 8, 1), 8);
  assert.equal(blendCode(4, 8, 0.5), 6);
  assert.equal(blendCode(0, 10, 0.2), 2);
  assert.equal(blendCode(0, 10, 0.04), 0);
  assert.equal(blendCode(3 | ALOFT, 5, 0.25), 4 | ALOFT);
  assert.equal(blendCode(3 | ALOFT, 5, 0.75), 5);
  assert.equal(blendCode(NODATA, NODATA, 0.3), NODATA);
  assert.equal(blendCode(0, 0, 0.3), 0);
  assert.equal(COMPACT_SIZE, 33);
});

test("warp: an echo moving one pixel a minute is drawn in between", () => {
  const w = 10;
  const h = 1;
  const a = new Uint8Array(w);
  const b = new Uint8Array(w);
  a[2] = 9; // moves 5 px to the right in the interval
  b[7] = 9;
  const lut = buildLut();
  const flow = upsampleFlow({ nx: 1, ny: 1, dt_s: 300, u: [5], v: [0] }, w, h, 300);
  const out = new Uint32Array(w);
  const at = (tau) => [...warpBlend(out, a, b, w, h, flow, tau, lut)].findIndex((c) => c === lut[9]);
  assert.equal(at(0), 2);
  assert.equal(at(0.2), 3);
  assert.equal(at(0.6), 5);
  assert.equal(at(1), 7);
  // full intensity all the way: it moves, it does not fade
  assert.equal([...warpBlend(out, a, b, w, h, flow, 0.4, lut)].filter((c) => c === lut[9]).length, 1);
  // without motion: a cross-fade, both half as strong in the middle
  const fade = [...warpBlend(out, a, b, w, h, null, 0.5, lut)];
  assert.equal(fade[2], lut[5]);
  assert.equal(fade[7], lut[5]);
  // b missing: frame a as it is; half resolution draws every other pixel
  assert.equal(warpBlend(out, a, null, w, h, null, 0.7, lut)[2], lut[9]);
  assert.equal(warpBlend(new Uint32Array(5), a, null, w, h, null, 0, lut, 2)[1], lut[9]);
});

test("warp: the coverage does not move with the echoes", () => {
  const a = new Uint8Array([NODATA, 0, 0, 0]);
  const b = new Uint8Array([NODATA, 0, 0, 0]);
  const lut = buildLut();
  const flow = upsampleFlow({ nx: 1, ny: 1, dt_s: 300, u: [2], v: [0] }, 4, 1, 300);
  const out = warpBlend(new Uint32Array(4), a, b, 4, 1, flow, 0.5, lut);
  assert.equal(out[0], lut[NODATA]);
  assert.equal(out[1], 0);
});
