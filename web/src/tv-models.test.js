import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { mapModelOptions, modelPeriods, parseModelParts, parseModels } from "./models.js";
import {
  BEYOND, colorFor, labelFor, okresColours, parseOutlook, playSteps, rowFor, summary, valueFor,
} from "./tv.js";

const read = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));
// the real outlook.json of 12 Oct 2026 (77 okresy) and the models' parts of day for Praha
// and Benešov from the saved Open-Meteo answer of the same morning
const OUTLOOK = parseOutlook(read("outlook.json"));
const D2_DOC = read("models-parts-dwd_icon_d2.json");
const IFS_DOC = read("models-parts-ecmwf_ifs025.json");
const INDEX = read("models-parts-index.json");
const D2 = parseModelParts(D2_DOC, OUTLOOK);
const IFS = parseModelParts(IFS_DOC, OUTLOOK);
const DAY = "2026-10-13";

test("the map's selector: models by mean rank over Czechia, then the unranked by name", () => {
  const names = { dwd_icon_eu: "DWD ICON-EU", ecmwf_ifs: "ECMWF IFS HRES 9 km" };
  const options = mapModelOptions(INDEX, names);
  assert.equal(options.length, 11);
  const ranks = options.map((o) => o.rank);
  assert.deepEqual(ranks, [...ranks].sort((a, b) => a - b));
  assert.deepEqual(options[0], { model: "dwd_icon_eu", name: "DWD ICON-EU", rank: INDEX.models[0].mean_rank, position: 1 });
  assert.equal(options.find((o) => o.model === "ecmwf_ifs").name, "ECMWF IFS HRES 9 km");
  // models without a mean rank come after the ranked ones, by name
  const index = {
    models: [{ model: "zz", mean_rank: null }, { model: "b", mean_rank: 2 }, { model: "aa", mean_rank: null }, { model: "a", mean_rank: 1.5 }],
  };
  assert.deepEqual(mapModelOptions(index).map((o) => [o.model, o.position]), [["a", 1], ["b", 2], ["aa", null], ["zz", null]]);
  assert.deepEqual(mapModelOptions(null), []);
});

test("one model for the whole map: our days and okresy, its own values", () => {
  assert.equal(D2.single, true);
  assert.equal(D2.model, "dwd_icon_d2");
  assert.equal(D2.lastHour, Date.parse(D2_DOC.last_hour));
  assert.deepEqual(D2.days, OUTLOOK.days);
  assert.equal(D2.okresy.length, 77);
  const row = rowFor(D2, "CZ0201", DAY, "afternoon");
  const i = D2_DOC.days.indexOf(DAY) * 5 + 2;
  assert.equal(row.tmax, D2_DOC.okresy.CZ0201.tmax[i]);
  assert.equal(row.precipitation, D2_DOC.okresy.CZ0201.precipitation[i]);
  assert.equal(row.symbol, D2_DOC.symbols[D2_DOC.okresy.CZ0201.symbol[i]]);
  assert.equal(row.rain_probability, null);
  assert.equal(row.single, true);
  // the day's sunrise and sunset from our outlook, for the night symbols
  assert.equal(row.sunrise, rowFor(OUTLOOK, "CZ0201", DAY, "afternoon").sunrise);
  assert.equal(parseModelParts(null, OUTLOOK), null);
});

test("the same values as the okres panel computes from the okres's own file", () => {
  const panel = modelPeriods(parseModels(read("models-CZ0201.json")), "dwd_icon_d2");
  for (const [key, ours] of panel) {
    const [day, part] = key.split("|");
    const row = rowFor(D2, "CZ0201", day, part);
    if (!row) continue; // a day our outlook does not show
    assert.ok(!row.beyond, key);
    assert.ok(Math.abs(row.tmax - ours.tmax) < 0.051, key);
    assert.ok(Math.abs(row.precipitation - ours.precipitation) < 0.006, key);
    assert.equal(row.symbol, ours.symbol, key);
  }
});

test("beyond the model's horizon: grey okresy with \"–\", left out of the summary and play", () => {
  // ICON-D2 ends on 14 Oct: 15 Oct onwards there is nothing
  const late = rowFor(D2, "CZ0201", "2026-10-15", "afternoon");
  assert.equal(late.beyond, true);
  assert.equal(labelFor(late, "temperature", "afternoon"), "–");
  assert.equal(labelFor(late, "precipitation", "afternoon"), "–");
  assert.equal(okresColours(D2, "2026-10-15", "afternoon", "temperature").get("CZ0201"), BEYOND);
  // okresy the file does not have (the fixture: only Praha and Benešov) are grey too
  assert.equal(rowFor(D2, "CZ0423", DAY, "afternoon").beyond, true);
  assert.equal(summary(D2, "2026-10-15", "afternoon"), null);
  const week = playSteps(D2, "week", DAY);
  assert.ok(week.every((s) => s.day <= "2026-10-14"));
  assert.ok(week.length < playSteps(OUTLOOK, "week", DAY).length);
  // a global model covers the whole week
  assert.ok(!rowFor(IFS, "CZ0201", "2026-10-17", "day").beyond);
});

test("a single model's rain: mm on the map and in the colours, and the summary counts ≥ 0.3 mm", () => {
  const row = { single: true, precipitation: 1.24, rain_probability: null, tmax: 10 };
  assert.equal(valueFor(row, "precipitation", "afternoon"), 1.24);
  assert.equal(labelFor(row, "precipitation", "afternoon"), "1.2 mm");
  // our combination keeps the probability
  assert.equal(labelFor({ rain_probability: 0.6, precipitation: 3 }, "precipitation", "afternoon"), "60 %");
  const colours = okresColours(IFS, DAY, "afternoon", "precipitation");
  const ifsRow = rowFor(IFS, "CZ0201", DAY, "afternoon");
  assert.equal(colours.get("CZ0201"), colorFor(ifsRow.precipitation, "precipitationMm"));
  for (const part of ["night", "morning", "afternoon", "evening", "day"]) {
    const s = summary(IFS, DAY, part);
    assert.equal(s.single, true);
    assert.equal(s.okresy, 2); // only the okresy with values
    const wet = ["CZ0100", "CZ0201"].filter((c) => rowFor(IFS, c, DAY, part).precipitation >= 0.3).length;
    assert.equal(s.rainy, wet);
    const temps = ["CZ0100", "CZ0201"].map((c) => valueFor(rowFor(IFS, c, DAY, part), "temperature", part));
    assert.equal(s.warmest.value, Math.max(...temps));
  }
  assert.equal(summary(OUTLOOK, DAY, "afternoon").single, false);
  // never showers: one model has no probability
  for (const row2 of IFS.rows.values()) assert.notEqual(row2.symbol, "showers");
});
