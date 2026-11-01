import assert from "node:assert/strict";
import { test } from "node:test";

import { smoothDraw } from "./radar-smooth.js";
import { ALOFT, NODATA, buildLut } from "./radar-palette.js";

const lut = buildLut();
const draw = (codes, w, h, k) => smoothDraw(new Uint32Array(w * k * h * k), Uint8Array.from(codes), w, h, k, lut);

test("k = 1 is the plain drawing: every cell its own colour", () => {
  const codes = [0, 3, 8, 8 | ALOFT, NODATA, 0];
  const out = draw(codes, 3, 2, 1);
  assert.deepEqual([...out], codes.map((c) => lut[c]));
});

test("only legend colours appear, cell centres keep their class, a lone cell fades through lower classes", () => {
  const out = draw([0, 0, 0, 0, 10, 0, 0, 0, 0], 3, 3, 3);
  const allowed = new Set([0, ...Array.from({ length: 10 }, (_, l) => lut[l + 1])]);
  assert.ok([...out].every((c) => allowed.has(c)));
  assert.equal(out[4 * 9 + 4], lut[10]); // the middle sub-pixel of the middle cell
  assert.ok(out.some((c) => c !== 0 && c !== lut[10])); // soft edge
  assert.equal(out[0], 0);
});

test("no coverage stays where the nearest cell has none, and an echo never takes its colour", () => {
  const out = draw([NODATA, 5, NODATA, 5], 2, 2, 2);
  assert.equal(out[0], lut[NODATA]);
  assert.ok([...out].every((c) => c === lut[NODATA] || c === lut[5] || c === lut[3] || c === lut[4] || c === lut[2] || c === lut[1] || c === 0));
});

test("the aloft flag follows the cell, a hidden class stays hidden", () => {
  const out = draw([6 | ALOFT, 6 | ALOFT], 2, 1, 2);
  assert.ok([...out].every((c) => c === lut[6 | ALOFT]));
  const hidden = buildLut({ minLevel: 5 });
  const o2 = smoothDraw(new Uint32Array(4), Uint8Array.from([3, 3]), 2, 1, 2, hidden);
  assert.ok([...o2].every((c) => c === 0));
});
