import assert from "node:assert/strict";
import { test } from "node:test";

import { compareSeries, errorSummary, modelOptions, sizeClass, splitModelHash, withModelHash } from "./station-model.js";

const t = (key) => key;

test("the model choice lives in a suffix of the hash and the defaults leave it out", () => {
  assert.deepEqual(splitModelHash("#2026-10-19/day/temperature/tp/stations;m=dwd_icon_d2;l=2"), {
    hash: "#2026-10-19/day/temperature/tp/stations", model: "dwd_icon_d2", lead: 2,
  });
  assert.deepEqual(splitModelHash("#kinds/0-20000-0-11464;m=blend"), { hash: "#kinds/0-20000-0-11464", model: "blend", lead: 1 });
  assert.deepEqual(splitModelHash("#kinds"), { hash: "#kinds", model: null, lead: null });
  assert.equal(splitModelHash("#kinds;m=x;l=9").lead, 1);
  assert.equal(withModelHash("#kinds/S1", { model: "ai", lead: 1 }), "#kinds/S1");
  assert.equal(withModelHash("#kinds/S1", { model: "blend", lead: 1 }), "#kinds/S1;m=blend");
  assert.equal(withModelHash("#kinds/S1;m=blend", { model: "ecmwf_ifs", lead: 2 }), "#kinds/S1;m=ecmwf_ifs;l=2");
  assert.equal(withModelHash("", { model: "ai", lead: 2 }), "#;m=ai;l=2");
});

test("options: AI, the blend, then the models in a fixed order", () => {
  const options = modelOptions({ models: { ncep_gfs_global: "GFS", blend: "x", chmi_aladin_cz_1km: "ALADIN", zzz: "Z" } }, t);
  assert.deepEqual(options.map((o) => o.id), ["ai", "blend", "chmi_aladin_cz_1km", "ncep_gfs_global", "zzz"]);
  assert.deepEqual(modelOptions(null, t).map((o) => o.id), ["ai", "blend"]);
});

const doc = {
  from: "2026-10-01",
  to: "2026-10-04",
  obs: { tmax: [10, 12, null, 8] },
  series: { tmax: { 1: { blend: [11, 11, 13, null] }, 2: { blend: [9, 9, 9, 9] } } },
};

test("forecast minus measured per day, with gaps where either is missing", () => {
  const s = compareSeries(doc, null, "blend", 1, "tmax");
  assert.deepEqual(s.days, ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]);
  assert.deepEqual(s.err, [1, -1, null, null]);
  assert.equal(s.hasModel, true);
  const summary = errorSummary(s);
  assert.equal(summary.n, 2);
  assert.equal(summary.mae, 1);
  assert.equal(summary.bias, 0);
  assert.equal(compareSeries(doc, null, "blend", 2, "tmax").err[0], -1);
});

test("a model without values is reported, AI comes only from its own file", () => {
  assert.equal(compareSeries(doc, null, "ecmwf_ifs", 1, "tmax").hasModel, false);
  assert.equal(compareSeries(doc, null, "ai", 1, "tmax").hasModel, false);
  const ai = { series: { tmax: { 1: { ai: [9, 12, 12, 8] } } } };
  assert.deepEqual(compareSeries(doc, ai, "ai", 1, "tmax").err, [-1, 0, null, 0]);
  assert.equal(errorSummary(compareSeries(doc, null, "ecmwf_ifs", 1, "tmax")), null);
  assert.equal(compareSeries(null, null, "blend", 1, "tmax"), null);
});

test("size of a difference", () => {
  assert.equal(sizeClass(0.8, "°C"), "small");
  assert.equal(sizeClass(-2.5, "°C"), "medium");
  assert.equal(sizeClass(3.1, "m/s"), "large");
  assert.equal(sizeClass(4, "mm"), "medium");
});
