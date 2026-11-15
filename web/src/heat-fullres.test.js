import assert from "node:assert/strict";
import { test } from "node:test";
import { coarseZoomLimit, isSlowConnection, wantFullImages } from "./heat-fullres.js";

const coarse = { bounds: [12.0, 48.4972, 19.0044, 51.1], width: 1347 };

test("the coarse set turns blocky at about zoom 8", () => {
  const z = coarseZoomLimit(coarse);
  assert.ok(z > 7.5 && z < 8.5, String(z));
  assert.equal(coarseZoomLimit(null), Infinity);
  assert.equal(coarseZoomLimit({ bounds: [1, 1, 1, 2], width: 10 }), Infinity);
});

test("slow connections", () => {
  assert.equal(isSlowConnection(undefined), false);
  assert.equal(isSlowConnection({ effectiveType: "4g" }), false);
  assert.equal(isSlowConnection({ effectiveType: "2g" }), true);
  assert.equal(isSlowConnection({ effectiveType: "slow-2g" }), true);
  assert.equal(isSlowConnection({ effectiveType: "4g", saveData: true }), true);
});

test("when the full images are wanted", () => {
  const z = coarseZoomLimit(coarse);
  assert.equal(wantFullImages({ reason: "zoom", zoom: z - 0.1, coarse }), false);
  assert.equal(wantFullImages({ reason: "zoom", zoom: z + 0.1, coarse }), true);
  assert.equal(wantFullImages({ reason: "zoom", zoom: 12, coarse: null }), false);
  assert.equal(wantFullImages({ reason: "point", coarse }), true);
  assert.equal(wantFullImages({ reason: "point", coarse, connection: { saveData: true } }), true);
  assert.equal(wantFullImages({ reason: "idle", coarse }), true);
  assert.equal(wantFullImages({ reason: "idle", coarse, connection: { saveData: true } }), false);
  assert.equal(wantFullImages({ reason: "idle", coarse, connection: { effectiveType: "2g" } }), false);
  assert.equal(wantFullImages({ reason: "point", coarse, haveFull: true }), false);
  assert.equal(wantFullImages({ reason: "other", coarse }), false);
});
