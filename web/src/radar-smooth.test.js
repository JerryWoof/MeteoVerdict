import assert from "node:assert/strict";
import { test } from "node:test";

import { smoothDraw, smoothField } from "./radar-smooth.js";
import { ALOFT, NODATA, buildLut } from "./radar-palette.js";

const lut = buildLut();
const draw = (codes, w, h, k, mode, table = lut) => smoothDraw(new Uint32Array(w * k * h * k), Uint8Array.from(codes), w, h, k, table, mode);
const legend = new Set([0, ...Array.from({ length: 15 }, (_, l) => lut[l + 1]), ...Array.from({ length: 15 }, (_, l) => lut[(l + 1) | ALOFT])]);

test("bands: only legend colours, the middle of a big echo keeps its class", () => {
  const codes = new Array(25).fill(0);
  for (const p of [6, 7, 8, 11, 12, 13, 16, 17, 18]) codes[p] = 10;
  const out = draw(codes, 5, 5, 3, "bands");
  assert.ok([...out].every((c) => legend.has(c)));
  assert.equal(out[7 * 15 + 7], lut[10]);
  assert.equal(out[0], 0);
});

test("the echo grows by less than a cell and a lone cell stays a small blob", () => {
  const codes = new Array(49).fill(0);
  codes[24] = 8; // 7 × 7, the middle cell
  const k = 4;
  const out = draw(codes, 7, 7, k, "bands");
  const shown = [];
  out.forEach((c, o) => c && shown.push([o % 28, Math.floor(o / 28)]));
  assert.ok(shown.length > 0);
  // the cell spans pixels 12 … 15; nothing beyond half a cell (2 pixels) outside it
  for (const [x, y] of shown) assert.ok(x >= 10 && x <= 17 && y >= 10 && y <= 17, `${x},${y}`);
});

test("gradient blends between the colours of neighbouring classes, never outside the two", () => {
  const out = draw([3, 3, 3, 3, 4, 4, 4, 4, 3, 3, 3, 3, 3, 3, 3, 3], 4, 4, 4, "gradient");
  const blended = [...out].filter((c) => c && !legend.has(c));
  assert.ok(blended.length > 0);
  const [lo, hi] = [lut[3], lut[4]];
  for (const c of blended) {
    for (const s of [0, 8, 16]) {
      const v = (c >>> s) & 255;
      const [a, b] = [(lo >>> s) & 255, (hi >>> s) & 255].sort((x, y) => x - y);
      assert.ok(v >= a - 1 && v <= b + 1);
    }
  }
});

test("no coverage stays where the nearest cell has none; aloft follows the echo; hidden classes stay hidden", () => {
  assert.equal(draw([NODATA, 0], 2, 1, 2, "bands")[0], lut[NODATA]);
  const light = draw([6 | ALOFT, 6 | ALOFT, 6 | ALOFT, 6 | ALOFT], 2, 2, 2, "bands");
  assert.ok([...light].every((c) => c === lut[6 | ALOFT]));
  const hidden = buildLut({ minLevel: 5 });
  for (const mode of ["bands", "gradient"]) {
    const o = draw([3, 3, 3, 3], 2, 2, 2, mode, hidden);
    assert.ok([...o].every((c) => c === 0), mode);
  }
});

test("the level field is not diluted by empty cells around", () => {
  const codes = Uint8Array.from([0, 0, 0, 9, 9, 0, 0, 0, 0]);
  const f = smoothField(codes, 3, 3);
  assert.ok(Math.abs(f.level[3] - 9) < 1e-4);
  assert.ok(f.coverage[3] > 0.5 && f.coverage[0] < f.coverage[3]);
});
