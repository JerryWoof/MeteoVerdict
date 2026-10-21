import assert from "node:assert/strict";
import { test } from "node:test";

import { compareSeries, errorKeyFor, errorLookup, okresErrors, errorSummary, modelOptions, sizeClass, splitModelHash, withModelHash } from "./station-model.js";

const t = (key) => key;

test("the model choice lives in a suffix of the hash and the defaults leave it out", () => {
  assert.deepEqual(splitModelHash("#2026-10-19/day/temperature/tp/stations;m=dwd_icon_d2;l=2"), {
    hash: "#2026-10-19/day/temperature/tp/stations", model: "dwd_icon_d2", lead: 2,
  });
  assert.deepEqual(splitModelHash("#kinds/0-20000-0-11464;m=blend"), { hash: "#kinds/0-20000-0-11464", model: "blend", lead: 1 });
  assert.deepEqual(splitModelHash("#kinds"), { hash: "#kinds", model: null, lead: null });
  assert.equal(splitModelHash("#kinds;m=x;l=9").lead, 1);
  const base = { lead: 1, err: "tmax" };
  assert.equal(withModelHash("#kinds/S1", { ...base, model: "blend" }), "#kinds/S1");
  assert.equal(withModelHash("#kinds/S1", { ...base, model: "ai" }), "#kinds/S1;m=ai");
  assert.equal(withModelHash("#kinds/S1;m=ai", { ...base, model: "ecmwf_ifs", lead: 2 }), "#kinds/S1;m=ecmwf_ifs;l=2");
  assert.equal(withModelHash("", { ...base, model: "blend", lead: 2 }), "#;m=blend;l=2");
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

test("the error choice rides in the hash after the model and lead; the maximum is the default", () => {
  assert.deepEqual(splitModelHash("#2026-10-19/day/temperature/tp/stations;m=blend;l=2;e=tmin"), {
    hash: "#2026-10-19/day/temperature/tp/stations", model: "blend", lead: 2, err: "tmin",
  });
  assert.deepEqual(splitModelHash("#x;m=ai;e=r"), { hash: "#x", model: "ai", lead: 1, err: "r" });
  assert.equal(splitModelHash("#x;m=ai;e=none").err, null); // the measured values
  assert.equal(splitModelHash("#x;m=ai;e=gust").err, undefined); // only the mapped values
  assert.equal(withModelHash("#x", { model: "blend", lead: 1, err: "wind" }), "#x;m=blend;e=wind");
  assert.equal(withModelHash("#x", { model: "blend", lead: 2, err: "tmin" }), "#x;m=blend;l=2;e=tmin");
  assert.equal(withModelHash("#x", { model: "blend", lead: 1, err: null }), "#x;m=blend;e=none");
  assert.equal(withModelHash("#x;m=ai;e=r", { model: "blend", lead: 1, err: "tmax" }), "#x");
});

test("the day's errors per station, in the unit (the file has tenths), null where missing", () => {
  const file = {
    scale: 10,
    stations: ["A", "B", "C"],
    e: { tmax: { 1: { blend: [12, null, -5] } }, r: { 1: { blend: [null, null, null] } } },
  };
  const { byId, hasModel } = errorLookup(file, "blend", 1, "tmax");
  assert.equal(hasModel, true);
  assert.deepEqual([...byId], [["A", 1.2], ["B", null], ["C", -0.5]]);
  assert.equal(byId.has("D"), false); // not among the stations with stored forecasts
  assert.equal(errorLookup(file, "ai", 1, "tmax").hasModel, false);
  assert.equal(errorLookup(file, "blend", 2, "tmax").hasModel, false);
  assert.equal(errorLookup(null, "blend", 1, "tmax").hasModel, false);
});

test("the Weather map's error mode rides in the hash as ;w= (the model's error is the default)", () => {
  assert.equal(splitModelHash("#x;m=ai;e=tmax;w=none").wx, "none");
  assert.equal(splitModelHash("#x;m=ai;w=abs").wx, "abs");
  assert.equal(splitModelHash("#x;m=ai;e=tmax").wx, undefined); // an old link: the default
  const base = { model: "blend", lead: 1, err: "tmax" };
  assert.equal(withModelHash("#d", { ...base, wx: "bias" }), "#d");
  assert.equal(withModelHash("#d", { ...base, wx: "none" }), "#d;m=blend;w=none");
  assert.equal(withModelHash("#d", { ...base, err: null, wx: "abs" }), "#d;m=blend;e=none;w=abs");
});

test("the error of an okres is the mean of its stations with a value", () => {
  assert.equal(errorKeyFor("temperature", "night"), "tmin");
  assert.equal(errorKeyFor("temperature", "day"), "tmax");
  assert.equal(errorKeyFor("sunshine", "day"), null);
  const byId = new Map([["a", 2], ["b", -1], ["c", null], ["d", 5]]);
  const stations = [{ id: "a", okres: "X" }, { id: "b", okres: "X" }, { id: "c", okres: "X" }, { id: "d", okres: "Nowhere" }, { id: "z", okres: "X" }];
  const out = okresErrors(byId, stations, (name) => (name === "X" ? "CZ1" : null));
  assert.deepEqual([...out], [["CZ1", { n: 2, bias: 0.5, mae: 1.5 }]]);
});
