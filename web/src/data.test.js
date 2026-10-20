import assert from "node:assert/strict";
import { test } from "node:test";

import {
  stationsIn,
  NO_DATA, P_BEST_MIN, TOO_FEW, bestByRegion, fillExpression, modelColors, records,
  closeCodes, regionColor, smallSampleCodes, stationFeatures, withKrajFallback,
} from "./data.js";


// the layout `mvd aggregate` writes (aggregate.JSON_COLUMNS, a subset)
const DOC = {
  columns: ["region", "region_name", "lead_day", "model", "mae", "enough_stations", "rank", "tied_with_best"],
  rows: [
    ["CZ020", "Středočeský kraj", 1, "icon", 1.2, true, 1, false],
    ["CZ020", "Středočeský kraj", 1, "ifs", 1.25, true, 2, true],
    ["CZ020", "Středočeský kraj", 1, "blend", 1.1, true, null, true],
    ["CZ020", "Středočeský kraj", 2, "ifs", 1.5, true, 1, false],
    ["CZ010", "Praha", 1, "ifs", 1.0, false, 1, false],
  ],
};
const MODELS = { icon: "DWD ICON-D2", ifs: "ECMWF IFS", blend: "Mean of all models" };

test("records", () => {
  assert.deepEqual(records(DOC)[0].region_name, "Středočeský kraj");
  assert.deepEqual(records(null), []);
});

test("colours follow the model order and skip the blend", () => {
  assert.deepEqual(Object.keys(modelColors(MODELS)), ["icon", "ifs"]);
});

test("every model of the catalogue gets its own colour", () => {
  // 20 models in models.yaml (19 enabled, 1 disabled) plus the blend
  const many = Object.fromEntries([...Array(20).keys()].map((i) => [`m${i}`, `M${i}`]));
  const colors = modelColors({ ...many, blend: "Mean" });
  assert.equal(new Set(Object.values(colors)).size, 20);
  assert.equal(colors.blend, undefined);
  assert.ok(!Object.values(colors).includes(NO_DATA) && !Object.values(colors).includes(TOO_FEW));
});

test("best model per region at one lead day, with ties but without the blend", () => {
  const best = bestByRegion(records(DOC), 1);
  assert.deepEqual(best.get("CZ020"), {
    name: "Středočeský kraj", model: "icon", mae: 1.2, tied: ["ifs"], enough: true, ranked: true,
    borrowed: 0, pBest: null, clear: true, small: false,
  });
  assert.equal(bestByRegion(records(DOC), 2).get("CZ020").model, "ifs");
});

test("an unranked variable's best is never a model with too short a record", () => {
  const rows = [
    { region: "cz", region_name: "Česko", lead_day: 1, model: "icon", mae: 1.2, rank: null, enough_stations: true },
    { region: "cz", region_name: "Česko", lead_day: 1, model: "new", mae: 0.9, rank: null, enough_stations: true, short_record: true },
  ];
  assert.equal(bestByRegion(rows, 1).get("cz").model, "icon");
});

test("region colours: best model, too few stations, no data", () => {
  const colors = modelColors(MODELS);
  const best = bestByRegion(records(DOC), 1);
  assert.equal(regionColor(best.get("CZ020"), colors), colors.icon);
  assert.equal(regionColor(best.get("CZ010"), colors), TOO_FEW);
  assert.equal(regionColor(undefined, colors), NO_DATA);
  const expression = fillExpression(best, colors);
  assert.deepEqual(expression.slice(0, 4), ["match", ["get", "code"], "CZ020", colors.icon]);
  assert.equal(expression.at(-1), NO_DATA);
  assert.equal(fillExpression(new Map(), colors), NO_DATA);
});

test("station dots only where there are scores", () => {
  const stations = { columns: ["id", "name", "lat", "lon"], rows: [["CZ020", "A", 50, 14], ["x", "B", 49, 15]] };
  const points = stationFeatures(stations, bestByRegion(records(DOC), 1), modelColors(MODELS));
  assert.equal(points.features.length, 1);
  assert.deepEqual(points.features[0].geometry.coordinates, [14, 50]);
});

test("unranked variables take the lowest MAE, never the blend", () => {
  const doc = {
    columns: ["region", "region_name", "lead_day", "model", "mae", "enough_stations", "rank"],
    rows: [
      ["CZ020", "S", 1, "icon", 1.4, true, null],
      ["CZ020", "S", 1, "ifs", 1.3, true, null],
      ["CZ020", "S", 1, "blend", 1.0, true, null],
    ],
  };
  const entry = bestByRegion(records(doc), 1).get("CZ020");
  assert.equal(entry.model, "ifs");
  assert.equal(entry.ranked, false);
});

test("an okres knows how many stations it borrowed", () => {
  const doc = {
    columns: ["region", "region_name", "lead_day", "model", "mae", "enough_stations", "rank", "borrowed"],
    rows: [["CZ0201", "Benešov", 1, "ifs", 1.1, true, 1, 2]],
  };
  const entry = bestByRegion(records(doc), 1).get("CZ0201");
  assert.equal(entry.borrowed, 2);
});


test("station pages of an okres: all its stations by name, also by kraj", () => {
  const table = {
    columns: ["id", "name", "okres_code", "kraj_code"],
    rows: [
      ["b", "Žatec", "CZ0424", "CZ042"],
      ["a", "Doksany", "CZ0423", "CZ042"],
      ["c", "Ústí nad Labem", "CZ0427", "CZ042"],
      ["d", "Bílá Třemešná", "CZ0423", "CZ042"],
    ],
  };
  assert.deepEqual(stationsIn(table, "CZ0423").map((s) => s.name), ["Bílá Třemešná", "Doksany"]);
  assert.equal(stationsIn(table, "CZ042").length, 4);
  assert.deepEqual(stationsIn(table, "CZ0999"), []);
  assert.deepEqual(stationsIn(null, "CZ0423"), []);
});

test("a close win keeps its model colour (hatched), and the small-sample regions", () => {
  const rows = [
    { region: "a", region_name: "A", lead_day: 1, model: "icon", mae: 1, rank: 1, enough_stations: true, p_best: 0.9 },
    { region: "b", region_name: "B", lead_day: 1, model: "icon", mae: 1, rank: 1, enough_stations: true, p_best: 0.45, small_sample: true },
    { region: "b", region_name: "B", lead_day: 1, model: "ifs", mae: 1.01, rank: 2, enough_stations: true, p_best: 0.55, tied_with_best: true },
  ];
  const colors = modelColors(MODELS);
  const best = bestByRegion(rows, 1);
  assert.equal(P_BEST_MIN, 0.6);
  assert.deepEqual([best.get("a").clear, best.get("a").pBest], [true, 0.9]);
  assert.equal(regionColor(best.get("a"), colors), colors.icon);
  // the rank-1 model leads on MAE but is best in fewer than 60 % of the resamples
  assert.deepEqual([best.get("b").model, best.get("b").clear, best.get("b").small], ["icon", false, true]);
  assert.equal(regionColor(best.get("b"), colors), colors.icon);
  assert.deepEqual(closeCodes(best), ["b"]);
  assert.equal(regionColor(bestByRegion(rows, 1, 0.4).get("b"), colors), colors.icon);
  assert.deepEqual(smallSampleCodes(best), ["b"]);
});

test("an okres without a ranking takes its kraj's best model", () => {
  const row = (region, model, enough = true) => ({ region, region_name: region, lead_day: 1, model, mae: 1, rank: 1, enough_stations: enough, p_best: 0.9 });
  const okres = bestByRegion([row("CZ0201", "icon"), row("CZ0202", "ifs", false)], 1);
  okres.set("CZ0203", { name: "X", model: null, enough: true, tied: [] });
  const merged = withKrajFallback(okres, bestByRegion([row("CZ020", "aladin")], 1));
  assert.equal(merged.get("CZ0201").model, "icon");
  assert.deepEqual([merged.get("CZ0202").model, merged.get("CZ0202").fallback], ["aladin", true]);
  assert.deepEqual([merged.get("CZ0203").model, merged.get("CZ0203").name], ["aladin", "X"]);
});
