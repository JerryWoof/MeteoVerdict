import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ALOFT, ALOFT_COLOURS, CATEGORIES, FILTERS, NODATA, buildLut, categoriesFrom, categoryOf, dbzLevel,
  decodePixels, filterLevels, hexRgb, isAloft, labelKey, legendRows, levelDbz, levelOf, makeClassifier,
  maxzScale, packRgba, parseFilter, rateLabel,
} from "./radar-palette.js";
import { DBZ_SCALE } from "./radar.js";
import index from "./fixtures/radar-index.json" with { type: "json" };

test("dBZ classes and categories", () => {
  assert.equal(dbzLevel(3.9), 0);
  assert.equal(dbzLevel(4), 1);
  assert.equal(dbzLevel(19.5), 4);
  assert.equal(dbzLevel(20), 5);
  assert.equal(dbzLevel(60), 15);
  assert.equal(dbzLevel(75), 15);
  assert.equal(levelDbz(5), 20);
  assert.equal(levelDbz(0), null);
  assert.equal(categoryOf(0), null);
  assert.equal(categoryOf(1), "drizzle");
  assert.equal(categoryOf(dbzLevel(24)), "light");
  assert.equal(categoryOf(dbzLevel(36)), "moderate");
  assert.equal(categoryOf(dbzLevel(44)), "heavy");
  assert.equal(categoryOf(dbzLevel(52)), "veryHeavy");
  assert.equal(categoryOf(dbzLevel(56)), "hail");
});

test("palette colours of the frames → codes", () => {
  const classify = makeClassifier();
  // the solid colours of png_masked: 4 dBZ = #380070 … 60 dBZ = #fcfcfc
  assert.equal(classify(56, 0, 112, 255), 1);
  assert.equal(classify(252, 252, 252, 255), 15);
  // lighter ones: echo aloft (palette index 135 = 4 dBZ aloft, 133 = 12 dBZ aloft)
  assert.equal(classify(139, 110, 168, 255), 1 | ALOFT);
  assert.equal(classify(177, 177, 208, 255), 3 | ALOFT);
  assert.equal(classify(254, 254, 254, 255), 15 | ALOFT);
  // the faint grey outside the coverage, transparency
  assert.equal(classify(196, 196, 196, 64), NODATA);
  assert.equal(classify(196, 196, 196, 0), 0);
  // a colour off by a few units (another decoder) still finds its class
  assert.equal(classify(1, 161, 2, 255), 5);
  const rgba = new Uint8ClampedArray([0, 0, 0, 0, 0, 160, 0, 255, 137, 184, 137, 255, 196, 196, 196, 64]);
  assert.deepEqual([...decodePixels(rgba)], [0, 5, 5 | ALOFT, NODATA]);
  assert.equal(levelOf(5 | ALOFT), 5);
  assert.ok(isAloft(5 | ALOFT));
  assert.equal(levelOf(NODATA), 0);
  assert.equal(ALOFT_COLOURS.length, DBZ_SCALE.length);
});

test("show from: the colour table drops weaker classes and echoes aloft", () => {
  const all = buildLut();
  assert.equal(all[0], 0);
  assert.equal(all[1], packRgba(...hexRgb("#380070")));
  assert.equal(all[1 | ALOFT], packRgba(...hexRgb(ALOFT_COLOURS[0])));
  assert.equal(all[NODATA], packRgba(196, 196, 196, 64));
  const moderate = buildLut({ minLevel: FILTERS.moderate.radar, aloft: FILTERS.moderate.aloft });
  assert.equal(moderate[dbzLevel(24)], 0);
  assert.equal(moderate[dbzLevel(28)], packRgba(...hexRgb("#34d800")));
  assert.equal(moderate[dbzLevel(40) | ALOFT], 0);
  const hail = buildLut({ minLevel: FILTERS.hail.radar });
  assert.equal(hail[dbzLevel(52)], 0);
  assert.notEqual(hail[dbzLevel(56)], 0);
  assert.equal(packRgba(255, 0, 0, 255), 0xff0000ff);
  assert.equal(parseFilter("heavy"), "heavy");
  assert.equal(parseFilter("x"), "all");
  assert.equal(parseFilter(undefined), "all");
});

test("legend rows in plain language, from the index or built in", () => {
  const rows = legendRows(maxzScale(index), "en");
  assert.deepEqual(rows.map((r) => r.label), ["drizzle", "light", "moderate", "heavy", "very heavy", "hail possible"]);
  assert.equal(rows[2].colours.length, 3);
  assert.equal(rows[2].from, 2.05);
  assert.equal(rows[2].to, 11.5);
  assert.equal(rows.at(-1).to, null);
  assert.equal(legendRows(maxzScale(index), "cs")[1].label, "slabé");
  const labels = { en: { drizzle: "D", light: "L", moderate: "M", heavy: "H", veryHeavy: "V", hail: "X" } };
  const built = legendRows(maxzScale({}, labels), "en");
  assert.deepEqual(built.map((r) => r.label), ["D", "L", "M", "H", "V", "X"]);
  assert.deepEqual(built.map((r) => r.dbz), [4, 20, 28, 40, 48, 56]);
  assert.equal(rateLabel(built[1].from), "0.6"); // 20 dBZ
  assert.equal(rateLabel(built[2].from), "2"); // 28 dBZ
  assert.equal(rateLabel(built[3].from), "12"); // 40 dBZ
  assert.equal(rateLabel(205), "210");
});

test("categories and the filter follow the backend's labels", () => {
  assert.equal(labelKey(" Very heavy "), "veryHeavy");
  assert.equal(labelKey("hail possible"), "hail");
  assert.equal(labelKey("storm"), null);
  // the live index calls 16 dBZ "light" (ours starts at 20)
  const cats = categoriesFrom(index.scales.maxz);
  assert.deepEqual(cats.map((c) => c.dbz), [4, 16, 28, 40, 48, 56]);
  assert.equal(categoryOf(dbzLevel(16), cats), "light");
  assert.equal(categoryOf(dbzLevel(16)), "drizzle");
  assert.deepEqual(filterLevels("light", cats), { radar: dbzLevel(16), rain: 3, aloft: false });
  assert.deepEqual(filterLevels("light"), FILTERS.light);
  assert.deepEqual(filterLevels("all", cats), { radar: 1, rain: 1, aloft: true });
  assert.deepEqual(filterLevels("hail", cats).radar, dbzLevel(56));
  // unknown or out-of-order labels: our categories
  assert.equal(categoriesFrom([[4, "#000", 0.1, "fog", "mlha"]]), CATEGORIES);
  assert.equal(categoriesFrom([[4, "#000", 0.1, "heavy"], [8, "#000", 0.1, "light"]]), CATEGORIES);
  assert.equal(categoriesFrom(undefined), CATEGORIES);
});
