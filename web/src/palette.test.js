import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import * as palette from "./palette.js";
import * as tv from "./tv.js";

const source = (name) => readFileSync(new URL(`./${name}`, import.meta.url), "utf8");

test("the forecast map and the measured page share one palette", () => {
  // tv.js re-exports the very same scales and functions
  for (const name of ["RAMPS", "colorFor", "rampKey", "NEUTRAL", "BEYOND"]) assert.equal(tv[name], palette[name], name);
  // both pages draw the legend with palette.renderScale, and neither builds its own
  for (const file of ["tv-page.js", "station-page.js"]) {
    const code = source(file);
    assert.match(code, /import \{ renderScale \} from "\.\/palette\.js"/, file);
    assert.doesNotMatch(code, /linear-gradient/, file);
  }
  // the measured map's okres fills and station dots take the palette's colours
  assert.match(source("measured-map-view.js"), /from "\.\/palette\.js"/);
  assert.doesNotMatch(source("measured-map-view.js"), /RAMPS = \{/);
});

test("gust and sunshine scales are derived in the forecast's style", () => {
  const colours = (key) => palette.RAMPS[key].map(([, rgb]) => rgb.join(","));
  // gusts: the wind's colours, stops 1.4 times the wind's
  assert.deepEqual(colours("gust"), colours("wind"));
  assert.deepEqual(palette.RAMPS.gust.map(([v]) => v), [0, 6, 11, 20, 28]);
  // sunshine: the cloud scale turned round (overcast grey → clear sky's pale yellow)
  assert.deepEqual(colours("sunshine"), [...colours("cloud")].reverse());
  assert.deepEqual(palette.RAMPS.sunshine.map(([v]) => v), [0, 3, 6]);
  assert.equal(palette.colorFor(6, "sunshine"), palette.colorFor(0, "cloud"));
  // measured rain is in mm, as a single model's on the forecast map
  assert.equal(palette.rampKey("precipitation", true), "precipitationMm");
  assert.equal(palette.rampKey("temperature", true), "temperature");
});

test("the legend: bar and ends", () => {
  assert.equal(palette.scale("temperature").ends, "-15° … 32°");
  assert.equal(palette.scale("precipitation").ends, "0 % … 100 %");
  assert.equal(palette.scale("precipitationMm").ends, "0 mm … 10 mm");
  assert.equal(palette.scale("gust").ends, "0 m/s … 28 m/s");
  assert.equal(palette.scale("sunshine").ends, "0 h … 6 h");
  assert.match(palette.scale("wind").gradient, /^linear-gradient\(to right, #f4f1ea 0%/);
  assert.equal(palette.scale("nothing"), null);
});
